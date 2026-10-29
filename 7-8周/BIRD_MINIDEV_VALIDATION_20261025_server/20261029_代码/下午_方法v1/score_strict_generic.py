#!/usr/bin/env python3
"""Strict authorizer scoring for arbitrary prediction files."""

import argparse
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

MAX_ROWS = 200000
PERMISSIVE = False


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def normalize(value):
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, bytes):
        return "hex:" + value.hex()
    return value


def run(db_path, sql, allowed, timeout):
    hits = []
    allowed_tables = {c.split(".")[0] for c in allowed}
    allowed_cols = {c.lower() for c in allowed}
    started = time.perf_counter()
    deadline = started + timeout
    con = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)

    def authorizer(action, arg1, arg2, dbname, trigger):
        if action == sqlite3.SQLITE_READ:
            table = (arg1 or "").lower()
            column = (arg2 or "").lower()
            if table not in allowed_tables or (column and f"{table}.{column}" not in allowed_cols):
                hits.append(f"{table}.{column}" if column else table)
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    if not PERMISSIVE:
        con.set_authorizer(authorizer)
    con.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 20000)
    try:
        con.execute("PRAGMA query_only = ON")
        rows = con.execute(sql).fetchmany(MAX_ROWS + 1)
        if len(rows) > MAX_ROWS:
            raise RuntimeError("too many rows")
        return "ok", rows, hits
    except sqlite3.Error as exc:
        return ("denied" if hits else "error"), None, hits
    finally:
        con.close()


def permissive(db_path, sql, timeout):
    con = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
    started = time.perf_counter()
    deadline = started + timeout
    con.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 20000)
    try:
        con.execute("PRAGMA query_only = ON")
        return con.execute(sql).fetchmany(MAX_ROWS + 1)
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--data-root", default="/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025/mini_dev_data")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--families", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--permissive", action="store_true")
    args = parser.parse_args()

    families = {f.strip() for f in args.families.split(",") if f.strip()}
    variants = {v["variant_id"]: v for v in read(args.variants)
                if not families or v.get("perturbation", {}).get("family") in families}
    preds = [p for p in read(args.predictions) if p["variant_id"] in variants]
    if args.limit:
        preds = preds[: args.limit]
    data_root = Path(args.data_root)
    out = []
    for pred in preds:
        variant = variants.get(pred["variant_id"])
        if variant is None:
            continue
        sql = pred.get("predicted_sql") or pred.get("sql") or ""
        db_path = data_root / variant["database_path"]
        record = {"variant_id": pred["variant_id"], "question_id": variant["question_id"]}
        if not sql.strip():
            record.update(status="prediction_error", strict_correct=False)
            out.append(record)
            continue
        try:
            gold_rows = permissive(db_path, variant["gold_sql"], args.timeout)
        except Exception:
            record.update(status="gold_unscoreable", strict_correct=False)
            out.append(record)
            continue
        status, rows, hits = run(db_path, sql, {c.lower() for c in variant["schema_columns"]}, args.timeout)
        record["denied"] = len(hits)
        if status != "ok":
            record.update(status=status, strict_correct=False)
        else:
            strict = [tuple(normalize(v) for v in r) for r in rows]
            gold = [tuple(normalize(v) for v in r) for r in gold_rows]
            record.update(status="ok", strict_correct=set(strict) == set(gold))
        out.append(record)
        if len(out) % 50 == 0:
            print(f"[{len(out)}/{len(preds)}] correct={sum(r['strict_correct'] for r in out)}", flush=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    print(args.output, "rows", len(out), "correct", sum(r["strict_correct"] for r in out))


if __name__ == "__main__":
    main()
