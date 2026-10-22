#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path("/root/fsas/home/xiaotao/xiaotao/MINIDEV")
OLD_ROOT = ROOT / "BIRD_RESULTS" / "scores"
NEW_ROOT = ROOT / "BIRD_RESULTS" / "scores_official"
OUTPUT_JSON = ROOT / "BIRD_RESULTS" / "analysis" / "official_rescore_delta.json"
OUTPUT_CSV = ROOT / "BIRD_RESULTS" / "analysis" / "official_rescore_delta.csv"

CONDITIONS = (
    "base",
    "random/level_5",
    "random/level_10",
    "random/level_20",
    "random/level_50",
    "synonym/level_5",
    "synonym/level_10",
    "synonym/level_20",
    "synonym/level_50",
    "real_synonym/level_20",
    "missing",
)
MODELS = (
    "qwen3_0_6b",
    "qwen3_1_7b",
    "qwen3_4b",
    "qwen2_5_coder_1_5b",
    "api_control",
)


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    rows = []
    for condition in CONDITIONS:
        for model in MODELS:
            old_path = OLD_ROOT / condition / f"{model}.jsonl"
            new_path = NEW_ROOT / condition / f"{model}.jsonl"
            if not old_path.exists() or not new_path.exists():
                continue
            old = {row["variant_id"]: bool(row["correct"]) for row in read_jsonl(old_path)}
            new = {row["variant_id"]: bool(row["correct"]) for row in read_jsonl(new_path)}
            ids = sorted(old.keys() & new.keys())
            old_correct = sum(old[item] for item in ids)
            new_correct = sum(new[item] for item in ids)
            false_to_true = sum((not old[item]) and new[item] for item in ids)
            true_to_false = sum(old[item] and (not new[item]) for item in ids)
            rows.append(
                {
                    "condition": condition,
                    "model": model,
                    "count": len(ids),
                    "old_correct": old_correct,
                    "new_correct": new_correct,
                    "old_accuracy": old_correct / len(ids) if ids else None,
                    "new_accuracy": new_correct / len(ids) if ids else None,
                    "accuracy_delta_percentage_points": (
                        100 * (new_correct - old_correct) / len(ids) if ids else None
                    ),
                    "false_to_true": false_to_true,
                    "true_to_false": true_to_false,
                }
            )
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(OUTPUT_JSON)
    print(OUTPUT_CSV)


if __name__ == "__main__":
    main()
