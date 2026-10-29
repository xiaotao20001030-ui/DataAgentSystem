#!/usr/bin/env python3
"""Resumable SQLite execution scorer with gold-result caching."""

import argparse
import json
import sqlite3
import time
from collections import Counter
from functools import lru_cache
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
        default=project_root / "model_eval" / "scores_fixed",
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-rows", type=int, default=MAX_RESULT_ROWS)
    parser.add_argument("--progress-every", type=int, default=10)
    return parser.parse_args()


def read_jsonl(path):
    if not path.exists():
        return []
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


def execute_query(db_path, sql, timeout_seconds, max_rows):
    if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
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


def results_equal(predicted_rows, gold_rows, gold_sql):
    predicted = normalize_rows(predicted_rows)
    gold = normalize_rows(gold_rows)
    if "order by" in gold_sql.lower():
        return predicted == gold
    return Counter(predicted) == Counter(gold)


def score_prediction(prediction, variant, args):
    db_path = args.data_root / variant["database_path"]
    predicted_sql = prediction.get("predicted_sql", "")
    gold_sql = variant["gold_sql"]

    if prediction.get("error"):
        return {
            "evaluation_status": "incorrect",
            "correct": False,
            "prediction_error": prediction["error"],
            "evaluation_error": None,
        }
    if not predicted_sql:
        return {
            "evaluation_status": "incorrect",
            "correct": False,
            "prediction_error": "empty predicted SQL",
            "evaluation_error": None,
        }

    try:
        predicted_meta = execute_query(
            db_path,
            predicted_sql,
            args.timeout_seconds,
            args.max_rows,
        )
    except Exception as error:
        return {
            "evaluation_status": "incorrect",
            "correct": False,
            "prediction_error": f"{type(error).__name__}: {error}",
            "evaluation_error": None,
        }

    gold_response = cached_gold_result(
        str(db_path),
        gold_sql,
        args.timeout_seconds,
        args.max_rows,
    )
    if not gold_response["ok"]:
        return {
            "evaluation_status": "evaluation_error",
            "correct": False,
            "prediction_error": None,
            "evaluation_error": gold_response["error"],
            "predicted_columns": predicted_meta["columns"],
            "predicted_row_count": len(predicted_meta["rows"]),
            "predicted_elapsed_ms": predicted_meta["elapsed_ms"],
        }

    gold_meta = gold_response["result"]
    correct = results_equal(
        predicted_meta["rows"],
        gold_meta["rows"],
        gold_sql,
    )
    return {
        "evaluation_status": "correct" if correct else "incorrect",
        "correct": correct,
        "prediction_error": None,
        "evaluation_error": None,
        "predicted_columns": predicted_meta["columns"],
        "predicted_row_count": len(predicted_meta["rows"]),
        "predicted_elapsed_ms": predicted_meta["elapsed_ms"],
        "gold_columns": gold_meta["columns"],
        "gold_row_count": len(gold_meta["rows"]),
    }


@lru_cache(maxsize=8)
def cached_gold_result(db_path, sql, timeout_seconds, max_rows):
    try:
        return {
            "ok": True,
            "result": execute_query(
                Path(db_path),
                sql,
                timeout_seconds,
                max_rows,
            ),
        }
    except Exception as error:
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
        }


def summarize(records):
    summary = {}
    for family in sorted({record["family"] for record in records}):
        family_records = [
            record for record in records if record["family"] == family
        ]
        evaluated = [
            record
            for record in family_records
            if record["evaluation_status"] != "evaluation_error"
        ]
        correct = sum(record["correct"] for record in evaluated)
        summary[family] = {
            "count": len(family_records),
            "evaluated": len(evaluated),
            "excluded_evaluation_errors": (
                len(family_records) - len(evaluated)
            ),
            "correct": correct,
            "accuracy": correct / len(evaluated) if evaluated else None,
        }
    return summary


def main():
    args = parse_args()
    args.data_root = args.data_root.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    variants = {
        record["variant_id"]: record
        for record in read_jsonl(args.variants)
    }
    predictions = read_jsonl(args.predictions)
    model_key = predictions[0]["model_key"] if predictions else "unknown"
    output_path = args.output_dir / f"{model_key}.jsonl"
    existing = read_jsonl(output_path)
    existing_ids = {record["variant_id"] for record in existing}
    pending = [
        record
        for record in predictions
        if record["variant_id"] not in existing_ids
    ]

    total = len(existing) + len(pending)
    print(
        f"model={model_key} total={total} existing={len(existing)} "
        f"pending={len(pending)}",
        flush=True,
    )

    with output_path.open("a", encoding="utf-8") as output:
        for index, prediction in enumerate(pending, start=1):
            variant = variants[prediction["variant_id"]]
            result = score_prediction(prediction, variant, args)
            record = {
                "variant_id": prediction["variant_id"],
                "question_id": prediction["question_id"],
                "db_id": prediction["db_id"],
                "family": prediction["family"],
                "model_key": model_key,
                "model": prediction["model"],
                **result,
                "predicted_sql": prediction.get("predicted_sql", ""),
                "gold_sql": variant["gold_sql"],
            }
            output.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            )
            output.write("\n")
            output.flush()
            completed = len(existing) + index
            if index % args.progress_every == 0 or index == len(pending):
                percent = completed / total * 100 if total else 100
                print(
                    f"[{completed}/{total}] {percent:.1f}% "
                    f"{record['variant_id']} {record['evaluation_status']}",
                    flush=True,
                )

    records = read_jsonl(output_path)
    summary = {
        "model_key": model_key,
        "prediction_file": str(args.predictions),
        "timeout_seconds": args.timeout_seconds,
        "by_family": summarize(records),
    }
    summary_path = args.output_dir / f"{model_key}.summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
