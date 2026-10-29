#!/usr/bin/env python3
"""Resolve physical table/column labels from native gold or result-matched SQL."""

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope


def read_jsonl(path):
    return [json.loads(s) for s in path.open(encoding="utf-8") if s.strip()]


def catalog(db_path):
    uri = f"file:{quote(str(db_path))}?mode=ro"
    with sqlite3.connect(uri, uri=True) as con:
        tables = {}
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            escaped = '"' + name.replace('"', '""') + '"'
            tables[name.lower()] = {
                "name": name,
                "columns": {row[1].lower(): {"name": row[1], "type": row[2]}
                            for row in con.execute(f"PRAGMA table_info({escaped})")},
            }
    return tables


def labels_for_sql(sql, tables):
    tree = sqlglot.parse_one(sql, read="sqlite")
    if tree is None:
        raise ValueError("Empty SQL AST")
    selected = set()
    physical_tables = set()
    unresolved = []
    ambiguous = []
    for scope in traverse_scope(tree):
        sources = {}
        for alias, node in scope.sources.items():
            if isinstance(node, exp.Table) and node.name.lower() in tables:
                physical = tables[node.name.lower()]["name"]
                sources[alias.lower()] = physical
                physical_tables.add(physical)

        def add(table_name, column_name):
            table = tables[table_name.lower()]
            column = table["columns"].get(column_name.lower())
            if column:
                selected.add(f"{table['name']}.{column['name']}")
                return True
            return False

        for column in scope.columns:
            if column.is_star:
                continue
            if column.table:
                physical = sources.get(column.table.lower())
                if physical and not add(physical, column.name):
                    unresolved.append(f"{column.table}.{column.name}")
            else:
                candidates = [table for table in sources.values()
                              if column.name.lower() in tables[table.lower()]["columns"]]
                if len(candidates) == 1:
                    add(candidates[0], column.name)
                elif len(candidates) > 1:
                    for table in candidates:
                        add(table, column.name)
                    ambiguous.append({"column": column.name, "tables": sorted(candidates)})
                # No physical candidate means a CTE/subquery output or SQL alias.

        # USING(...) identifiers are not always represented as exp.Column nodes.
        for join in scope.expression.args.get("joins", []):
            for identifier in join.args.get("using") or []:
                for physical in sources.values():
                    add(physical, identifier.name)

        if isinstance(scope.expression, exp.Select):
            for projection in scope.expression.expressions:
                star = projection if isinstance(projection, exp.Star) else None
                if isinstance(projection, exp.Column) and projection.is_star:
                    star = projection
                if star is None:
                    continue
                target = sources.get(star.table.lower()) if getattr(star, "table", None) else None
                for physical in ([target] if target else sources.values()):
                    if physical:
                        for item in tables[physical.lower()]["columns"].values():
                            selected.add(f"{physical}.{item['name']}")

    if not physical_tables or not selected:
        raise ValueError("No physical table/column labels resolved")
    return {"tables": sorted(physical_tables), "columns": sorted(selected),
            "unresolved_physical_refs": sorted(set(unresolved)),
            "ambiguous_refs": ambiguous}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--database-root", type=Path, required=True)
    p.add_argument("--silver-attempts", type=Path, required=True)
    p.add_argument("--gold-audit", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    files = args.data_root / "files"
    tasks = {x["instance_id"]: x for x in read_jsonl(files / "tasks/spider2-lite.jsonl")
             if x["instance_id"].startswith("local")}
    gold_audit = {x["instance_id"]: x for x in json.loads(args.gold_audit.read_text())["rows"]}
    silver_by_id = defaultdict(list)
    if args.silver_attempts.exists():
        for x in read_jsonl(args.silver_attempts):
            silver_by_id[x["instance_id"]].append(x)
    db_catalog = {}
    rows = []
    for qid, task in sorted(tasks.items()):
        db = task["db"]
        if db not in db_catalog:
            db_catalog[db] = catalog(args.database_root / f"{db}.sqlite")
        gold_path = files / "gold/sql/lite" / f"{qid}.sql"
        if gold_path.is_file():
            source = "gold_sql"
            sql = gold_path.read_text(encoding="utf-8")
            gold_match = gold_audit[qid]["official_match"]
            attempt = None
        else:
            matches = sorted((x for x in silver_by_id[qid] if x["score"] and x["sql"]),
                             key=lambda x: x["attempt"])
            if not matches:
                rows.append({"instance_id": qid, "db": db, "eligible": False,
                             "reason": "no_result_matched_silver", "attempts_recorded": len(silver_by_id[qid])})
                continue
            source = "silver_result_match"
            sql = matches[0]["sql"]
            gold_match = None
            attempt = matches[0]["attempt"]
        try:
            labels = labels_for_sql(sql, db_catalog[db])
            rows.append({"instance_id": qid, "db": db, "eligible": True,
                         "label_source": source, "gold_sql_official_match": gold_match,
                         "silver_attempt": attempt, "sql": sql, **labels})
        except Exception as exc:
            rows.append({"instance_id": qid, "db": db, "eligible": False,
                         "label_source": source, "reason": f"{type(exc).__name__}: {exc}"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    summary = {"questions": len(rows),
               "eligible": sum(x["eligible"] for x in rows),
               "native_gold": sum(x.get("label_source") == "gold_sql" and x["eligible"] for x in rows),
               "native_gold_official_match": sum(x.get("gold_sql_official_match") is True and x["eligible"] for x in rows),
               "silver": sum(x.get("label_source") == "silver_result_match" and x["eligible"] for x in rows)}
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
