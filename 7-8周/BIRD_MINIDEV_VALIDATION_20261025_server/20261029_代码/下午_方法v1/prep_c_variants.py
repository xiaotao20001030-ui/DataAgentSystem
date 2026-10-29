#!/usr/bin/env python3
"""Build per-model variant files for method-C predictions (visible schema = final)."""

import argparse
import json
from pathlib import Path

BASE = Path("/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025")
FIXED = BASE / "fixed_k_fk_20261029/variants/fixed_variants.jsonl"
OUT = BASE / "method_c_130/variants"


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="")
    args = parser.parse_args()
    wanted = {m.strip() for m in args.models.split(",") if m.strip()}
    fixed = {v["question_id"]: v for v in read(FIXED) if v["variant_id"].endswith("__plain_fixed_130")}
    OUT.mkdir(parents=True, exist_ok=True)
    for path in sorted((BASE / "method_c_130").glob("*.jsonl")):
        if wanted and path.stem not in wanted:
            continue
        model = path.stem
        rows = []
        for record in read(path):
            base = fixed[record["question_id"]]
            rows.append({
                "variant_id": record["variant_id"],
                "question_id": record["question_id"],
                "db_id": record["db_id"],
                "question": base["question"],
                "evidence": base.get("evidence") or "",
                "gold_sql": base["gold_sql"],
                "database_path": base["database_path"],
                "schema_columns": record["visible_final"],
                "perturbation": {"family": "method_c", "level": record["rounds"]},
            })
        (OUT / f"{model}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(model, len(rows))


if __name__ == "__main__":
    main()
