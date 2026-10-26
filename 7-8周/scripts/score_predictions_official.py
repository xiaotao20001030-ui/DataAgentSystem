#!/usr/bin/env python3
"""Score saved BIRD predictions with the official Mini-Dev set semantics."""

import argparse
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote


MAX_RESULT_ROWS = 200000


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, nargs="+", required=True)
    parser.add_argument("--variants", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prediction-timeout", type=float, default=30.0)
    parser.add_argument("--gold-timeout", type=float, default=30.0)
    parser.add_argument("--max-rows", type=int, default=MAX_RESULT_ROWS)
    parser.add_argument("--progress-every", type=int, default=25)
    return parser.parse_args()


def read_jsonl(path):
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def execute_query(db_path, sql, timeout_seconds, max_rows):
    if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
        raise ValueError("Only SELECT or WITH queries are allowed")

    deadline = time.perf_counter() + timeout_seconds
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
        return columns, rows
    finally:
        connection.close()


def rows_equal(predicted_rows, gold_rows):
    # BIRD Mini-Dev evaluation_ex.py line 20:
    # set(predicted_result) == set(ground_truth_result)
    return set(predicted_rows) == set(gold_rows)


def score_file(
    prediction_path,
    variants_by_id,
    data_root,
    output_dir,
    prediction_timeout,
    gold_timeout,
    max_rows,
    progress_every,
    gold_cache,
):
    predictions = read_jsonl(prediction_path)
    model_key = predictions[0]["model_key"] if predictions else "unknown"
    output_path = output_dir / f"{model_key}.jsonl"
    existing = read_jsonl(output_path)
    existing_ids = {row["variant_id"] for row in existing}
    pending = [row for row in predictions if row["variant_id"] not in existing_ids]
    total = len(predictions)

    print(
        f"model={model_key} total={total} existing={len(existing)} "
        f"pending={len(pending)}",
        flush=True,
    )

    with output_path.open("a", encoding="utf-8") as output:
        for index, prediction in enumerate(pending, start=1):
            variant = variants_by_id[prediction["variant_id"]]
            db_path = data_root / variant["database_path"]
            predicted_sql = prediction.get("predicted_sql", "")
            gold_sql = variant["gold_sql"]
            prediction_error = prediction.get("error")
            evaluation_error = None
            correct = False
            predicted_columns = None
            predicted_row_count = None
            gold_columns = None
            gold_row_count = None

            if prediction_error:
                evaluation_error = f"prediction_error: {prediction_error}"
            elif not predicted_sql:
                evaluation_error = "prediction_error: empty predicted SQL"
            else:
                try:
                    predicted_columns, predicted_rows = execute_query(
                        db_path,
                        predicted_sql,
                        prediction_timeout,
                        max_rows,
                    )
                    predicted_row_count = len(predicted_rows)
                    cache_key = (str(db_path), gold_sql)
                    if cache_key not in gold_cache:
                        try:
                            gold_columns_cached, gold_rows_cached = execute_query(
                                db_path,
                                gold_sql,
                                gold_timeout,
                                max_rows,
                            )
                            gold_cache[cache_key] = {
                                "ok": True,
                                "columns": gold_columns_cached,
                                "rows": gold_rows_cached,
                            }
                        except Exception as error:
                            gold_cache[cache_key] = {
                                "ok": False,
                                "error": f"{type(error).__name__}: {error}",
                            }
                    gold_result = gold_cache[cache_key]
                    if gold_result["ok"]:
                        gold_columns = gold_result["columns"]
                        gold_row_count = len(gold_result["rows"])
                        correct = rows_equal(predicted_rows, gold_result["rows"])
                    else:
                        evaluation_error = f"gold_error: {gold_result['error']}"
                except Exception as error:
                    evaluation_error = f"prediction_error: {type(error).__name__}: {error}"

            record = {
                "variant_id": prediction["variant_id"],
                "question_id": prediction["question_id"],
                "db_id": prediction["db_id"],
                "family": prediction["family"],
                "model_key": model_key,
                "model": prediction["model"],
                "evaluation_status": "correct" if correct else "incorrect",
                "correct": correct,
                "evaluation_error": evaluation_error,
                "predicted_columns": predicted_columns,
                "predicted_row_count": predicted_row_count,
                "gold_columns": gold_columns,
                "gold_row_count": gold_row_count,
                "predicted_sql": predicted_sql,
                "gold_sql": gold_sql,
            }
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            output.flush()
            completed = len(existing) + index
            if index % progress_every == 0 or index == len(pending):
                print(
                    f"[{completed}/{total}] {record['variant_id']} "
                    f"{record['evaluation_status']}",
                    flush=True,
                )

    records = read_jsonl(output_path)
    by_family = {}
    for family in sorted({record["family"] for record in records}):
        family_records = [record for record in records if record["family"] == family]
        correct = sum(record["correct"] for record in family_records)
        evaluation_errors = sum(bool(record["evaluation_error"]) for record in family_records)
        by_family[family] = {
            "count": len(family_records),
            "correct": correct,
            "accuracy": correct / len(family_records) if family_records else None,
            "evaluation_errors": evaluation_errors,
        }
    summary = {
        "model_key": model_key,
        "prediction_file": str(prediction_path),
        "scoring": "official_mini_dev_set_equality",
        "prediction_timeout_seconds": prediction_timeout,
        "gold_timeout_seconds": gold_timeout,
        "by_family": by_family,
    }
    (output_dir / f"{model_key}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def main():
    args = parse_args()
    args.data_root = args.data_root.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    variants_by_id = {
        row["variant_id"]: row for row in read_jsonl(args.variants)
    }
    gold_cache = {}
    for prediction_path in args.predictions:
        score_file(
            prediction_path,
            variants_by_id,
            args.data_root,
            args.output_dir,
            args.prediction_timeout,
            args.gold_timeout,
            args.max_rows,
            args.progress_every,
            gold_cache,
        )


if __name__ == "__main__":
    main()
