#!/usr/bin/env python3
"""Apply the qwen-vs-API execution accuracy decision gate."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np


BOOTSTRAP_ITERATIONS = 10000
MIN_DROP_GAP = 0.10


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "model_eval" / "model_matrix.json",
    )
    parser.add_argument(
        "--scores-dir",
        type=Path,
        default=project_root / "model_eval" / "scores",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "model_eval" / "execution_gate.json",
    )
    parser.add_argument("--seed", type=int, default=20261019)
    return parser.parse_args()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def correctness_map(records, family):
    return {
        record["question_id"]: bool(record["correct"])
        for record in records
        if record["family"] == family
        and record.get("evaluation_status") != "evaluation_error"
    }


def pair_maps(baseline, perturbed):
    question_ids = sorted(set(baseline) & set(perturbed))
    return [
        (int(baseline[qid]) - int(perturbed[qid]))
        for qid in question_ids
    ]


def accuracy(values):
    return sum(values) / len(values) if values else None


def bootstrap_paired_difference(small_drop, large_drop, seed):
    size = min(len(small_drop), len(large_drop))
    if size == 0:
        return None
    small = np.asarray(small_drop[:size], dtype=float)
    large = np.asarray(large_drop[:size], dtype=float)
    paired = small - large
    rng = np.random.default_rng(seed)
    values = np.empty(BOOTSTRAP_ITERATIONS)
    for index in range(BOOTSTRAP_ITERATIONS):
        sample = rng.integers(0, size, size=size)
        values[index] = paired[sample].mean()
    observed = float(paired.mean())
    return {
        "question_count": size,
        "difference_in_accuracy_drop": observed,
        "difference_in_accuracy_drop_percentage_points": observed * 100,
        "ci95_low": float(np.quantile(values, 0.025)),
        "ci95_high": float(np.quantile(values, 0.975)),
        "ci95_low_percentage_points": float(np.quantile(values, 0.025) * 100),
        "ci95_high_percentage_points": float(np.quantile(values, 0.975) * 100),
        "p_one_sided": float(
            (np.count_nonzero(values <= 0) + 1) / (BOOTSTRAP_ITERATIONS + 1)
        ),
        "passed": (
            observed >= MIN_DROP_GAP
            and float(np.quantile(values, 0.025)) > 0
        ),
    }


def main():
    args = parse_args()
    configs = json.loads(args.config.read_text(encoding="utf-8"))
    small_models = [item for item in configs if item.get("role") == "small"]
    large_models = [item for item in configs if item.get("role") == "large"]
    if not large_models:
        raise SystemExit("No model with role=large in model matrix")
    control = large_models[0]
    control_path = args.scores_dir / f"{control['key']}.jsonl"
    if not control_path.exists():
        raise SystemExit(f"Missing large-model scores: {control_path}")
    control_records = read_jsonl(control_path)

    result = {
        "criterion": "small-model drop at 20 added columns exceeds API control by >= 10 pp",
        "minimum_drop_gap": MIN_DROP_GAP,
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "control_model": control,
        "models": {},
    }
    all_passed = True
    for model in small_models:
        score_path = args.scores_dir / f"{model['key']}.jsonl"
        if not score_path.exists():
            result["models"][model["key"]] = {"status": "missing_scores"}
            all_passed = False
            continue
        records = read_jsonl(score_path)
        model_result = {"status": "complete", "perturbations": {}}
        for family in ("add_random_20", "add_synonym_20"):
            small_base = correctness_map(records, "base")
            small_noise = correctness_map(records, family)
            large_base = correctness_map(control_records, "base")
            large_noise = correctness_map(control_records, family)
            common_ids = sorted(
                set(small_base)
                & set(small_noise)
                & set(large_base)
                & set(large_noise)
            )
            small_base_values = [small_base[qid] for qid in common_ids]
            small_noise_values = [small_noise[qid] for qid in common_ids]
            large_base_values = [large_base[qid] for qid in common_ids]
            large_noise_values = [large_noise[qid] for qid in common_ids]
            small_drop = pair_maps(small_base, small_noise)
            large_drop = pair_maps(large_base, large_noise)
            gate = bootstrap_paired_difference(
                small_drop,
                large_drop,
                args.seed,
            )
            if not gate or not gate["passed"]:
                all_passed = False
            if gate:
                gate.update(
                    {
                        "small_baseline_accuracy": accuracy(small_base_values),
                        "small_perturbed_accuracy": accuracy(small_noise_values),
                        "small_accuracy_drop": (
                            accuracy(small_base_values)
                            - accuracy(small_noise_values)
                        ),
                        "large_baseline_accuracy": accuracy(large_base_values),
                        "large_perturbed_accuracy": accuracy(large_noise_values),
                        "large_accuracy_drop": (
                            accuracy(large_base_values)
                            - accuracy(large_noise_values)
                        ),
                    }
                )
            model_result["perturbations"][family] = gate
        result["models"][model["key"]] = model_result

    result["passed"] = all_passed
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
