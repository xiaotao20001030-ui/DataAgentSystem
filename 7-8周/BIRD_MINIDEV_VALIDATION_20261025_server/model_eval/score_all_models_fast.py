#!/usr/bin/env python3
"""Score all local models with one shared cache of the 500 gold executions."""

import argparse
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import score_predictions as common


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variants",
        type=Path,
        default=project_root / "perturbations" / "output" / "mini_dev_perturbations.jsonl",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=project_root / "mini_dev_data",
    )
    parser.add_argument(
        "--predictions-dir",
        type=Path,
        default=project_root / "model_eval" / "predictions",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "model_eval" / "scores",
    )
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--gold-workers", type=int, default=8)
    parser.add_argument("--gold-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-rows", type=int, default=common.MAX_RESULT_ROWS)
    parser.add_argument("--comparison", choices=("set", "multiset", "ordered"), default="set")
    return parser.parse_args()


def main():
    args = parse_args()
    variants = common.read_jsonl(args.variants)
    variant_by_id = {record["variant_id"]: record for record in variants}
    base_by_question = {
        record["question_id"]: record
        for record in variants
        if record["perturbation"]["family"] == "base"
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def execute_gold(item):
        question_id, record = item
        db_path = args.data_root / record["database_path"]
        try:
            meta = common.execute_query(
                db_path,
                record["gold_sql"],
                args.gold_timeout_seconds,
                args.max_rows,
            )
            return question_id, meta, None
        except Exception as exception:
            return question_id, None, f"{type(exception).__name__}: {exception}"

    with ThreadPoolExecutor(max_workers=args.gold_workers) as pool:
        gold_results = list(pool.map(execute_gold, base_by_question.items()))
    gold_cache = {question_id: (meta, error) for question_id, meta, error in gold_results}
    gold_errors = {question_id: error for question_id, (_, error) in gold_cache.items() if error}
    print(
        f"Gold cache ready: {len(gold_cache)} questions; "
        f"unscorable={json.dumps(gold_errors, ensure_ascii=False)}",
        flush=True,
    )

    prediction_paths = sorted(args.predictions_dir.glob("*.jsonl"))
    if not prediction_paths:
        raise SystemExit(f"No prediction files in {args.predictions_dir}")

    for prediction_path in prediction_paths:
        predictions = common.read_jsonl(prediction_path)
        model_key = predictions[0]["model_key"] if predictions else prediction_path.stem

        def score_one(prediction):
            variant = variant_by_id[prediction["variant_id"]]
            gold_meta, gold_error = gold_cache[prediction["question_id"]]
            gold_sql = variant["gold_sql"]
            predicted_sql = prediction.get("predicted_sql", "")
            error = prediction.get("error")
            predicted_meta = None
            correct = False
            if gold_error:
                error = f"GoldUnscorable: {gold_error}"
            elif not error and predicted_sql:
                try:
                    predicted_meta = common.execute_query(
                        args.data_root / variant["database_path"],
                        predicted_sql,
                        args.timeout_seconds,
                        args.max_rows,
                    )
                    correct = common.results_equal(
                        predicted_meta["rows"],
                        gold_meta["rows"],
                        gold_sql,
                        args.comparison,
                    )
                except Exception as exception:
                    error = f"{type(exception).__name__}: {exception}"
            return {
                "variant_id": prediction["variant_id"],
                "question_id": prediction["question_id"],
                "db_id": prediction["db_id"],
                "family": prediction["family"],
                "model_key": prediction["model_key"],
                "model": prediction["model"],
                "correct": correct,
                "error": error,
                "gold_unscorable": bool(gold_error),
                "predicted_sql": predicted_sql,
                "gold_sql": gold_sql,
                "predicted_columns": predicted_meta["columns"] if predicted_meta else None,
                "predicted_row_count": len(predicted_meta["rows"]) if predicted_meta else None,
                "predicted_elapsed_ms": predicted_meta["elapsed_ms"] if predicted_meta else None,
                "gold_columns": gold_meta["columns"] if gold_meta else None,
                "gold_row_count": len(gold_meta["rows"]) if gold_meta else None,
            }

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            scored = list(pool.map(score_one, predictions))
        output_path = args.output_dir / f"{model_key}.jsonl"
        with output_path.open("w", encoding="utf-8") as output:
            for record in scored:
                output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                output.write("\n")

        grouped = defaultdict(list)
        for record in scored:
            grouped[record["family"]].append(record)
        by_family = {}
        for family, records in sorted(grouped.items()):
            scorable = [record for record in records if not record["gold_unscorable"]]
            by_family[family] = {
                "count": len(records),
                "scorable_count": len(scorable),
                "gold_unscorable_count": len(records) - len(scorable),
                "correct": sum(record["correct"] for record in scorable),
                "accuracy": (
                    sum(record["correct"] for record in scorable) / len(scorable)
                    if scorable else None
                ),
            }
        summary = {
            "model_key": model_key,
            "prediction_file": str(prediction_path),
            "prediction_sha256": hashlib.sha256(prediction_path.read_bytes()).hexdigest(),
            "comparison": args.comparison,
            "gold_cache_questions": len(gold_cache),
            "gold_unscorable_questions": gold_errors,
            "by_family": by_family,
        }
        (args.output_dir / f"{model_key}.summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Scored {model_key}: {len(scored)} records", flush=True)


if __name__ == "__main__":
    main()
