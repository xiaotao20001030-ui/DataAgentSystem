#!/usr/bin/env python3
"""Build paired Spider SQLite base/random20/physical-synonym20 variants."""

import argparse
import hashlib
import json
import random
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from extract_labels import catalog, read_jsonl
from generate_silver import execute_readonly, official_functions, score_result


WORD_SYNONYMS = {
    "id": ("key", "identifier"), "name": ("label", "title"),
    "date": ("day", "timestamp"), "time": ("timestamp", "moment"),
    "year": ("yr", "calendar_year"), "month": ("calendar_month", "period"),
    "amount": ("total", "value"), "price": ("cost", "unit_price"),
    "cost": ("expense", "price"), "total": ("sum", "aggregate"),
    "count": ("quantity", "number"), "number": ("count", "num"),
    "customer": ("client", "buyer"), "user": ("account", "person"),
    "order": ("purchase", "transaction"), "product": ("item", "merchandise"),
    "sales": ("revenue", "turnover"), "revenue": ("sales", "income"),
    "status": ("state", "condition"), "type": ("category", "kind"),
    "category": ("class", "group"), "description": ("details", "summary"),
    "city": ("municipality", "town"), "country": ("nation", "region"),
    "first": ("given", "initial"), "last": ("family", "final"),
    "start": ("begin", "initial"), "end": ("finish", "final"),
    "score": ("rating", "points"), "rate": ("ratio", "percentage"),
    "quantity": ("count", "volume"), "address": ("location", "place"),
    "employee": ("staff", "worker"), "player": ("participant", "athlete"),
    "team": ("squad", "group"), "match": ("game", "contest"),
}


def qid(name):
    return '"' + name.replace('"', '""') + '"'


def affinity(declared):
    t = (declared or "").upper()
    if "INT" in t:
        return "INTEGER"
    if any(s in t for s in ("CHAR", "CLOB", "TEXT")):
        return "TEXT"
    if "BLOB" in t or not t:
        return "BLOB"
    if any(s in t for s in ("REAL", "FLOA", "DOUB")):
        return "REAL"
    return "NUMERIC"


def near_names(base):
    tokens = [s for s in re.split(r"[_\s]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", base)) if s]
    names = []
    for i, token in enumerate(tokens):
        for alt in WORD_SYNONYMS.get(token.lower(), ()):
            names.append("_".join(tokens[:i] + [alt] + tokens[i + 1:]))
    names.extend((f"alt_{base}", f"equivalent_{base}", f"related_{base}"))
    return names


def render_schema(columns, tables, required_tables=()):
    lines = []
    represented = {key.split(".", 1)[0].casefold() for key in columns}
    for table_name in sorted(required_tables, key=str.casefold):
        if table_name.casefold() not in represented:
            lines.append(f"table {table_name};")
    for key in sorted(columns, key=str.casefold):
        table_name, column_name = key.split(".", 1)
        entry = tables[table_name.lower()]["columns"][column_name.lower()]
        lines.append(f"table {table_name}; column {column_name}; type {entry['type'] or 'ANY'};")
    return "\n".join(lines)


def unique_new_name(target_name, taken, position):
    for candidate in near_names(target_name):
        if candidate.casefold() not in taken:
            taken.add(candidate.casefold())
            return candidate
    base = near_names(target_name)[0]
    n = position + 1
    while f"{base}_{n}".casefold() in taken:
        n += 1
    candidate = f"{base}_{n}"
    taken.add(candidate.casefold())
    return candidate


def plan_near_columns(gold_columns, tables, seed):
    targets = sorted(gold_columns, key=str.casefold)
    rng = random.Random(seed)
    rng.shuffle(targets)
    taken = {t: set(x["columns"]) for t, x in tables.items()}
    gold = set(gold_columns)
    planned = []
    for i in range(20):
        target = targets[i % len(targets)]
        table, column = target.split(".", 1)
        key = table.lower()
        target_info = tables[key]["columns"][column.lower()]
        donor_options = [info["name"] for info in tables[key]["columns"].values()
                         if f"{table}.{info['name']}" not in gold
                         and affinity(info["type"]) == affinity(target_info["type"])]
        if donor_options:
            donor_table = table
            donor = sorted(donor_options, key=str.casefold)[rng.randrange(len(donor_options))]
        else:
            alternatives = sorted((t["name"], info["name"])
                for t in tables.values() for info in t["columns"].values()
                if f"{t['name']}.{info['name']}" not in gold
                and affinity(info["type"]) == affinity(target_info["type"]))
            if not alternatives:
                raise ValueError(f"No non-gold same-type donor in database for {target}")
            donor_table, donor = alternatives[rng.randrange(len(alternatives))]
        name = unique_new_name(column, taken[key], i)
        planned.append({"table": table, "name": name,
                        "type": target_info["type"] or "BLOB",
                        "target": target, "donor": f"{donor_table}.{donor}"})
    return planned


