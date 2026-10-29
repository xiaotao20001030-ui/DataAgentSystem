#!/usr/bin/env python3
"""Generate three full-schema DeepSeek SQL candidates and verify official results.

The API key is read only from DEEPSEEK_API_KEY. No request headers or key are
written to logs. Rows are appended after every attempt so the job can resume.
"""

import argparse
import io
import json
import os
import re
import sqlite3
import sys
import time
import types
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import sqlglot
from sqlglot import exp


def read_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def official_functions(evaluator_root):
    sys.path.insert(0, str(evaluator_root))
    try:
        from google.cloud import bigquery  # noqa: F401
    except ImportError:
        import google.cloud
        google.cloud.bigquery = types.ModuleType("google.cloud.bigquery")
        sys.modules["google.cloud.bigquery"] = google.cloud.bigquery
    from evaluate import compare_multi_pandas_table, compare_pandas_table, resolve_gold_paths
    return compare_multi_pandas_table, compare_pandas_table, resolve_gold_paths


def full_schema(db_path):
    with sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True) as con:
        lines = [row[0] for row in con.execute(
            "SELECT sql FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY name")]
    return ";\n".join(lines) + ";"


def extract_sql(reply):
    blocks = re.findall(r"```(?:sql|sqlite)?\s*(.*?)```", reply, re.I | re.S)
    sql = blocks[0].strip() if blocks else reply.strip()
    sql = re.sub(r"^\s*(?:SQL\s*:\s*)", "", sql, flags=re.I)
    return sql.rstrip(";\n ") + ";"


def safe_select(sql):
    expressions = sqlglot.parse(sql, read="sqlite")
    if len(expressions) != 1 or expressions[0] is None:
        raise ValueError("Expected one SQL statement")
    tree = expressions[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Except, exp.Intersect)):
        raise ValueError(f"Only SELECT queries are allowed: {type(tree).__name__}")
    if any(tree.find(kind) for kind in (exp.Insert, exp.Update, exp.Delete,
                                         exp.Create, exp.Drop, exp.Alter)):
        raise ValueError("Mutating SQL is not allowed")
    return tree


def call_api(api_base, model, messages, temperature):
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is absent")
    payload = json.dumps({"model": model, "messages": messages,
                          "temperature": temperature, "max_tokens": 1200}).encode()
    req = urllib.request.Request(api_base.rstrip("/") + "/chat/completions",
        data=payload, headers={"Content-Type": "application/json",
                               "Authorization": "Bearer " + key}, method="POST")
    last = None
    for n in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                data = json.load(response)
            return data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError) as exc:
            last = type(exc).__name__
            time.sleep(min(2 ** n, 10))
    raise RuntimeError("API request failed after 4 attempts: " + str(last))


def execute_readonly(db_path, sql, timeout=60, max_rows=100000):
    uri = f"file:{quote(str(db_path))}?mode=ro"
    with sqlite3.connect(uri, uri=True) as con:
        deadline = time.monotonic() + timeout
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        cursor = con.execute(sql)
        columns = [item[0] for item in cursor.description]
        rows = []
        while True:
            part = cursor.fetchmany(2000)
            if not part:
                break
            rows.extend(part)
            if len(rows) > max_rows:
                raise RuntimeError("SQL returned over 100000 rows")
        df = pd.DataFrame(rows, columns=columns)
    return pd.read_csv(io.StringIO(df.to_csv(index=False)))


def score_result(qid, frame, standards, gold_dir, functions):
    compare_multi, compare_one, resolve_paths = functions
    paths, is_single = resolve_paths(qid, str(gold_dir))
    if not paths:
        raise FileNotFoundError("Official gold result is absent")
    standard = standards[qid]
    cols = standard.get("condition_cols")
    order = standard.get("ignore_order", False)
    if is_single:
        return bool(compare_one(frame, pd.read_csv(paths[0]), cols, order))
    return bool(compare_multi(frame, [pd.read_csv(p) for p in paths], cols, order))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--database-root", type=Path, required=True)
    p.add_argument("--evaluator-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", default="deepseek-chat")
    p.add_argument("--api-base", default="https://api.deepseek.com/v1")
    p.add_argument("--temperature", type=float, default=0.4)
    p.add_argument("--limit", type=int)
    args = p.parse_args()
    files = args.data_root / "files"
    tasks = [t for t in read_jsonl(files / "tasks/spider2-lite.jsonl")
             if t["instance_id"].startswith("local")]
    gold_ids = {f.stem for f in (files / "gold/sql/lite").glob("*.sql")}
    tasks = [t for t in tasks if t["instance_id"] not in gold_ids]
    if args.limit is not None:
        tasks = tasks[:args.limit]
    standards = {x["instance_id"]: x for x in read_jsonl(files / "tasks/spider2lite_eval.jsonl")}
    functions = official_functions(args.evaluator_root)
    gold_dir = files / "gold/exec_result/lite"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = {(x["instance_id"], x["attempt"]) for x in read_jsonl(args.output)} if args.output.exists() else set()
    with args.output.open("a", encoding="utf-8") as output:
        for task in tasks:
            qid, db = task["instance_id"], task["db"]
            db_path = args.database_root / f"{db}.sqlite"
            schema = full_schema(db_path)
            knowledge = ""
            if task.get("external_knowledge"):
                doc = files / "documents" / task["external_knowledge"]
                if doc.is_file():
                    knowledge = doc.read_text(encoding="utf-8")
            for attempt in range(1, 4):
                if (qid, attempt) in done:
                    continue
                row = {"instance_id": qid, "db": db, "attempt": attempt,
                       "label_type": "silver_result_match", "score": False,
                       "sql": None, "error": None,
                       "external_knowledge_present": bool(knowledge)}
                try:
                    prompt = (f"SQLite schema:\n{schema}\n\nQuestion:\n{task['question']}\n"
                              + (f"\nExternal knowledge:\n{knowledge}\n" if knowledge else "")
                              + f"\nProduce a correct SQL query. Candidate {attempt} of 3. "
                                "Return only one SQLite SELECT query, with no explanation.")
                    reply = call_api(args.api_base, args.model, [
                        {"role": "system", "content": "You write SQLite SQL to answer database questions."},
                        {"role": "user", "content": prompt}], args.temperature)
                    sql = extract_sql(reply)
                    safe_select(sql)
                    row["sql"] = sql
                    frame = execute_readonly(db_path, sql)
                    row["score"] = score_result(qid, frame, standards, gold_dir, functions)
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
                print(f"{qid} attempt={attempt} score={int(row['score'])}", flush=True)


if __name__ == "__main__":
    main()
