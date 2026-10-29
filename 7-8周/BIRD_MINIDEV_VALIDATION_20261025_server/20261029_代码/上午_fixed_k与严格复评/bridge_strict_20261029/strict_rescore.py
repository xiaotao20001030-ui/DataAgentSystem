#!/usr/bin/env python3
"""Rescore stored predictions under a strict access constraint.

Each hidden-schema variant records the tables/columns removed from the prompt
(perturbation.removed). We re-execute the *stored* prediction against the
unmodified read-only SQLite database with an authorizer that denies READ on
those hidden objects. A denied read is a strict violation and counts as an
incorrect answer. The same prediction is also executed without the authorizer,
so the report can separate "would have matched if the access constraint were
not enforced" from "strictly correct".

No model inference happens here; no database is modified.
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote

MODELS = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b", "api_control")
MAX_ROWS = 200000


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_value(value):
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, bytes):
        return "hex:" + value.hex()
    return value


def normalize_rows(rows):
    return [tuple(normalize_value(value) for value in row) for row in rows]


def results_equal(predicted_rows, gold_rows):
    return set(normalize_rows(predicted_rows)) == set(normalize_rows(gold_rows))


class QueryError(Exception):
    pass


class Denied(QueryError):
    pass


def execute(db_path, sql, timeout_seconds, allowed_tables=None, allowed_columns=None):
    """Return rows, or raise Denied if the authorizer blocked a read.

    When allowed_tables is given, only READs on that visible schema are
    permitted; every other table or column access raises Denied.
    """
    if not re.match(r"^\s*(SELECT|WITH)\b", sql or "", flags=re.IGNORECASE):
        raise QueryError("Only SELECT or WITH queries are allowed")
    strict = allowed_tables is not None
    allowed_tables = {t.lower() for t in allowed_tables or ()}
    allowed_columns = {c.lower() for c in allowed_columns or ()}
    hits = []
    started = time.perf_counter()
    deadline = started + timeout_seconds
    connection = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)

    def authorizer(action, arg1, arg2, dbname, trigger):
        if action == sqlite3.SQLITE_READ and strict:
            table = (arg1 or "").lower()
            column = (arg2 or "").lower()
            if table not in allowed_tables or (column and f"{table}.{column}" not in allowed_columns):
                hits.append(f"{arg1}.{arg2}")
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    if strict:
        connection.set_authorizer(authorizer)
    connection.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 20000)
    try:
        connection.execute("PRAGMA query_only = ON")
        cursor = connection.execute(sql)
        rows = cursor.fetchmany(MAX_ROWS + 1)
        if len(rows) > MAX_ROWS:
            raise QueryError(f"Result exceeds max rows: {MAX_ROWS}")
        return rows
    except sqlite3.Error as exc:
        if hits:
            raise Denied(";".join(sorted(set(hits)))) from exc
        raise QueryError(str(exc)) from exc
    finally:
        connection.close()


def visible_spec(variant):
    """Objects the model was actually shown in the prompt schema.

    Strict access constraint: any READ outside this set is a violation, which
    covers both the explicitly removed bridge table / FK column and every other
    table or column that the prompt never exposed.
    """
    columns = {c.lower() for c in variant.get("schema_columns") or []}
    tables = {c.split(".", 1)[0] for c in columns}
    return tables, columns


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", type=Path, required=True)
    parser.add_argument("--predictions-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--families", default="missing_bridge_table")
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    families = {f.strip() for f in args.families.split(",") if f.strip()}
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    variants = [
        v for v in read_jsonl(args.variants)
        if v.get("perturbation", {}).get("family") in families
    ]
    if args.limit:
        variants = variants[: args.limit]
    by_id = {v["variant_id"]: v for v in variants}
    print(f"variants={len(variants)} families={sorted(families)}", flush=True)

    gold_ok = {}
    for variant in variants:
        db_path = args.data_root / variant["database_path"]
        try:
            rows = execute(db_path, variant["gold_sql"], args.timeout_seconds)
            gold_ok[variant["variant_id"]] = normalize_rows(rows)
        except Exception as exc:  # noqa: BLE001 - gold failures are excluded
            gold_ok[variant["variant_id"]] = None
            print(f"GOLD_FAIL {variant['variant_id']} {exc}", flush=True)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for model in models:
        rows = read_jsonl(args.predictions_dir / f"{model}.jsonl")
        rows = [r for r in rows if r["variant_id"] in by_id]
        out = []
        for row in rows:
            variant = by_id[row["variant_id"]]
            record = {
                "variant_id": row["variant_id"],
                "model": model,
                "family": variant["perturbation"]["family"],
            }
            gold = gold_ok[row["variant_id"]]
            sql = row.get("predicted_sql") or ""
            if row.get("error") or not sql.strip():
                record.update(status="prediction_error", strict_correct=False, permissive_correct=False)
                out.append(record)
                continue
            if gold is None:
                record.update(status="gold_unscoreable", strict_correct=False, permissive_correct=False)
                out.append(record)
                continue
            db_path = args.data_root / variant["database_path"]
            tables, columns = visible_spec(variant)
            try:
                permissive = execute(db_path, sql, args.timeout_seconds)
                permissive_ok = results_equal(permissive, gold)
            except QueryError as exc:
                permissive_ok = False
                record["permissive_error"] = str(exc)[:300]
            record["permissive_correct"] = permissive_ok
            try:
                strict = execute(db_path, sql, args.timeout_seconds, tables, columns)
                strict_ok = results_equal(strict, gold)
                record["status"] = "strict_correct" if strict_ok else "wrong_result"
            except Denied as exc:
                strict_ok = False
                record["status"] = "denied_hidden_access"
                record["denied_refs"] = str(exc)[:500]
            except QueryError as exc:
                strict_ok = False
                record["status"] = "execution_error"
                record["error"] = str(exc)[:300]
            record["strict_correct"] = strict_ok
            out.append(record)
        path = args.output_dir / f"strict_{model}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
        counts = Counter(r["status"] for r in out)
        n = sum(1 for r in out if r["status"] not in ("gold_unscoreable",))
        sc = sum(1 for r in out if r["strict_correct"])
        pc = sum(1 for r in out if r["permissive_correct"])
        print(f"{model} n={n} strict={sc} ({sc / n:.2%}) permissive={pc} ({pc / n:.2%}) {dict(counts)}", flush=True)


if __name__ == "__main__":
    main()
