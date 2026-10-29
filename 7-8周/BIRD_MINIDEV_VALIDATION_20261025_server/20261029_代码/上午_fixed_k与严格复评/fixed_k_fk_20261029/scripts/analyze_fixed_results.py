#!/usr/bin/env python3
"""Analyze all five completed fixed-k BIRD score files without generation calls.

Expected layout: RUN/variants/{summary.json,selection_metrics.jsonl,
fixed_variants.jsonl}, RUN/scores/MODEL.jsonl. Writes RUN/reports/results.json
and fixed_k_execution_report.md. Each model must have all 2,000 unique rows.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


MODELS = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b", "api_control")
TARGETS = (130, 200)
FAMILIES = tuple(f"{method}_fixed_{target}" for target in TARGETS for method in ("plain", "fk1"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index_rows(rows, label):
    indexed = {}
    variant_ids = set()
    for row in rows:
        key = (row["question_id"], row["family"])
        if key in indexed or row["variant_id"] in variant_ids:
            raise ValueError(f"Duplicate question/family or variant ID in {label}: {key}")
        if row["family"] not in FAMILIES:
            raise ValueError(f"Unexpected family in {label}: {row['family']}")
        indexed[key] = row
        variant_ids.add(row["variant_id"])
    return indexed


def distribution(values):
    values = np.asarray(values, dtype=float)
    return {"mean": float(values.mean()), "min": float(values.min()), "p05": float(np.quantile(values, .05)),
            "p25": float(np.quantile(values, .25)), "median": float(np.median(values)),
            "p75": float(np.quantile(values, .75)), "p95": float(np.quantile(values, .95)), "max": float(values.max())}


def bootstrap(plain, fk, seed, iterations):
    """Resample the same question indices for both arms; percentile intervals."""
    rng = np.random.default_rng(seed)
    plain_means, fk_means, gains = [], [], []
    for start in range(0, iterations, 1000):
        indices = rng.integers(0, len(plain), size=(min(1000, iterations - start), len(plain)))
        p = plain[indices].mean(axis=1)
        f = fk[indices].mean(axis=1)
        plain_means.extend(p)
        fk_means.extend(f)
        gains.extend((f - p) * 100)
    return [np.quantile(values, [.025, .975]).tolist() for values in (plain_means, fk_means, gains)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--scores-dir", type=Path, help="Default: RUN/scores")
    parser.add_argument("--output-dir", type=Path, help="Default: RUN/reports")
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261029)
    args = parser.parse_args()
    if args.bootstrap_replicates < 1000:
        raise ValueError("Use at least 1,000 bootstrap replicates")
    scores_dir = args.scores_dir or args.run_root / "scores"
    output_dir = args.output_dir or args.run_root / "reports"
    variant_dir = args.run_root / "variants"
    selection_path = variant_dir / "selection_metrics.jsonl"
    summary_path = variant_dir / "summary.json"
    variants_path = variant_dir / "fixed_variants.jsonl"
    metrics = json.loads(summary_path.read_text(encoding="utf-8"))
    selection = read_jsonl(selection_path)
    by_selection = index_rows(selection, "selection metrics")
    # Preserve the cohort ordering in the variant file for reproducible resampling.
    qids = list(dict.fromkeys(row["question_id"] for row in selection))
    expected_keys = {(qid, family) for qid in qids for family in FAMILIES}
    if len(qids) != 500 or len(selection) != 2000 or set(by_selection) != expected_keys:
        raise ValueError("Selection metrics must have exactly four variants for the same 500 questions")
    if metrics.get("question_count") != 500 or metrics.get("variant_count") != 2000:
        raise ValueError("Summary does not describe the required 500-question/2,000-variant experiment")
    for path, key in ((selection_path, "selection_metrics_sha256"), (variants_path, "variants_sha256")):
        if metrics.get(key) != sha256(path):
            raise ValueError(f"Provenance mismatch: {path.name}")
    fixed_ks = metrics["fixed_ks"]
    if fixed_ks["130"] != {"plain": 12, "fk1": 10}:
        raise ValueError("The teacher-prespecified 130 pair must remain plain12 / FK10")
    for target in TARGETS:
        for method in ("plain", "fk1"):
            family = f"{method}_fixed_{target}"
            rows = [row for row in selection if row["family"] == family]
            if {row["retrieval_k"] for row in rows} != {fixed_ks[str(target)][method]}:
                raise ValueError(f"k is not fixed for {family}")
            observed_mean = float(np.mean([row["token_count"] for row in rows]))
            if abs(observed_mean - metrics["by_family"][family]["mean_schema_tokens"]) > 1e-9:
                raise ValueError(f"Token summary mismatch for {family}")

    output = {
        "experiment": "BIRD Mini-Dev fixed-k plain versus one-hop FK", "question_count": 500,
        "target_labels": list(TARGETS), "fixed_ks": fixed_ks,
        "retrieval_summary": metrics["by_family"], "models": {},
        "token_target_interpretation": "130/200 are nominal mean-token targets, not per-question token caps; report actual token differences",
        "fk1_minus_plain_token_distribution": metrics["fk1_minus_plain_token_distribution"],
        "selection_protocol": {key: value for key, value in metrics["protocol"].items() if key not in {"candidate_pairs", "candidate_token_means"}},
        "bootstrap": {"method": "Paired question-level percentile bootstrap", "replicates": args.bootstrap_replicates,
                      "confidence": .95, "seed": args.seed, "seed_derivation": "SeedSequence([seed, model_index, target_label])",
                      "denominator": "Only same-question pairs for which neither evaluation_status is evaluation_error; prediction failures are incorrect",
                      "multiplicity": "Intervals are per comparison; no multiple-comparison correction", "unit": "question, not database"},
        "provenance": {"analyzer_sha256": sha256(Path(__file__)), "summary_sha256": sha256(summary_path),
                       "variants_sha256": sha256(variants_path), "selection_metrics_sha256": sha256(selection_path),
                       "rankings_sha256": metrics["rankings_sha256"], "base_variants_sha256": metrics["base_variants_sha256"],
                       "score_files": {}},
    }
    versions = set()
    for model_index, model in enumerate(MODELS):
        score_path = scores_dir / f"{model}.jsonl"
        rows = read_jsonl(score_path)
        indexed = index_rows(rows, model)
        if len(rows) != 2000 or set(indexed) != expected_keys:
            raise ValueError(f"Incomplete or mismatched score cohort for {model}: expected all 2,000 rows, found {len(rows)}")
        for key, row in indexed.items():
            source = by_selection[key]
            if any(row.get(field) != source[field] for field in ("variant_id", "db_id")) or row.get("model_key") != model:
                raise ValueError(f"Score identity mismatch for {model}: {key}")
            status = row["evaluation_status"]
            if status not in {"correct", "incorrect", "evaluation_error"}:
                raise ValueError(f"Unknown evaluation status for {model}: {status}")
            if row["correct"] not in (True, False, 0, 1) or isinstance(row["correct"], str):
                raise ValueError(f"Non-binary correct field for {model}: {key}")
            if bool(row["correct"]) != (status == "correct"):
                raise ValueError(f"Contradictory correctness/status for {model}: {key}")
            versions.add(row.get("scoring_version", "unspecified"))
        score_provenance = {"path": str(score_path), "sha256": sha256(score_path), "rows": len(rows)}
        sidecar = scores_dir / f"{model}.summary.json"
        if sidecar.exists():
            score_provenance["scorer_summary"] = json.loads(sidecar.read_text(encoding="utf-8"))
            score_provenance["scorer_summary_sha256"] = sha256(sidecar)
        output["provenance"]["score_files"][model] = score_provenance
        model_results = {}
        for target in TARGETS:
            plain_family, fk_family = f"plain_fixed_{target}", f"fk1_fixed_{target}"
            paired_qids = [qid for qid in qids if all(indexed[(qid, family)]["evaluation_status"] != "evaluation_error" for family in (plain_family, fk_family))]
            if not paired_qids:
                raise ValueError(f"No scorable pairs for {model}, {target}")
            plain = np.array([int(indexed[(qid, plain_family)]["correct"]) for qid in paired_qids], dtype=float)
            fk = np.array([int(indexed[(qid, fk_family)]["correct"]) for qid in paired_qids], dtype=float)
            differences = fk - plain
            p_ci, f_ci, gain_ci = bootstrap(plain, fk, np.random.SeedSequence([args.seed, model_index, target]), args.bootstrap_replicates)
            p_tokens = np.array([by_selection[(qid, plain_family)]["token_count"] for qid in paired_qids])
            f_tokens = np.array([by_selection[(qid, fk_family)]["token_count"] for qid in paired_qids])
            p_summary, f_summary = metrics["by_family"][plain_family], metrics["by_family"][fk_family]
            result = {
                "paired_n": len(paired_qids), "excluded_pairs": 500 - len(paired_qids),
                "excluded_question_ids": [qid for qid in qids if qid not in set(paired_qids)],
                "plain_evaluation_errors": sum(indexed[(qid, plain_family)]["evaluation_status"] == "evaluation_error" for qid in qids),
                "fk1_evaluation_errors": sum(indexed[(qid, fk_family)]["evaluation_status"] == "evaluation_error" for qid in qids),
                "plain_correct": int(plain.sum()), "fk1_correct": int(fk.sum()),
                "plain_accuracy": float(plain.mean()), "fk1_accuracy": float(fk.mean()),
                "plain_accuracy_ci95": p_ci, "fk1_accuracy_ci95": f_ci,
                "fk1_gain_pp": float(differences.mean() * 100), "ci95_low_pp": gain_ci[0], "ci95_high_pp": gain_ci[1],
                "fk1_wins": int((differences > 0).sum()), "fk1_losses": int((differences < 0).sum()),
                "both_correct": int(((plain == 1) & (fk == 1)).sum()), "both_incorrect": int(((plain == 0) & (fk == 0)).sum()),
                "plain_fixed_k": fixed_ks[str(target)]["plain"], "fk1_fixed_k": fixed_ks[str(target)]["fk1"],
                "plain_mean_schema_tokens": p_summary["mean_schema_tokens"], "fk1_mean_schema_tokens": f_summary["mean_schema_tokens"],
                "fk1_minus_plain_mean_schema_tokens": f_summary["mean_schema_tokens"] - p_summary["mean_schema_tokens"],
                "paired_plain_mean_schema_tokens": float(p_tokens.mean()), "paired_fk1_mean_schema_tokens": float(f_tokens.mean()),
                "paired_fk1_minus_plain_token_distribution": distribution(f_tokens - p_tokens),
                "plain_gold_column_recall": p_summary["gold_column_recall"], "fk1_gold_column_recall": f_summary["gold_column_recall"],
                "plain_bridge_fk_recall": p_summary["bridge_fk_recall"], "fk1_bridge_fk_recall": f_summary["bridge_fk_recall"],
            }
            model_results[str(target)] = result
        output["models"][model] = model_results
    if len(versions) != 1:
        raise ValueError(f"Mixed scorer versions across the experiment: {versions}")
    output["scoring_versions"] = list(versions)
    official = versions == {2} and all(item.get("scorer_summary", {}).get("scoring") == "official_mini_dev_set_equality" for item in output["provenance"]["score_files"].values())
    output["scoring_semantics"] = "official_mini_dev_set_equality" if official else "Supplied scores; consult score file provenance for scorer semantics"
    lines = [
        "# BIRD Mini-Dev：固定 k 的普通检索与外键一跳实验", "",
        "500 题共享同一份 BGE 排名。130 组固定为普通 top-12 对比 top-10 加声明外键一跳；200 组仅根据全体 schema 的 token 统计选定一个固定整数 k 组合。每组的 k 对所有题保持不变，选取过程不读取模型答案、执行成绩或 gold 覆盖率。",
        "", "130/200 是名义长度目标，不是逐题 token 上限。下表明确列出实际 token 分布与两方案差值；实验不能解释为逐题严格等 token 的效果。", "",
        "| 名义目标 | 普通固定 k | 一跳固定种子 k | 普通实际平均 token | 一跳实际平均 token | 一跳−普通 token | 普通 P05–P95 | 一跳 P05–P95 |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for target in TARGETS:
        p, f = metrics["by_family"][f"plain_fixed_{target}"], metrics["by_family"][f"fk1_fixed_{target}"]
        lines.append(f"| {target} | {fixed_ks[str(target)]['plain']} | {fixed_ks[str(target)]['fk1']} | {p['mean_schema_tokens']:.2f} | {f['mean_schema_tokens']:.2f} | {f['mean_schema_tokens']-p['mean_schema_tokens']:+.2f} | {p['schema_tokens']['p05']:.1f}–{p['schema_tokens']['p95']:.1f} | {f['schema_tokens']['p05']:.1f}–{f['schema_tokens']['p95']:.1f} |")
    chosen = metrics["protocol"]["chosen_200"]
    lines.extend([
        "", f"200 组选取规则：`{metrics['protocol']['criterion']}`；候选 k 范围为 1–{metrics['protocol']['candidate_k_domain'][1]}，最终固定普通 k={chosen['plain_k']}、一跳种子 k={chosen['fk1_k']}，目标函数值 {chosen['objective']:.4f}。完整候选表、确定性平局规则与输入 SHA-256 见 `variants/summary.json`。", "",
        "## 配对执行准确率", "",
        "每个比较只包含两方案都能评分的同一道题。预测 SQL 失败或生成失败计错；gold SQL 无法评分导致的 evaluation_error 按题成对剔除。正增益表示外键一跳较好。",
        "", "| 模型 | 名义目标 | 普通 k / 一跳 k | 配对题数 | 剔除 | 普通准确率 | 一跳准确率 | 一跳增益 pp | 配对 bootstrap 95% CI pp | 一跳赢 / 输 |",
        "|---|---:|---|---:|---:|---:|---:|---:|---|---|",
    ])
    for model in MODELS:
        for target in TARGETS:
            r = output["models"][model][str(target)]
            lines.append(f"| {model} | {target} | {r['plain_fixed_k']} / {r['fk1_fixed_k']} | {r['paired_n']} | {r['excluded_pairs']} | {r['plain_accuracy']:.1%} | {r['fk1_accuracy']:.1%} | {r['fk1_gain_pp']:+.1f} | [{r['ci95_low_pp']:+.1f}, {r['ci95_high_pp']:+.1f}] | {r['fk1_wins']} / {r['fk1_losses']} |")
    lines.extend([
        "", f"区间采用 {args.bootstrap_replicates:,} 次按题配对重采样，随机种子 {args.seed}；同次抽样同时计算两方案准确率与差值。各准确率区间、成对保留样本的实际平均 token、token 差分布、剔除题号均写入 `results.json`。区间未做多重比较校正，也未按数据库聚类。", "",
        "## 解释与复现", "",
        f"- 评分口径：`{output['scoring_semantics']}`；scoring_version={next(iter(versions))}。",
        f"- 公共计数 tokenizer：`{metrics['tokenizer']}`；只计算实际注入提示的 schema_text，不含问题、evidence 或提示框架。其他模型的内部 token 数可能不同。",
        "- 外键扩展只从原始种子列走一跳，加入声明外键的另一端列，去重后按列名排序；不递归扩展。",
        "- 200 组的 k 使用当前 500 题输入长度校准；这不是基于成绩调参，也不是独立留出集性能估计。",
        "- `variants/fixed_variants.jsonl`：固定 2,000 条变体；`variants/selection_metrics.jsonl`：逐题 token、k 和事后覆盖率；`scores/`：五模型各 2,000 条执行评分。",
        "- 生成器与分析器不调用模型服务。`results.json` 保留输入与评分文件 SHA-256、评分器摘要、固定 k 和完整统计结果。", "",
    ])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "fixed_k_execution_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"models": len(MODELS), "comparisons": len(MODELS) * len(TARGETS), "output_dir": str(output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
