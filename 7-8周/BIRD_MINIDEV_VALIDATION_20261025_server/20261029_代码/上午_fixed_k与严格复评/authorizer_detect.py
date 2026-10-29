#!/usr/bin/env python3
"""Authorizer-based detection: run generated SQL against the read-only database
with an allowlist equal to the prompt schema and collect every read that falls
outside it. This is the authoritative 'missing object' signal for the method."""

import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote

BASE = Path("/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025")
RUN = BASE / "fixed_k_fk_20261029"
MODELS = ("qwen3_4b", "api_control", "qwen2_5_coder_1_5b")


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def run(db_path, sql, allowed_tables, allowed_columns, timeout=60.0):
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
        con.execute(sql).fetchmany(200001)
        return "ok", hits
    except sqlite3.Error as exc:
        return ("denied" if hits else "error"), hits
    finally:
        con.close()


def main():
    variants = {v["variant_id"]: v for v in read(RUN / "variants/fixed_variants.jsonl")}
    for model in MODELS:
        preds = [p for p in read(RUN / f"predictions/{model}.jsonl") if p["family"] == "plain_fixed_130"]
        status = Counter()
        outside = 0
        refs = Counter()
        for pred in preds:
            variant = variants[pred["variant_id"]]
            allowed = {c.lower() for c in variant["schema_columns"]}
            allowed_tables = {c.split(".")[0] for c in allowed}
            db = BASE / "mini_dev_data" / variant["database_path"]
            state, hits = run(db, pred["predicted_sql"], allowed_tables, allowed)
            status[state] += 1
            if state == "denied":
                outside += 1
                for ref in hits:
                    refs[ref] += 1
        print(json.dumps({"model": model, "n": len(preds), "status": dict(status),
                          "with_outside_reads": outside,
                          "rate": round(outside / len(preds), 4),
                          "top_refs": refs.most_common(8)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