def clone_and_add(source, destination, planned):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        by_table = defaultdict(list)
        temp_tables = {}
        for item in planned:
            table = item["table"]
            dst.execute(f"ALTER TABLE {qid(table)} ADD COLUMN {qid(item['name'])} {item['type']}")
            by_table[table].append(item)
            donor_table, donor_column = item["donor"].split(".", 1)
            if donor_table != table:
                sample = [row[0] for row in dst.execute(
                    f"SELECT {qid(donor_column)} FROM {qid(donor_table)} "
                    f"WHERE {qid(donor_column)} IS NOT NULL LIMIT 256")]
                if not sample:
                    raise ValueError(f"Cross-table donor has no values: {item['donor']}")
                temp_name = f"_syn_donor_{len(temp_tables)}"
                dst.execute(f"CREATE TEMP TABLE {qid(temp_name)} (_i INTEGER PRIMARY KEY, _value)")
                dst.executemany(f"INSERT INTO {qid(temp_name)} VALUES (?,?)",
                                [(j + 1, value) for j, value in enumerate(sample)])
                temp_tables[(table, item["name"])] = (temp_name, len(sample))
        for table, items in by_table.items():
            # SQLite rowid lets us cycle actual donor values without assuming
            # the two tables have equal row counts.
            if any((table, x["name"]) in temp_tables for x in items):
                dst.execute(f"SELECT rowid FROM {qid(table)} LIMIT 1")
            assignments = []
            for item in items:
                cross = temp_tables.get((table, item["name"]))
                if cross:
                    name, count = cross
                    value = (f"(SELECT _value FROM {qid(name)} "
                             f"WHERE _i = (abs({qid(table)}.rowid) % {count}) + 1)")
                else:
                    value = qid(item["donor"].split(".", 1)[1])
                assignments.append(f"{qid(item['name'])} = {value}")
            assignments = ", ".join(assignments)
            dst.execute(f"UPDATE {qid(table)} SET {assignments}")
        dst.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--database-root", type=Path, required=True)
    p.add_argument("--evaluator-root", type=Path, required=True)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--seed", type=int, default=20261028)
    p.add_argument("--limit", type=int)
    args = p.parse_args()
    files = args.data_root / "files"
    tasks = {x["instance_id"]: x for x in read_jsonl(files / "tasks/spider2-lite.jsonl")}
    standards = {x["instance_id"]: x for x in read_jsonl(files / "tasks/spider2lite_eval.jsonl")}
    scorer = official_functions(args.evaluator_root)
    gold_dir = files / "gold/exec_result/lite"
    labels = [x for x in read_jsonl(args.labels) if x.get("eligible")
              and (x["label_source"] != "gold_sql" or x["gold_sql_official_match"])]
    if args.limit is not None:
        labels = labels[:args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "variants.jsonl"
    exclusions = args.output_dir / "exclusions.jsonl"
    completed = {x["instance_id"] for x in read_jsonl(output) if x["condition"] == "synonym20"} if output.exists() else set()
    with output.open("a", encoding="utf-8") as out, exclusions.open("a", encoding="utf-8") as errors:
        for label in labels:
            q = label["instance_id"]
            if q in completed:
                continue
            db = label["db"]
            source = args.database_root / f"{db}.sqlite"
            clone = args.output_dir / "databases" / f"{q}.sqlite"
            try:
                tables = catalog(source)
                selected = set(label["columns"])
                all_columns = {f"{t['name']}.{c['name']}" for t in tables.values()
                               for c in t["columns"].values()}
                rng = random.Random(f"{args.seed}:{q}:random20")
                pool = sorted(all_columns - selected, key=str.casefold)
                if len(pool) < 20:
                    raise ValueError("Fewer than 20 random distractor columns")
                random_columns = rng.sample(pool, 20)
                planned = plan_near_columns(selected, tables, f"{args.seed}:{q}:synonym20")
                clone_and_add(source, clone, planned)
                clone_tables = catalog(clone)
                new_columns = {f"{x['table']}.{x['name']}" for x in planned}
                if not new_columns.issubset({f"{t['name']}.{c['name']}" for t in clone_tables.values()
                                            for c in t['columns'].values()}):
                    raise AssertionError("New columns absent from SQLite clone")
                for location in (source, clone):
                    frame = execute_readonly(location, label["sql"])
                    if not score_result(q, frame, standards, gold_dir, scorer):
                        raise ValueError(f"Label SQL does not match official result on {location.name}")
                for condition, cols, path, additions, schema_catalog in (
                    ("base", selected, source, [], tables),
                    ("random20", selected | set(random_columns), source, random_columns, tables),
                    ("synonym20", selected | new_columns, clone, sorted(new_columns), clone_tables),
                ):
                    record = {"instance_id": q, "db": db, "condition": condition,
                              "variant_id": f"{q}__{condition}", "label_source": label["label_source"],
                              "question": tasks[q]["question"],
                              "external_knowledge": tasks[q].get("external_knowledge"),
                              "schema_columns": sorted(cols),
                              "schema_text": render_schema(cols, schema_catalog, label["tables"]),
                              "database_path": str(path), "added_columns": additions,
                              "near_column_provenance": planned if condition == "synonym20" else []}
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out.flush()
                print(f"{q} variants=3", flush=True)
            except Exception as exc:
                if clone.exists():
                    clone.unlink()
                errors.write(json.dumps({"instance_id": q, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
                errors.flush()
                print(f"{q} excluded={type(exc).__name__}", flush=True)


if __name__ == "__main__":
    main()
