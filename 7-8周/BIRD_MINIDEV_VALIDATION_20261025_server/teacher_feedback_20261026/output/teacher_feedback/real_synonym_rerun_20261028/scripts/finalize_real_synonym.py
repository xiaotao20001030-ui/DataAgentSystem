#!/usr/bin/env python3
"""Wait for synonym predictions, score them, and write a compact report."""

import argparse
import csv
import json
import random
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


MODELS = (
    "qwen3_0_6b",
    "qwen3_1_7b",
    "qwen3_4b",
    "qwen2_5_coder_1_5b",
    "api_control",
)
LEVELS = (5, 10, 20, 50)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in records),
        encoding="utf-8",
    )


def count_lines(path):
    with path.open("rb") as stream:
        return sum(1 for _ in stream)


def prediction_process_running(model):
    output = subprocess.run(
        ["ps", "-eo", "args"], capture_output=True, text=True, check=True
    ).stdout
    return any(
        "model_eval/generate_predictions.py" in line and f"--model-key {model}" in line
        for line in output.splitlines()
    )


def wait_for_predictions(run_root, expected, timeout_hours):
    deadline = time.monotonic() + timeout_hours * 3600
    while True:
        counts = {model: count_lines(run_root / "predictions" / f"{model}.jsonl") for model in MODELS}
        print("prediction counts", counts, flush=True)
        if all(value == expected for value in counts.values()):
            return
        if any(value > expected for value in counts.values()):
            raise RuntimeError(f"More predictions than expected: {counts}")
        incomplete = [model for model, value in counts.items() if value < expected]
        stopped = [model for model in incomplete if not prediction_process_running(model)]
        if stopped:
            raise RuntimeError(f"Prediction stopped before completion: {stopped}; counts={counts}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Prediction deadline exceeded: {counts}")
        time.sleep(60)


def prepare_baseline(run_root, source_root, model_root):
    base_source = read_jsonl(source_root / "perturbations/output/mini_dev_perturbations.jsonl")
    bases = [row for row in base_source if row["perturbation"]["family"] == "base"]
    if len(bases) != 500:
        raise RuntimeError(f"Expected 500 base variants, got {len(bases)}")
    extra = read_jsonl(run_root / "variants/all_real_synonym_variants.jsonl")
    write_jsonl(run_root / "variants/evaluation_variants.jsonl", bases + extra)
    for model in MODELS:
        output = run_root / "predictions" / f"{model}.jsonl"
        current = read_jsonl(output)
        existing = {row["variant_id"] for row in current}
        original = read_jsonl(model_root / "predictions" / f"{model}.jsonl")
        baseline = [row for row in original if row["family"] == "base"]
        if len(baseline) != 500:
            raise RuntimeError(f"Expected 500 baseline predictions for {model}")
        additions = [row for row in baseline if row["variant_id"] not in existing]
        with output.open("a", encoding="utf-8") as stream:
            for row in additions:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"{model}: appended {len(additions)} baseline predictions", flush=True)


def score_all(run_root, data_root, model_root, python):
    def score_one(model):
        command = [
            str(python),
            str(model_root / "score_predictions_resumable.py"),
            "--predictions", str(run_root / "predictions" / f"{model}.jsonl"),
            "--variants", str(run_root / "variants/evaluation_variants.jsonl"),
            "--data-root", str(data_root),
            "--output-dir", str(run_root / "scores"),
            "--timeout-seconds", "120",
            "--progress-every", "50",
        ]
        with (run_root / "logs" / f"score_{model}.log").open("a", encoding="utf-8") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        print(f"{model}: scored", flush=True)

    with ThreadPoolExecutor(max_workers=len(MODELS)) as pool:
        list(pool.map(score_one, MODELS))


def valid(row):
    return row["evaluation_status"] != "evaluation_error"


