#!/usr/bin/env python3
"""Method v1 pilot: generate -> authorizer verification -> schema supplement (<=2 rounds).

Only the plumbing is exercised here; retrieval for hallucinated names falls back to
name similarity until the BGE column index is wired in.
"""

import argparse
import difflib
import importlib.util
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

import sqlglot
from sqlglot import exp
from transformers import AutoTokenizer

BASE = Path("/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025")
MINIDEV = Path("/root/fsas/home/xiaotao/xiaotao/MINIDEV")
FIXED = BASE / "fixed_k_fk_20261029"
SOURCE = MINIDEV / "model_eval/generate_predictions.py"

spec = importlib.util.spec_from_file_location("bird_generator", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def load_metadata():
    meta = json.loads((MINIDEV / "dev_tables.json").read_text())
    by_db = {}
    for item in meta:
        columns = {}
        for index, (table_idx, column) in enumerate(item["column_names_original"]):
            if index == 0 and column == "*":
                continue
            table = item["table_names_original"][table_idx]
            columns[f"{table.lower()}.{column.lower()}"] = {
                "table": table, "column": column,
                "type": item["column_types"][index],
                "pk": index in item["primary_keys"],
            }
        fks = []
        for left, right in item["foreign_keys"]:
            left_col = item["column_names_original"][left]
            right_col = item["column_names_original"][right]
            left_name = f"{item['table_names_original'][left_col[0]].lower()}.{left_col[1].lower()}"
            right_name = f"{item['table_names_original'][right_col[0]].lower()}.{right_col[1].lower()}"
            fks.append((left_name, right_name))
        by_db[item["db_id"]] = {"columns": columns, "fks": fks}
    return by_db


def schema_lines(columns, meta):
    lines = []
    for key in columns:
        info = meta["columns"].get(key.lower())
        if info is None:
            continue
        suffix = "; primary key" if info["pk"] else ";"
        lines.append(f"table {info['table']}; column {info['column']}; type {info['type']}{suffix}")
    return lines


def authorizer_check(db_path, sql, allowed_columns, timeout=60.0):
    allowed_tables = {c.split(".")[0] for c in allowed_columns}
    hits = []
    started = time.perf_counter()
    deadline = started + timeout
    con = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)

    def authorizer(action, arg1, arg2, dbname, trigger):
        if action == sqlite3.SQLITE_READ:
            table = (arg1 or "").lower()
            column = (arg2 or "").lower()
            if table not in allowed_tables or (column and f"{table}.{column}" not in allowed_columns):
                hits.append(f"{table}.{column}" if column else table)
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    con.set_authorizer(authorizer)
    con.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 20000)
    try:
        con.execute("PRAGMA query_only = ON")
        con.execute("EXPLAIN QUERY PLAN " + sql).fetchmany(50)
        return "ok", hits
    except Exception:
        return ("denied" if hits else "error"), hits
    finally:
        con.close()


def parse_refs(sql):
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return set(), set()
    derived = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for sub in tree.find_all(exp.Subquery):
        if sub.alias:
            derived.add(sub.alias.lower())
    aliases, tables = {}, set()
    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name:
            continue
        if table.alias:
            aliases[table.alias.lower()] = name
        if name not in derived:
            tables.add(name)
    cols = set()
    for column in tree.find_all(exp.Column):
        table = (column.table or "").lower()
        name = (column.name or "").lower()
        if table and name:
            cols.add(f"{aliases.get(table, table)}.{name}")
    return tables, cols


def nearest_columns(db_meta, wanted, limit=3):
    keys = list(db_meta["columns"])
    scored = []
    for key in keys:
        score = difflib.SequenceMatcher(None, wanted.lower(), key).ratio()
        if score >= 0.6:
            scored.append((score, key))
    scored.sort(reverse=True)
    return [key for _, key in scored[:limit]]


def supplement(db_meta, denied, visible, cap=12):
    added = []
    for ref in denied:
        table, _, column = ref.partition(".")
        direct = ref if ref in db_meta["columns"] else None
        if direct is None and column:
            direct = f"{table}.{column}"
        if direct in db_meta["columns"]:
            added.append(direct)
        elif column:
            added.extend(nearest_columns(db_meta, f"{table}.{column}"))
        else:
            candidates = [k for k in db_meta["columns"] if k.split(".")[0] == ref]
            added.extend(candidates[:4])
    for left, right in db_meta["fks"]:
        for ref in list(added):
            if ref == left and right not in visible:
                added.append(right)
            if ref == right and left not in visible:
                added.append(left)
    result = []
    for ref in added:
        if ref not in visible and ref not in result:
            result.append(ref)
    return result[:cap]


SAMPLE_CACHE = {}


def sample_values(db_path, table, column, limit=5, timeout=3.0):
    key = (str(db_path), table, column)
    if key in SAMPLE_CACHE:
        return SAMPLE_CACHE[key]
    started = time.perf_counter()
    deadline = started + timeout
    con = None
    try:
        con = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
        con.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 20000)
        rows = con.execute(
            f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT {limit}'
        ).fetchall()
        values = [str(r[0])[:40] for r in rows]
    except Exception:
        values = []
    finally:
        if con is not None:
            con.close()
    SAMPLE_CACHE[key] = values
    return values


