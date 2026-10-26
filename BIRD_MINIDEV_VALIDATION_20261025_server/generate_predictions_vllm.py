#!/usr/bin/env python3
"""Generate the local-model prediction matrix with deterministic vLLM decoding."""

import argparse
import json
from pathlib import Path

from vllm import LLM, SamplingParams

import generate_predictions as common


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variants",
        type=Path,
        default=project_root / "perturbations" / "output" / "mini_dev_perturbations.jsonl",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "model_eval" / "model_matrix.json",
    )
    parser.add_argument("--model-key", required=True)
    parser.add_argument("--families", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "model_eval" / "predictions",
    )
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--max-model-len", type=int, default=8192)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.80)
    parser.add_argument("--seed", type=int, default=20261019)
    return parser.parse_args()


def render_prompt(tokenizer, record):
    messages = common.build_prompt(record)
    kwargs = {
        "tokenize": False,
        "add_generation_prompt": True,
    }
    try:
        return tokenizer.apply_chat_template(
            messages,
            enable_thinking=False,
            **kwargs,
        )
    except TypeError:
        return tokenizer.apply_chat_template(messages, **kwargs)


def main():
    args = parse_args()
    configs = json.loads(args.config.read_text(encoding="utf-8"))
    config_by_key = {item["key"]: item for item in configs}
    config = config_by_key[args.model_key]
    if config["provider"] != "transformers":
        raise SystemExit("vLLM runner supports local transformer models only")

    records = common.load_variants(
        args.variants,
        common.parse_family_filter(args.families),
        None,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{args.model_key}.jsonl"
    existing_ids = common.load_existing_ids(output_path)
    pending = [record for record in records if record["variant_id"] not in existing_ids]
    if not pending:
        print(f"No pending predictions: {output_path}")
        return

    engine = LLM(
        model=config["model"],
        tokenizer=config["model"],
        dtype="float16",
        seed=args.seed,
        trust_remote_code=True,
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
        enforce_eager=False,
    )
    tokenizer = engine.get_tokenizer()
    prompts = [render_prompt(tokenizer, record) for record in pending]
    sampling = SamplingParams(
        temperature=0.0,
        max_tokens=args.max_new_tokens,
        seed=args.seed,
    )
    generations = engine.generate(prompts, sampling, use_tqdm=True)

    with output_path.open("a", encoding="utf-8") as output:
        for record, generation in zip(pending, generations):
            raw_response = generation.outputs[0].text if generation.outputs else ""
            prediction = {
                "variant_id": record["variant_id"],
                "question_id": record["question_id"],
                "db_id": record["db_id"],
                "family": common.family_name(record),
                "model_key": args.model_key,
                "model": config["model"],
                "raw_response": raw_response,
                "predicted_sql": common.extract_sql(raw_response),
                "error": None if generation.outputs else "NoGenerationOutput",
            }
            output.write(json.dumps(prediction, ensure_ascii=False, separators=(",", ":")))
            output.write("\n")
    print(f"Predictions: {output_path}; records={len(pending)}")


if __name__ == "__main__":
    main()
