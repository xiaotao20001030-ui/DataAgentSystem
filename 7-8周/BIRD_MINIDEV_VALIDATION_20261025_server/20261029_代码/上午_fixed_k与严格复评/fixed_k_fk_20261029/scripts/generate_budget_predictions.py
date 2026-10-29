#!/usr/bin/env python3
"""Run the existing model matrix with the exact schema text used for budgets."""

import importlib.util
import json
import os
from pathlib import Path


root = Path(os.environ.get(
    "BIRD_MODEL_EVAL_ROOT",
    "/root/fsas/home/xiaotao/xiaotao/MINIDEV/model_eval",
))
source = root / "generate_predictions.py"
spec = importlib.util.spec_from_file_location("bird_original_generator", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_build_prompt = module.build_prompt


def build_budget_prompt(record):
    if "schema_text" not in record:
        return original_build_prompt(record)
    evidence = record.get("evidence") or ""
    user_prompt = (
        "SQLite schema:\n"
        + record["schema_text"]
        + "\n\nQuestion:\n"
        + record["question"]
    )
    if evidence:
        user_prompt += "\n\nEvidence:\n" + evidence
    user_prompt += "\n\nReturn one SQLite query."
    return [
        {"role": "system", "content": module.SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


module.build_prompt = build_budget_prompt


def main():
    args = module.parse_args()
    configs = json.loads(args.config.read_text(encoding="utf-8"))
    config = next(item for item in configs if item["key"] == args.model_key)
    records = module.load_variants(
        args.variants, module.parse_family_filter(args.families), args.limit
    )
    by_id = {record["variant_id"]: record for record in records}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{args.model_key}.jsonl"
    existing = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()] if output_path.exists() else []
    existing_ids = {row["variant_id"] for row in existing}
    cache = {}
    for row in existing:
        variant = by_id.get(row["variant_id"])
        if variant is not None and not row.get("error"):
            key = json.dumps(build_budget_prompt(variant), ensure_ascii=False, sort_keys=True)
            cache[key] = (row["raw_response"], row["variant_id"])
    pending = [record for record in records if record["variant_id"] not in existing_ids]
    generator = None
    generated_calls = reused_calls = 0
    with output_path.open("a", encoding="utf-8") as output:
        for index, record in enumerate(pending, start=1):
            messages = build_budget_prompt(record)
            key = json.dumps(messages, ensure_ascii=False, sort_keys=True)
            reused_from = None
            if key in cache:
                raw_response, reused_from = cache[key]
                error = None
                reused_calls += 1
            else:
                if generator is None:
                    generator = module.create_generator(config, args)
                try:
                    raw_response = generator.generate(messages)
                    error = None
                    cache[key] = (raw_response, record["variant_id"])
                except Exception as exception:
                    raw_response = ""
                    error = f"{type(exception).__name__}: {exception}"
                generated_calls += 1
            prediction = {
                "variant_id": record["variant_id"],
                "question_id": record["question_id"],
                "db_id": record["db_id"],
                "family": module.family_name(record),
                "model_key": args.model_key,
                "model": config["model"],
                "raw_response": raw_response,
                "predicted_sql": module.extract_sql(raw_response),
                "error": error,
                "reused_prompt_from_variant_id": reused_from,
            }
            output.write(json.dumps(prediction, ensure_ascii=False, separators=(",", ":")) + "\n")
            output.flush()
            if index % 100 == 0 or index == len(pending):
                print(f"[{index}/{len(pending)}] generated={generated_calls} reused={reused_calls}", flush=True)
    print(f"Predictions: {output_path}", flush=True)


if __name__ == "__main__":
    main()
