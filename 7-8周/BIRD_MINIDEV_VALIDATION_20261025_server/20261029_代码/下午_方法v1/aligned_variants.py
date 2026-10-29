#!/usr/bin/env python3
"""Build token-aligned A (plain top-k) and B (top-k + FK one-hop) variants for
each model, using the model's actual method-C schema token mean as the target."""

import argparse
import importlib.util
import json
import statistics
from pathlib import Path

BASE = Path("/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025")
MINIDEV = Path("/root/fsas/home/xiaotao/xiaotao/MINIDEV")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fk_expand(columns, fks):
    expanded = list(columns)
    seed = set(columns)
    for left, right in fks:
        if left in seed and right not in expanded:
            expanded.append(right)
        if right in seed and left not in expanded:
            expanded.append(left)
    return expanded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rankings", default=str(BASE / "equal_budget_fk_20261028/input/bge_rankings.jsonl"))
    parser.add_argument("--method-dir", default=str(BASE / "method_c_130"))
    parser.add_argument("--output-dir", default=str(BASE / "aligned_ab"))
    parser.add_argument("--models", default="qwen3_0_6b,qwen3_1_7b,qwen3_4b,qwen2_5_coder_1_5b")
    args = parser.parse_args()

    mv = load_module(BASE / "method_v1.py", "method_v1")
    meta = mv.load_metadata()
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(MINIDEV / "modules/Qwen3-0.6B"), local_files_only=True)
    rankings = [json.loads(line) for line in Path(args.rankings).read_text().splitlines() if line.strip()]
    fixed = [json.loads(line) for line in (BASE / "fixed_k_fk_20261029/variants/fixed_variants.jsonl").read_text().splitlines() if line.strip()]
    fixed_by_qid = {row["question_id"]: row for row in fixed if row["variant_id"].endswith("__plain_fixed_130")}
    by_qid = {}
    for row in rankings:
        base = fixed_by_qid.get(row["question_id"], {})
        by_qid[row["question_id"]] = {**row, **{k: base.get(k) for k in ("gold_sql", "evidence", "database_path", "difficulty")}}
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = {}

    for model in args.models.split(","):
        records = [json.loads(line) for line in (Path(args.method_dir) / f"{model}.jsonl").read_text().splitlines() if line.strip()]
        c_tokens = []
        for record in records:
            visible = record["visible_final"]
            db_meta = meta[record["db_id"]]
            db_path = BASE / "mini_dev_data" / f"dev_databases/{record['db_id']}/sqlite/{record['db_id']}.sqlite"
            text = "\n".join(mv.schema_lines(visible, db_meta))
            hints = mv.near_name_hints(db_meta, visible, db_path)
            if hints:
                text += "\n\nValue hints:\n" + "\n".join(hints)
            c_tokens.append(len(tokenizer.encode(text)))
        target = statistics.mean(c_tokens)
        targets[model] = {"target": target, "c_n": len(c_tokens),
                          "c_median": statistics.median(c_tokens)}
        print(f"{model}: C mean tokens {target:.2f}")

        for method in ("plain", "fk1"):
            best = None
            for k in range(1, 41):
                per_q = []
                for question_id, row in by_qid.items():
                    cols = [c.lower() for c in row["top_columns"][:k]]
                    if method == "fk1":
                        cols = fk_expand(cols, meta[row["db_id"]]["fks"])
                    text = "\n".join(mv.schema_lines(cols, meta[row["db_id"]]))
                    per_q.append(len(tokenizer.encode(text)))
                mean = statistics.mean(per_q)
                distance = abs(mean - target)
                if best is None or distance < best[0]:
                    best = (distance, k, mean)
                if mean > target + 40:
                    break
            _, k, mean = best
            family = f"{method}_align"
            rows = []
            for index, row in enumerate(rankings):
                row = by_qid[row["question_id"]]
                cols = [c.lower() for c in row["top_columns"][:k]]
                if method == "fk1":
                    cols = fk_expand(cols, meta[row["db_id"]]["fks"])
                text = "\n".join(mv.schema_lines(cols, meta[row["db_id"]]))
                rows.append({
                    "variant_id": f"q{index:04d}__{family}_{k}",
                    "question_index": index,
                    "question_id": row["question_id"],
                    "db_id": row["db_id"],
                    "question": row["question"],
                    "evidence": row.get("evidence") or "",
                    "gold_sql": row.get("gold_sql"),
                    "database_path": f"dev_databases/{row['db_id']}/sqlite/{row['db_id']}.sqlite",
                    "schema_columns": cols,
                    "schema_text": text,
                    "perturbation": {"family": family, "level": k},
                    "schema_token_target": round(target, 2),
                    "schema_token_count": len(tokenizer.encode(text)),
                })
            path = out_dir / f"variants_{model}_{method}.jsonl"
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            targets[model][method] = {"k": k, "mean_tokens": mean, "n": len(rows)}
            print(f"  {method}: k={k} mean={mean:.2f} distance={abs(mean - target):.2f}")

    (out_dir / "targets.json").write_text(json.dumps(targets, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
