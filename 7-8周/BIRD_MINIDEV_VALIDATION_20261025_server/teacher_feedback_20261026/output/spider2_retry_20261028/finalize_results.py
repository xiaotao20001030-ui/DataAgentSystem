#!/usr/bin/env python3
"""Compute five-model common-denominator Spider accuracy and preregistered gate."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from generate_silver import read_jsonl


CONDITIONS = ("base", "random20", "synonym20")
DEFAULT_MODELS = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b",
                  "qwen2_5_coder_1_5b", "api_control")


def compute(stratum, qids, scores, models, rng):
    rows = []
    for condition in ("random20", "synonym20"):
        api_base = np.array([int(scores[(q, "base", "api_control")]["correct"]) for q in qids])
        api_pert = np.array([int(scores[(q, condition, "api_control")]["correct"]) for q in qids])
        api_drop = (api_base - api_pert).mean() * 100
        for model in models:
            base = np.array([int(scores[(q, "base", model)]["correct"]) for q in qids])
            pert = np.array([int(scores[(q, condition, model)]["correct"]) for q in qids])
            drop = (base - pert).mean() * 100
            difference = drop - api_drop
            paired = (base - pert) - (api_base - api_pert)
            draws = rng.integers(0, len(qids), size=(10000, len(qids)))
            bootstrap = paired[draws].mean(axis=1) * 100
            lo, hi = np.quantile(bootstrap, (0.025, 0.975))
            rows.append({"stratum": stratum, "condition": condition,
                         "model": model, "n": len(qids),
                         "base_accuracy": float(base.mean()),
                         "perturbed_accuracy": float(pert.mean()),
                         "drop_pp": float(drop), "api_drop_pp": float(api_drop),
                         "drop_difference_pp": float(difference),
                         "ci95_lower_pp": float(lo), "ci95_upper_pp": float(hi),
                         "passes_individual": bool(model != "api_control" and difference > 10 and lo > 0)})
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scores-dir", type=Path, required=True)
    p.add_argument("--variants", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--models", default=",".join(DEFAULT_MODELS))
    p.add_argument("--seed", type=int, default=20261028)
    args = p.parse_args()
    models = tuple(args.models.split(","))
    if len(models) != 5 or "api_control" not in models:
        raise ValueError("Exactly five models including api_control are required")
    variants = {x["variant_id"]: x for x in read_jsonl(args.variants)}
    qids = {x["instance_id"] for x in variants.values()}
    scores = {}
    for model in models:
        path = args.scores_dir / f"{model}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(path)
        for row in read_jsonl(path):
            if row["model_key"] != model:
                raise ValueError(f"Score model mismatch in {path}")
            scores[(row["instance_id"], row["condition"], model)] = row
    common = sorted(q for q in qids if all(
        (q, condition, model) in scores and scores[(q, condition, model)]["scorable"]
        for condition in CONDITIONS for model in models))
    if not common:
        raise RuntimeError("No five-model, three-condition common scored questions")
    source_by_q = {}
    for variant in variants.values():
        source_by_q[variant["instance_id"]] = variant["label_source"]
    rng = np.random.default_rng(args.seed)
    rows = []
    rows.extend(compute("all", common, scores, models, rng))
    for source in ("gold_sql", "silver_result_match"):
        subset = [q for q in common if source_by_q[q] == source]
        if subset:
            rows.extend(compute(source, subset, scores, models, rng))
    verdict = {}
    for condition in ("random20", "synonym20"):
        passing = [x["model"] for x in rows if x["stratum"] == "all"
                   and x["condition"] == condition and x["passes_individual"]]
        verdict[condition] = {"passing_small_models": passing,
                              "passes": len(passing) >= 2}
    verdict["overall_passes"] = any(verdict[c]["passes"] for c in ("random20", "synonym20"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps({
        "eligible_with_variants": len(qids), "common_scored_n": len(common),
        "common_gold_n": sum(source_by_q[q] == "gold_sql" for q in common),
        "common_silver_n": sum(source_by_q[q] == "silver_result_match" for q in common),
        "seed": args.seed, "bootstrap_resamples": 10000,
        "rows": rows, "verdict": verdict,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.output_dir / "paired_accuracy.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# Spider 2.0-Lite SQLite 实验二：随机与近义列扰动",
             "", f"五模型三条件共同可评分题数：**{len(common)}**；原生 gold SQL："
             f"**{sum(source_by_q[q] == 'gold_sql' for q in common)}**；"
             f"结果匹配银标签：**{sum(source_by_q[q] == 'silver_result_match' for q in common)}**。",
             "", "| 条件 | 模型 | 基线准确率 | 扰动准确率 | 掉点 pp | 相对 API 多掉 pp [95% CI] | n |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        if row["stratum"] != "all":
            continue
        lines.append(f"| {row['condition']} | {row['model']} | {row['base_accuracy']:.1%} | "
                     f"{row['perturbed_accuracy']:.1%} | {row['drop_pp']:+.1f} | "
                     f"{row['drop_difference_pp']:+.1f} [{row['ci95_lower_pp']:+.1f}, {row['ci95_upper_pp']:+.1f}] | {row['n']} |")
    lines.extend(["", "## 预先固定的判定", "",
                  "随机或近义任一条件下，至少 2/4 小模型相对 API 多掉超过 10 pp，"
                  "且按题配对 bootstrap 95% 区间下限大于 0，则通过。",
                  "", f"**结果：{'通过' if verdict['overall_passes'] else '不通过'}。**",
                  "", "原生 gold SQL 与结果匹配银标签的分层值见 `paired_accuracy.csv`。"
                  "银标签由 DeepSeek API 产生，可能偏向该 API；分层结果不可省略。",
                  "", "所有模型使用相同 schema 提示和 temperature=0；"
                  "近义列在 SQLite 副本中真实存在且有同类型来源值。"])
    baseline_by_model = {row["model"]: row["base_accuracy"] for row in rows
                         if row["stratum"] == "all" and row["condition"] == "random20"}
    small_baselines = [value for model, value in baseline_by_model.items() if model != "api_control"]
    lines.extend(["", "## 解释限制", "",
                  f"本次四个小模型的基线准确率为 {min(small_baselines):.1%}–{max(small_baselines):.1%}，"
                  "绝对掉点受到地板效应限制。预设门槛不通过表示本次重试未验证原假设；"
                  "不能据此推断小模型不受无关列或近义列干扰。", "",
                  "最终表列提示应经 SQLite 编译时 READ 依赖核验；有表但不引用具体列的查询"
                  "仍需在提示中保留表名。"])
    (args.output_dir / "spider_sqlite_execution_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"common_n": len(common), "verdict": verdict}, ensure_ascii=False))


if __name__ == "__main__":
    main()
