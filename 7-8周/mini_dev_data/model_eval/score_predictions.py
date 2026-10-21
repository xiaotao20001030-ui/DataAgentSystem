#!/usr/bin/env python3
"""Execute generated SQL and score exact result accuracy."""

import argparse
import hashlib
import json
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote


MAX_RESULT_ROWS = 200000


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument(
        "--variants",
        type=Path,
        default=project_root / "perturbations" / "output"
        / "mini_dev_perturbations.jsonl",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=project_root / "mini_dev_data",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "model_eval" / "scores",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-rows", type=int, default=MAX_RESULT_ROWS)
    return parser.parse_args()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalize_value(value):
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, bytes):
        return "hex:" + value.hex()
    return value


def normalize_rows(rows):
    return [tuple(normalize_value(value) for value in row) for row in rows]


def order_sensitive(sql):
    return bool(re.search(r"\border\s+by\b", sql, flags=re.IGNORECASE))


def results_equal(predicted_rows, gold_rows, gold_sql):
    predicted = normalize_rows(predicted_rows)
    gold = normalize_rows(gold_rows)
    if order_sensitive(gold_sql):
        return predicted == gold
    return Counter(predicted) == Counter(gold)


def execute_query(db_path, sql, timeout_seconds, max_rows):
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, flags=re.IGNORECASE):
        raise ValueError("Only SELECT or WITH queries are allowed")
    started = time.perf_counter()
    deadline = started + timeout_seconds
    connection = sqlite3.connect(
        f"file:{quote(str(db_path))}?mode=ro",
        uri=True,
    )
    connection.set_progress_handler(
        lambda: 1 if time.perf_counter() > deadline else 0,
        20000,
    )
    try:
        connection.execute("PRAGMA query_only = ON")
        cursor = connection.execute(sql)
        columns = [item[0] for item in cursor.description or []]
        rows = cursor.fetchmany(max_rows + 1)
        if len(rows) > max_rows:
            raise RuntimeError(f"Result exceeds max rows: {max_rows}")
        return {
            "columns": columns,
            "rows": rows,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    finally:
        connection.close()


def main():
    args = parse_args()
    variant_records = read_jsonl(args.variants)
    variant_by_id = {record["variant_id"]: record for record in variant_records}
    predictions = read_jsonl(args.predictions)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    scored = []
    for prediction in predictions:
        variant = variant_by_id[prediction["variant_id"]]
        db_path = args.data_root / variant["database_path"]
        gold_sql = variant["gold_sql"]
        predicted_sql = prediction.get("predicted_sql", "")
        error = prediction.get("error")
        correct = False
        predicted_meta = None
        gold_meta = None

        if not error and predicted_sql:
            try:
                predicted_meta = execute_query(
                    db_path,
                    predicted_sql,
                    args.timeout_seconds,
                    args.max_rows,
                )
                gold_meta = execute_query(
                    db_path,
                    gold_sql,
                    args.timeout_seconds,
                    args.max_rows,
                )
                correct = results_equal(
                    predicted_meta["rows"],
                    gold_meta["rows"],
                    gold_sql,
                )
            except Exception as exception:
                error = f"{type(exception).__name__}: {exception}"

        scored.append(
            {
                "variant_id": prediction["variant_id"],
                "question_id": prediction["question_id"],
                "db_id": prediction["db_id"],
                "family": prediction["family"],
                "model_key": prediction["model_key"],
                "model": prediction["model"],
                "correct": correct,
                "error": error,
                "predicted_sql": predicted_sql,
                "gold_sql": gold_sql,
                "predicted_columns": (
                    predicted_meta["columns"] if predicted_meta else None
                ),
                "predicted_row_count": (
                    len(predicted_meta["rows"]) if predicted_meta else None
                ),
                "predicted_elapsed_ms": (
                    predicted_meta["elapsed_ms"] if predicted_meta else None
                ),
                "gold_columns": gold_meta["columns"] if gold_meta else None,
                "gold_row_count": len(gold_meta["rows"]) if gold_meta else None,
            }
        )

    model_key = predictions[0]["model_key"] if predictions else "unknown"
    output_path = args.output_dir / f"{model_key}.jsonl"
    with output_path.open("w", encoding="utf-8") as output:
        for record in scored:
            output.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            )
            output.write("\n")

    by_family = {}
    for family in sorted({record["family"] for record in scored}):
        family_records = [record for record in scored if record["family"] == family]
        by_family[family] = {
            "count": len(family_records),
            "correct": sum(record["correct"] for record in family_records),
            "accuracy": (
                sum(record["correct"] for record in family_records)
                / len(family_records)
            ),
        }
    summary = {
        "model_key": model_key,
        "prediction_file": str(args.predictions),
        "prediction_sha256": hashlib.sha256(args.predictions.read_bytes()).hexdigest(),
        "by_family": by_family,
    }
    summary_path = args.output_dir / f"{model_key}.summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