def near_name_hints(db_meta, visible, db_path, max_hints=2, threshold=0.7):
    """At most max_hints ambiguous columns, each with 5 sample values."""
    hints = []
    names = list(db_meta["columns"])
    for ref in visible:
        if len(hints) >= max_hints:
            break
        info = db_meta["columns"].get(ref)
        if not info:
            continue
        best = None
        for other in names:
            if other == ref:
                continue
            oinfo = db_meta["columns"][other]
            if oinfo["type"] != info["type"]:
                continue
            ratio = difflib.SequenceMatcher(None, ref.split(".")[-1], other.split(".")[-1]).ratio()
            if ratio >= threshold and (best is None or ratio > best[0]):
                best = (ratio, other)
        if best is None:
            continue
        other = best[1]
        other_info = db_meta["columns"][other]
        values = sample_values(db_path, other_info["table"], other_info["column"])
        if values:
            hints.append(f"- {other}: {', '.join(v[:12] for v in values)}")
    return hints


def build_prompt(record, schema_text, hints):
    user = "SQLite schema:\n" + schema_text
    if hints:
        user += "\n\nValue hints (sample values help disambiguate similar columns):\n" + "\n".join(hints)
    user += "\n\nQuestion:\n" + record["question"]
    if record.get("evidence"):
        user += "\n\nEvidence:\n" + record["evidence"]
    user += "\n\nReturn one SQLite query."
    return [{"role": "system", "content": module.SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(MINIDEV / "model_eval/model_matrix.json"))
    parser.add_argument("--model-key", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--start-k", type=int, default=8)
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    args_in = parser.parse_args()

    config = {item["key"]: item for item in json.loads(Path(args_in.config).read_text())}[args_in.model_key]
    gen_args = argparse.Namespace(
        local_files_only=True, device=args_in.device, dtype="auto",
        max_new_tokens=args_in.max_new_tokens, temperature=0.0,
        api_base=None, api_key_env="DEEPSEEK_API_KEY", retries=4, seed=20261019,
    )
    generator = module.create_generator(config, gen_args)

    tokenizer = AutoTokenizer.from_pretrained(
        str(MINIDEV / "modules/Qwen3-0.6B"), local_files_only=True
    )

    def tokens(text):
        return len(tokenizer.encode(text))

    variants = {v["variant_id"]: v for v in read(FIXED / "variants/fixed_variants.jsonl")}
    plain = [v for v in variants.values() if v["variant_id"].endswith("__plain_fixed_130")]
    plain.sort(key=lambda v: v["question_index"])
    plain = plain[: args_in.limit]
    metadata = load_metadata()

    out_path = Path(args_in.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = {row["variant_id"] for row in read(out_path)} if out_path.exists() else set()

    with out_path.open("a", encoding="utf-8") as out:
        for record in plain:
            if record["variant_id"] in done:
                continue
            db_path = BASE / "mini_dev_data" / record["database_path"]
            db_meta = metadata[record["db_id"]]
            visible = [c.lower() for c in record["schema_columns"][: args_in.start_k]]
            rounds = 0
            added_tokens = 0
            blocked = 0
            history = []
            while True:
                hints = near_name_hints(db_meta, visible, db_path)
                schema_text = "\n".join(schema_lines(visible, db_meta))
                if hints:
                    schema_text += "\n\nValue hints:\n" + "\n".join(hints)
                messages = build_prompt(record, schema_text, [])
                raw = generator.generate(messages)
                sql = module.extract_sql(raw)
                status, denied = authorizer_check(db_path, sql, set(visible))
                blocked += len(denied)
                history.append({"round": rounds, "sql": sql, "status": status,
                                "denied": sorted(set(denied)), "visible": list(visible)})
                if status == "ok" or rounds >= args_in.max_rounds:
                    break
                missing = set(denied)
                if status == "error":
                    tables, cols = parse_refs(sql)
                    visible_tables = {v.split(".")[0] for v in visible}
                    missing |= {c for c in cols if c not in visible}
                    missing |= {t for t in tables if t not in visible_tables}
                extra = supplement(db_meta, sorted(missing), set(visible))
                if not extra:
                    break
                before = tokens("\n".join(schema_lines(visible, db_meta)))
                visible.extend(extra)
                after = tokens("\n".join(schema_lines(visible, db_meta)))
                added_tokens += max(0, after - before)
                rounds += 1
            row = {
                "variant_id": record["variant_id"], "question_id": record["question_id"],
                "db_id": record["db_id"], "model_key": args_in.model_key,
                "rounds": rounds, "added_tokens": added_tokens, "blocked": blocked,
                "visible_final": visible, "sql": sql, "raw": raw,
                "status_final": status, "history": history,
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{record['variant_id']} rounds={rounds} added={added_tokens} blocked={blocked} status={status}", flush=True)


if __name__ == "__main__":
    main()
