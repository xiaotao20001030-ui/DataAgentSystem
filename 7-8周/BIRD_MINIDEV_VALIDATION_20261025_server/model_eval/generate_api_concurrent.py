#!/usr/bin/env python3
"""Generate OpenAI-compatible API predictions concurrently and resumably."""

import argparse
import importlib.util
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def load_base_module(project_root: Path):
    module_path = project_root / "model_eval" / "generate_predictions.py"
    spec = importlib.util.spec_from_file_location("generate_predictions", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--model-key", default="api_control")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument(
        "--families",
        default=(
            "base,add_random_5,add_random_10,add_random_20,add_random_50,"
            "add_synonym_5,add_synonym_10,add_synonym_20,add_synonym_50,"
            "missing_bridge_table,missing_fk_column"
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    project_root = args.project_root.resolve()
    base = load_base_module(project_root)
    config_path = project_root / "model_eval" / "model_matrix.json"
    configs = json.loads(config_path.read_text(encoding="utf-8"))
    config = next(item for item in configs if item["key"] == args.model_key)

    compat_args = argparse.Namespace(
        api_base=None,
        api_key_env=args.api_key_env,
        temperature=args.temperature,
        max_new_tokens=args.max_new_tokens,
        retries=args.retries,
    )
    generator = base.OpenAIChatGenerator(config, compat_args)
    variants_path = (
        project_root / "perturbations" / "output" / "mini_dev_perturbations.jsonl"
    )
    records = base.load_variants(
        variants_path,
        base.parse_family_filter(args.families),
        None,
    )
    output_path = project_root / "model_eval" / "predictions" / f"{args.model_key}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = base.load_existing_ids(output_path)
    pending = [record for record in records if record["variant_id"] not in existing_ids]
    write_lock = threading.Lock()

    def generate(record):
        messages = base.build_prompt(record)
        try:
            raw_response = generator.generate(messages)
            error = None
        except Exception as exception:
            raw_response = ""
            error = f"{type(exception).__name__}: {exception}"
        return {
            "variant_id": record["variant_id"],
            "question_id": record["question_id"],
            "db_id": record["db_id"],
            "family": base.family_name(record),
            "model_key": args.model_key,
            "model": config["model"],
            "raw_response": raw_response,
            "predicted_sql": base.extract_sql(raw_response),
            "error": error,
        }

    print(f"Existing: {len(existing_ids)}; pending: {len(pending)}; workers: {args.workers}", flush=True)
    with output_path.open("a", encoding="utf-8") as output:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(generate, record): record for record in pending}
            for index, future in enumerate(as_completed(futures), start=1):
                prediction = future.result()
                with write_lock:
                    output.write(json.dumps(prediction, ensure_ascii=False, separators=(",", ":")))
                    output.write("\n")
                    output.flush()
                if index == 1 or index % 25 == 0 or index == len(pending):
                    print(f"[{index}/{len(pending)}] {prediction['variant_id']}", flush=True)

    print(f"Predictions: {output_path}", flush=True)


if __name__ == "__main__":
    main()
