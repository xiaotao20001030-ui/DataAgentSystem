#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path("/root/fsas/home/xiaotao/xiaotao/MINIDEV")
SCORE_ROOT = ROOT / "BIRD_RESULTS" / "scores_official"
OUTPUT = SCORE_ROOT / "combined"
MODELS = (
    "qwen3_0_6b",
    "qwen3_1_7b",
    "qwen3_4b",
    "qwen2_5_coder_1_5b",
    "api_control",
)
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


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        records = []
        for condition in CONDITIONS:
            path = SCORE_ROOT / condition / f"{model}.jsonl"
            if not path.exists():
                raise FileNotFoundError(path)
            records.extend(read_jsonl(path))
        records.sort(key=lambda row: (row["question_id"], row["family"], row["variant_id"]))
        output_path = OUTPUT / f"{model}.jsonl"
        output_path.write_text(
            "\n".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                for row in records
            )
            + "\n",
            encoding="utf-8",
        )
        print(output_path, len(records))


if __name__ == "__main__":
    main()
