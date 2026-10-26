#!/usr/bin/env python3
"""Analyze real-schema-only synonym sensitivity against baseline correctness."""

import argparse
import json
from pathlib import Path

import numpy as np


BOOTSTRAP_ITERATIONS = 10000


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-scores-dir",
        type=Path,
        default=project_root / "model_eval" / "scores_fixed",
    )
    parser.add_argument(
        "--sensitivity-scores-dir",
        type=Path,
        default=project_root / "model_eval" / "scores_real_synonym",
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
        / "real_synonym_sensitivity.json",
    )
    return parser.parse_args()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def results_map(records, family):
    result = {}
    for record in records:
        if (
            record["family"] == family
            and record.get("evaluation_status") != "evaluation_error"
        ):
            result[record["question_id"]] = bool(record["correct"])
    return result


def bootstrap(local_values, control_values, seed):
    local = np.asarray(local_values, dtype=float)
    control = np.asarray(control_values, dtype=float)
    difference = control - local
    rng = np.random.default_rng(seed)
    samples = np.empty(BOOTSTRAP_ITERATIONS)
    for index in range(BOOTSTRAP_ITERATIONS):
        chosen = rng.integers(0, len(difference), len(difference))
        samples[index] = difference[chosen].mean()
    return {
        "local_retention": float(local.mean()),
        "control_retention": float(control.mean()),
        "local_extra_failure": float(difference.mean()),
        "local_extra_failure_percentage_points": float(
            difference.mean() * 100
        ),
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
    }


def main():
    args = parse_args()
    model_keys = [item.strip() for item in args.models.split(",") if item.strip()]
    control_base = results_map(
        read_jsonl(args.base_scores_dir / f"{args.control_model}.jsonl"),
        "base",
    )
    control_sensitivity = results_map(
        read_jsonl(
            args.sensitivity_scores_dir / f"{args.control_model}.jsonl"
        ),
        "add_real_synonym_20",
    )

    result = {
        "definition": (
            "retention under 20 real near-synonym columns for questions "
            "where local and control are both correct at base"
        ),
        "control_model": args.control_model,
        "models": {},
    }
    for model_index, model_key in enumerate(model_keys):
        local_base = results_map(
            read_jsonl(args.base_scores_dir / f"{model_key}.jsonl"),
            "base",
        )
        local_sensitivity = results_map(
            read_jsonl(
                args.sensitivity_scores_dir / f"{model_key}.jsonl"
            ),
            "add_real_synonym_20",
        )
        question_ids = sorted(
            question_id
            for question_id in set(local_base) & set(control_base)
            if local_base[question_id]
            and control_base[question_id]
            and question_id in local_sensitivity
            and question_id in control_sensitivity
        )
        local_values = [
            local_sensitivity[question_id] for question_id in question_ids
        ]
        control_values = [
            control_sensitivity[question_id] for question_id in question_ids
        ]
        result["models"][model_key] = {
            "common_base_correct_questions": len(question_ids),
            **bootstrap(
                local_values,
                control_values,
                args.seed + model_index,
            ),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