def make_report(run_root):
    variants = {
        row["variant_id"]: row
        for row in read_jsonl(run_root / "variants/evaluation_variants.jsonl")
    }
    generated = json.loads((run_root / "variants/summary.json").read_text(encoding="utf-8"))
    scores = {model: read_jsonl(run_root / "scores" / f"{model}.jsonl") for model in MODELS}
    all_results = {}
    lines = [
        "# BIRD Mini-Dev 真实近名列扰动重跑（2026-10-28）",
        "",
        "## 实验定义与修复",
        "",
        "从每题原数据库的真实 SQLite 列中选择干扰项；剔除 gold 所需列，按列名 token Jaccard 或字符相似度（阈值 0.25）排序，同类型列加 0.03 分。每个加入的 `table.column` 均由 SQLite PRAGMA 验证存在；gold SQL 在只读数据库上通过 `EXPLAIN QUERY PLAN` 编译。数据库没有被改动。",
        "",
        "这是一组**真实列的近名干扰**，列名相似不保证语义同义，因此不能单独解释为‘真实语义近义列’实验。",
        "",
        "| 加入真实干扰列 | 可构造题数 | 排除题数 |",
        "|---:|---:|---:|",
    ]
    for level in LEVELS:
        item = generated["levels"][str(level)]
        lines.append(f"| {level} | {item['generated']} | {item['excluded']} |")
    total_added = sum(level * generated["levels"][str(level)]["generated"] for level in LEVELS)
    lines.extend([
        "",
        f"四档共加入 {total_added} 次真实列。各档可构造题目不同，跨档趋势应优先看下方共同的 248 题。",
        "",
        "## 同题配对执行准确率",
        "",
        "执行比较沿用项目的 SQLite 结果比较器，查询超时 120 秒；评分异常从分母排除，SQL 执行失败计为错误。每档基线只取该档可构造的同一批题。下降同时给出百分点和相对百分比。",
        "",
        "| 模型 | 干扰列数 | 有效配对 n | 基线正确率 | 扰动正确率 | 下降 pp | 相对下降 | 评分异常 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for model in MODELS:
        rows = scores[model]
        by_family = {}
        for row in rows:
            by_family.setdefault(row["family"], {})[row["question_id"]] = row
        base = by_family["base"]
        model_result = {}
        for level in LEVELS:
            family = f"add_real_synonym_{level}"
            perturbed = by_family.get(family, {})
            paired = [(base[qid], row) for qid, row in perturbed.items() if qid in base and valid(base[qid]) and valid(row)]
            base_acc = sum(bool(left["correct"]) for left, _ in paired) / len(paired) if paired else None
            pert_acc = sum(bool(right["correct"]) for _, right in paired) / len(paired) if paired else None
            excluded = len(perturbed) - len(paired)
            if paired:
                drop_pp = (base_acc - pert_acc) * 100
                rel_drop = drop_pp / (base_acc * 100) * 100 if base_acc else None
                line = f"| {model} | {level} | {len(paired)} | {base_acc:.1%} | {pert_acc:.1%} | {drop_pp:+.1f} | {rel_drop:.1f}% | {excluded} |" if rel_drop is not None else f"| {model} | {level} | {len(paired)} | {base_acc:.1%} | {pert_acc:.1%} | {drop_pp:+.1f} | — | {excluded} |"
            else:
                drop_pp = rel_drop = None
                line = f"| {model} | {level} | — | — | — | — | — | — |"
            lines.append(line)
            model_result[str(level)] = {
                "paired_n": len(paired), "baseline_accuracy": base_acc,
                "perturbed_accuracy": pert_acc, "drop_pp": drop_pp,
                "relative_drop_pct": rel_drop, "excluded_evaluation_errors": excluded,
            }
        all_results[model] = model_result

    common_ids = {
        row["question_id"]
        for row in variants.values()
        if row["perturbation"]["family"] == "add_real_synonym" and row["perturbation"]["level"] == 50
    }
    lines.extend([
        "",
        "## 固定 248 题的剂量曲线",
        "",
        "下表把基线和四档限制在均可构造 50 个干扰列的同一组题；个别评分异常仍从该单元格分母排除。",
        "",
        "| 模型 | 基线 | +5 | +10 | +20 | +50 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    fixed = {}
    for model in MODELS:
        by_family = {}
        for row in scores[model]:
            by_family.setdefault(row["family"], {})[row["question_id"]] = row
        cells = []
        model_fixed = {}
        for family in ("base", *(f"add_real_synonym_{level}" for level in LEVELS)):
            chosen = [by_family.get(family, {}).get(qid) for qid in common_ids]
            chosen = [row for row in chosen if row and valid(row)]
            if chosen:
                accuracy = sum(bool(row["correct"]) for row in chosen) / len(chosen)
                cells.append(f"{accuracy:.1%} ({len(chosen)})")
            else:
                accuracy = None
                cells.append("—")
            model_fixed[family] = {"accuracy": accuracy, "n": len(chosen)}
        lines.append("| " + model + " | " + " | ".join(cells) + " |")
        fixed[model] = model_fixed

    api_wrong = [
        row for row in scores["api_control"]
        if row["family"] == "add_real_synonym_20" and row["evaluation_status"] == "incorrect"
    ]
    selected = random.Random(20261028).sample(api_wrong, min(30, len(api_wrong)))
    audit_path = run_root / "reports" / "api_synonym20_wrong_30_review.csv"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "question_id", "db_id", "question", "gold_columns", "added_real_columns",
            "gold_sql", "predicted_sql", "prediction_error", "human_reason", "human_notes",
        ])
        writer.writeheader()
        for row in selected:
            variant = variants[row["variant_id"]]
            writer.writerow({
                "question_id": row["question_id"],
                "db_id": row["db_id"],
                "question": variant["question"],
                "gold_columns": "; ".join(variant["gold_columns"]),
                "added_real_columns": "; ".join(item["id"] for item in variant["perturbation"]["added"]),
                "gold_sql": row["gold_sql"],
                "predicted_sql": row["predicted_sql"],
                "prediction_error": row.get("prediction_error") or "",
                "human_reason": "",
                "human_notes": "",
            })
    lines.extend([
        "",
        "## 人工复核与解释边界",
        "",
        f"`reports/api_synonym20_wrong_30_review.csv` 固定随机种子抽取 {len(selected)} 条 API 错误，提供题目、gold、预测 SQL 和真实干扰列，留空人工原因栏。该表是待人工判读的样本清单，不能代替人工结论。",
        "",
        "本实验修复了‘提示列不存在于 SQLite’的构造错误；仍需人工确认近名列的语义关系，以及 gold 本身是否有口径争议。",
        "",
        "## 复现文件",
        "",
        "- `variants/summary.json`：四档可构造性与哈希。",
        "- `variants/evaluation_variants.jsonl`：500 条基线和四档真实列变体。",
        "- `predictions/`、`scores/`：五个模型的逐题预测与执行评分。",
        "- `logs/`：模型运行与评分日志。",
        "",
    ])
    (run_root / "reports" / "real_synonym_rerun_report.md").write_text("\n".join(lines), encoding="utf-8")
    (run_root / "reports" / "real_synonym_rerun_summary.json").write_text(
        json.dumps({"paired_results": all_results, "fixed_248": fixed, "api_review_count": len(selected)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--timeout-hours", type=float, default=12)
    args = parser.parse_args()
    args.run_root.mkdir(parents=True, exist_ok=True)
    generated = json.loads((args.run_root / "variants/summary.json").read_text(encoding="utf-8"))
    expected = sum(generated["levels"][str(level)]["generated"] for level in LEVELS)
    wait_for_predictions(args.run_root, expected, args.timeout_hours)
    prepare_baseline(args.run_root, args.source_root, args.model_root)
    score_all(args.run_root, args.data_root, args.model_root, args.python)
    make_report(args.run_root)
    (args.run_root / "COMPLETE").write_text("completed\n", encoding="utf-8")
    print("complete", flush=True)


if __name__ == "__main__":
    main()
