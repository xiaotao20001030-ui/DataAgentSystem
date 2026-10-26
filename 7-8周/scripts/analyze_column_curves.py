#!/usr/bin/env python3
"""Build 5/10/20/50 execution-accuracy curves for all five models."""

import argparse
import csv
import json
from pathlib import Path


MODELS = (
    "qwen3_0_6b",
    "qwen2_5_coder_1_5b",
    "qwen3_1_7b",
    "qwen3_4b",
    "api_control",
)
PERTURBATIONS = {
    "random": (
        (5, "add_random_5"),
        (10, "add_random_10"),
        (20, "add_random_20"),
        (50, "add_random_50"),
    ),
    "synonym": (
        (5, "add_synonym_5"),
        (10, "add_synonym_10"),
        (20, "add_synonym_20"),
        (50, "add_synonym_50"),
    ),
}


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument(
        "--scores-dir",
        type=Path,
        default=None,
        help="Use one combined score directory for every condition.",
    )
    parser.add_argument(
        "--output-prefix",
        default="column_level_curves",
        help="Prefix for JSON/CSV/Markdown outputs.",
    )
    return parser.parse_args()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def family_map(records, family):
    result = {}
    for record in records:
        if (
            record["family"] == family
            and record.get("evaluation_status") != "evaluation_error"
        ):
            result[record["question_id"]] = bool(record["correct"])
    return result


def main():
    args = parse_args()
    root = args.project_root.resolve()
    if args.scores_dir:
        combined_dir = args.scores_dir.resolve()
        score_dirs = {"primary": combined_dir, "all_levels": combined_dir}
    else:
        score_dirs = {
            "primary": root / "model_eval" / "scores_fixed",
            "all_levels": root / "model_eval" / "scores_all_levels",
        }
    output_root = root / "BIRD_RESULTS"
    analysis_dir = output_root / "analysis"
    report_dir = output_root / "reports"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    full = {"models": {}}
    for model in MODELS:
        primary = read_jsonl(score_dirs["primary"] / f"{model}.jsonl")
        all_levels = read_jsonl(score_dirs["all_levels"] / f"{model}.jsonl")
        base = family_map(primary, "base")
        model_result = {}

        for perturbation, conditions in PERTURBATIONS.items():
            level_maps = {}
            for level, family in conditions:
                source = primary if level == 20 else all_levels
                records = primary if level == 20 else all_levels
                level_maps[level] = family_map(records, family)

            common_questions = set(base)
            for values in level_maps.values():
                common_questions &= set(values)
            common_questions = sorted(common_questions)

            base_correct = sum(base[qid] for qid in common_questions)
            base_accuracy = (
                base_correct / len(common_questions) if common_questions else None
            )
            model_result[perturbation] = {
                "common_questions": len(common_questions),
                "base_accuracy": base_accuracy,
                "levels": {},
            }
            for level, _ in conditions:
                values = level_maps[level]
                correct = sum(values[qid] for qid in common_questions)
                accuracy = (
                    correct / len(common_questions)
                    if common_questions
                    else None
                )
                drop = (
                    base_accuracy - accuracy
                    if base_accuracy is not None and accuracy is not None
                    else None
                )
                model_result[perturbation]["levels"][str(level)] = {
                    "correct": correct,
                    "count": len(common_questions),
                    "accuracy": accuracy,
                    "drop": drop,
                    "drop_percentage_points": drop * 100 if drop is not None else None,
                }
                rows.append(
                    {
                        "model": model,
                        "perturbation": perturbation,
                        "level": level,
                        "count": len(common_questions),
                        "correct": correct,
                        "accuracy": accuracy,
                        "accuracy_percent": accuracy * 100 if accuracy is not None else None,
                        "drop_percentage_points": drop * 100 if drop is not None else None,
                    }
                )
        full["models"][model] = model_result

    (analysis_dir / f"{args.output_prefix}.json").write_text(
        json.dumps(full, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (analysis_dir / f"{args.output_prefix}.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# 5/10/20/50 列执行准确率曲线",
        "",
        "所有档位使用共同可评测题目的配对口径。",
        "",
    ]
    for perturbation in ("random", "synonym"):
        lines.extend(
            [
                f"## {perturbation}",
                "",
                "| 模型 | base | level 5 | level 10 | level 20 | level 50 |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for model in MODELS:
            result = full["models"][model][perturbation]
            cells = [
                f"{result['base_accuracy'] * 100:.2f}%",
                *[
                    f"{result['levels'][str(level)]['accuracy'] * 100:.2f}%"
                    for level in (5, 10, 20, 50)
                ],
            ]
            lines.append("| " + model + " | " + " | ".join(cells) + " |")
        lines.append("")

    (report_dir / f"{args.output_prefix.upper()}_RESULTS.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(full, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
