#!/usr/bin/env python3
"""Compare robustness on questions both models answer correctly at baseline."""

import argparse
import json
from pathlib import Path

import numpy as np


BOOTSTRAP_ITERATIONS = 10000
FAMILIES = ("add_random_20", "add_synonym_20")


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scores-dir",
        type=Path,
        default=project_root / "model_eval" / "scores_fixed",
    )
    parser.add_argument("--control-model", default="api_control")
    parser.add_argument(
        "--models",
        default=(
            "qwen3_0_6b,"
            "qwen2_5_coder_1_5b,"
            "qwen3_1_7b,"
            "qwen3_4b"
        ),
    )
    parser.add_argument("--seed", type=int, default=20261020)
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "model_eval"
        / "conditional_robustness.json",
    )
    return parser.parse_args()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def correctness_maps(records):
    maps = {}
    for record in records:
        if record.get("evaluation_status") == "evaluation_error":
            continue
        maps.setdefault(record["question_id"], {})[
            record["family"]
        ] = bool(record["correct"])
    return maps


def difference_table(local_values, control_values):
    local = np.asarray(local_values, dtype=float)
    control = np.asarray(control_values, dtype=float)
    difference = control - local
    return {
        "local_retention": float(local.mean()),
        "control_retention": float(control.mean()),
        "local_extra_failure": float(difference.mean()),
        "local_extra_failure_percentage_points": float(difference.mean() * 100),
    }


def bootstrap_difference(local_values, control_values, seed):
    local = np.asarray(local_values, dtype=float)
    control = np.asarray(control_values, dtype=float)
    difference = control - local
    rng = np.random.default_rng(seed)
    samples = np.empty(BOOTSTRAP_ITERATIONS)
    for index in range(BOOTSTRAP_ITERATIONS):
        chosen = rng.integers(0, len(difference), size=len(difference))
        samples[index] = difference[chosen].mean()
    return {
        "ci95_low": float(np.quantile(samples, 0.025)),
        "ci95_high": float(np.quantile(samples, 0.975)),
        "ci95_low_percentage_points": float(
            np.quantile(samples, 0.025) * 100
        ),
        "ci95_high_percentage_points": float(
            np.quantile(samples, 0.975) * 100
        ),
        "p_one_sided": float(
            (np.count_nonzero(samples <= 0) + 1)
            / (BOOTSTRAP_ITERATIONS + 1)
        ),
        "iterations": BOOTSTRAP_ITERATIONS,
    }


def main():
    args = parse_args()
    model_keys = [item.strip() for item in args.models.split(",") if item.strip()]
    control_records = read_jsonl(
        args.scores_dir / f"{args.control_model}.jsonl"
    )
    control = correctness_maps(control_records)
    result = {
        "definition": (
            "retention on questions where both the local model and control "
            "answer the base condition correctly"
        ),
        "control_model": args.control_model,
        "models": {},
    }

    for model_index, model_key in enumerate(model_keys):
        local = correctness_maps(
            read_jsonl(args.scores_dir / f"{model_key}.jsonl")
        )
        model_result = {}
        for family_index, family in enumerate(FAMILIES):
            question_ids = sorted(
                question_id
                for question_id in set(local) & set(control)
                if local[question_id].get("base")
                and control[question_id].get("base")
                and family in local[question_id]
                and family in control[question_id]
            )
            local_values = [
                local[question_id][family] for question_id in question_ids
            ]
            control_values = [
                control[question_id][family] for question_id in question_ids
            ]
            model_result[family] = {
                "common_base_correct_questions": len(question_ids),
                **difference_table(local_values, control_values),
                **bootstrap_difference(
                    local_values,
                    control_values,
                    args.seed + model_index * 100 + family_index,
                ),
            }
        result["models"][model_key] = model_result

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
