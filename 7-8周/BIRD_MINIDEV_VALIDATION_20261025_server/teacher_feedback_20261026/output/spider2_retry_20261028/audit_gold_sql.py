#!/usr/bin/env python3
"""Audit the 24 native Spider2-Lite SQLite gold SQLs against official results."""

import argparse
import io
import json
import sys
import types
from pathlib import Path

import pandas as pd
import sqlglot


def read_jsonl(path):
    return {row["instance_id"]: row for line in path.open(encoding="utf-8")
            if (row := json.loads(line))["instance_id"].startswith("local")}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--database-root", type=Path, required=True)
    p.add_argument("--evaluator-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    sys.path.insert(0, str(args.evaluator_root))
    # The official module imports the BigQuery client unconditionally. This
    # SQLite-only audit never calls its BigQuery path.
    try:
        from google.cloud import bigquery  # noqa: F401
    except ImportError:
        import google.cloud
        google.cloud.bigquery = types.ModuleType("google.cloud.bigquery")
        sys.modules["google.cloud.bigquery"] = google.cloud.bigquery
    from evaluate import (compare_multi_pandas_table, compare_pandas_table,
                          get_sqlite_result, resolve_gold_paths)

    files = args.data_root / "files"
    tasks = read_jsonl(files / "tasks/spider2-lite.jsonl")
    standards = read_jsonl(files / "tasks/spider2lite_eval.jsonl")
    sql_dir = files / "gold/sql/lite"
    gold_dir = files / "gold/exec_result/lite"
    rows = []
    for sql_file in sorted(sql_dir.glob("local*.sql")):
        qid = sql_file.stem
        task = tasks[qid]
        standard = standards[qid]
        sql = sql_file.read_text(encoding="utf-8")
        row = {"instance_id": qid, "db": task["db"], "parse_ok": False,
               "execute_ok": False, "official_match": False, "error": None}
        try:
            expr = sqlglot.parse_one(sql, read="sqlite")
            if expr is None:
                raise ValueError("sqlglot returned empty AST")
            row["parse_ok"] = True
            db = args.database_root / f"{task['db']}.sqlite"
            ok, result = get_sqlite_result(str(db), sql, instance_id=qid)
            if not ok:
                raise RuntimeError(str(result))
            row["execute_ok"] = True
            paths, single = resolve_gold_paths(qid, str(gold_dir))
            if not paths:
                raise FileNotFoundError(f"No official gold result for {qid}")
            result = pd.read_csv(io.StringIO(result.to_csv(index=False)))
            condition = standard.get("condition_cols")
            ignore_order = standard.get("ignore_order", False)
            if single:
                match = compare_pandas_table(result, pd.read_csv(paths[0]), condition, ignore_order)
            else:
                match = compare_multi_pandas_table(result, [pd.read_csv(x) for x in paths], condition, ignore_order)
            row["official_match"] = bool(match)
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "source": "Spider2-Lite native gold SQL only",
        "total": len(rows),
        "parse_ok": sum(x["parse_ok"] for x in rows),
        "execute_ok": sum(x["execute_ok"] for x in rows),
        "official_match": sum(x["official_match"] for x in rows),
        "rows": rows,
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: sum(x[k] for x in rows)
                      for k in ("parse_ok", "execute_ok", "official_match")}))


if __name__ == "__main__":
    main()
