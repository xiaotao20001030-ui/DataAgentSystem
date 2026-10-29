#!/usr/bin/env python3
"""Score each completed model and report equal-budget FK expansion effects."""

import argparse
import csv
import json
import subprocess
import time
from pathlib import Path

import numpy as np


MODELS = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b", "api_control")
BUDGETS = (110, 130, 200)
EXPECTED = 500 * 2 * len(BUDGETS)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def count_lines(path):
    if not path.exists():
        return 0
    with path.open("rb") as stream:
        return sum(1 for _ in stream)


def process_running(model):
    lines = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, check=True).stdout.splitlines()
    return any(
        "generate_budget_predictions.py" in line and f"--model-key {model}" in line
        for line in lines
    )


def start_scoring(args, model):
    command = [
        str(args.python), str(args.model_eval_root / "score_predictions_resumable.py"),
        "--predictions", str(args.run_root / "predictions" / f"{model}.jsonl"),
        "--variants", str(args.run_root / "variants/budget_variants.jsonl"),
        "--data-root", str(args.data_root),
        "--output-dir", str(args.run_root / "scores"),
        "--timeout-seconds", "120", "--progress-every", "100",
    ]
    log = (args.run_root / "logs" / f"score_{model}.log").open("a", encoding="utf-8")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    print(f"{model}: scoring pid={process.pid}", flush=True)
    return process, log


def wait_and_score(args):
    started = {}
    complete = set()
    deadline = time.monotonic() + args.timeout_hours * 3600
    while len(complete) < len(MODELS):
        for model in MODELS:
            if model in complete:
                continue
            if model in started:
                process, log = started[model]
                result = process.poll()
                if result is None:
                    continue
                log.close()
                if result != 0:
                    raise RuntimeError(f"Scoring failed for {model}: exit {result}; see logs/score_{model}.log")
                count = count_lines(args.run_root / "scores" / f"{model}.jsonl")
                if count != EXPECTED:
                    raise RuntimeError(f"Scoring incomplete for {model}: {count}/{EXPECTED}")
                complete.add(model)
                print(f"{model}: scoring complete", flush=True)
                continue
            count = count_lines(args.run_root / "predictions" / f"{model}.jsonl")
            if count == EXPECTED:
                started[model] = start_scoring(args, model)
            elif count > EXPECTED:
                raise RuntimeError(f"Too many predictions for {model}: {count}")
            elif not process_running(model):
                raise RuntimeError(f"Prediction stopped early for {model}: {count}/{EXPECTED}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Exceeded {args.timeout_hours} hours waiting for scoring")
        if len(complete) < len(MODELS):
            time.sleep(60)


def analyze(args):
    selection = read_jsonl(args.run_root / "variants/selection_metrics.jsonl")
    metrics = json.loads((args.run_root / "variants/summary.json").read_text(encoding="utf-8"))
    by_selection = {(row["question_id"], row["family"]): row for row in selection}
    rng = np.random.default_rng(20261028)
    output = {"retrieval_summary": metrics["by_family"], "models": {}}
    lines = [
        "# BIRD Mini-Dev：BGE 同 token 预算下的外键一跳与 SQL 执行准确率",
        "",
        "500 题均使用同一份 `BAAI/bge-base-en-v1.5` 排名。按 Qwen3-0.6B tokenizer 对实际放入提示的 schema 文本计数，每题各方案在 110、130、200 token 上限内选择能容纳的最大检索前缀。外键方案仅从种子列沿声明外键加入对端列一跳，不用 gold 指导选择。两组使用同一问题、evidence、生成参数和 SQLite 执行评分器。",
        "",
        "表中 token 为实际平均使用量，准确率及差值只在两组都可评分的同题样本上计算；SQL 执行失败计错，gold 评分异常剔除。95% 区间是按题配对 bootstrap。正的差值表示外键一跳更好。",
        "",
        "| 模型 | 预算 | 普通 top-k token | 外键一跳 token | 配对题数 | 普通执行准确率 | 一跳执行准确率 | 一跳增益 pp | 95% CI pp |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    csv_rows = []
    for model in MODELS:
        rows = read_jsonl(args.run_root / "scores" / f"{model}.jsonl")
        indexed = {(row["question_id"], row["family"]): row for row in rows}
        model_results = {}
        for budget in BUDGETS:
            plain_family = f"plain_budget_{budget}"
            fk_family = f"fk1_budget_{budget}"
            paired = []
            for qid in {row["question_id"] for row in selection}:
                plain = indexed.get((qid, plain_family))
                fk = indexed.get((qid, fk_family))
                if plain and fk and plain["evaluation_status"] != "evaluation_error" and fk["evaluation_status"] != "evaluation_error":
                    paired.append((qid, plain, fk))
            if not paired:
                raise RuntimeError(f"No scored pairs: {model} budget {budget}")
            plain_binary = np.array([int(bool(p["correct"])) for _, p, _ in paired], dtype=float)
            fk_binary = np.array([int(bool(f["correct"])) for _, _, f in paired], dtype=float)
            differences = fk_binary - plain_binary
            samples = rng.integers(0, len(paired), size=(10000, len(paired)))
            ci = np.quantile(differences[samples].mean(axis=1) * 100, [0.025, 0.975])
            plain_tokens = metrics["by_family"][plain_family]["mean_schema_tokens"]
            fk_tokens = metrics["by_family"][fk_family]["mean_schema_tokens"]
            result = {
                "paired_n": len(paired),
                "plain_correct": int(plain_binary.sum()),
                "fk1_correct": int(fk_binary.sum()),
                "plain_accuracy": float(plain_binary.mean()),
                "fk1_accuracy": float(fk_binary.mean()),
                "fk1_gain_pp": float(differences.mean() * 100),
                "ci95_low_pp": float(ci[0]), "ci95_high_pp": float(ci[1]),
                "fk1_wins": int((differences > 0).sum()),
                "fk1_losses": int((differences < 0).sum()),
                "plain_mean_schema_tokens": plain_tokens,
                "fk1_mean_schema_tokens": fk_tokens,
                "plain_gold_column_recall": metrics["by_family"][plain_family]["gold_column_recall"],
                "fk1_gold_column_recall": metrics["by_family"][fk_family]["gold_column_recall"],
                "plain_bridge_fk_recall": metrics["by_family"][plain_family]["bridge_fk_recall"],
                "fk1_bridge_fk_recall": metrics["by_family"][fk_family]["bridge_fk_recall"],
            }
            model_results[str(budget)] = result
            lines.append(
                f"| {model} | {budget} | {plain_tokens:.1f} | {fk_tokens:.1f} | {len(paired)} | "
                f"{result['plain_accuracy']:.1%} | {result['fk1_accuracy']:.1%} | {result['fk1_gain_pp']:+.1f} | "
                f"[{ci[0]:+.1f}, {ci[1]:+.1f}] |"
            )
            csv_rows.append({"model": model, "budget": budget, **result})
        output["models"][model] = model_results
    lines.extend([
        "",
        "## 检索与预算检查",
        "",
        "| 预算 | 普通平均 k | 一跳种子平均 k | 普通 gold 列召回 | 一跳 gold 列召回 | 普通桥接/FK 召回 | 一跳桥接/FK 召回 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for budget in BUDGETS:
        plain = metrics["by_family"][f"plain_budget_{budget}"]
        fk = metrics["by_family"][f"fk1_budget_{budget}"]
        lines.append(
            f"| {budget} | {plain['mean_seed_k']:.1f} | {fk['mean_seed_k']:.1f} | "
            f"{plain['gold_column_recall']:.1%} | {fk['gold_column_recall']:.1%} | "
            f"{plain['bridge_fk_recall']:.1%} | {fk['bridge_fk_recall']:.1%} |"
        )
    lines.extend([
        "",
        "## 解释范围",
        "",
        "token 上限由固定的 Qwen3-0.6B tokenizer 计算，其他生成模型与 API 的内部 token 数可能不同；这里比较的是相同输入文本与相同公共预算。列有离散长度，实际使用 token 不一定逐题完全相等，因此同时报告了两组平均实际 token。执行准确率来自项目同一个只读 SQLite 结果评分器，超时设为 120 秒。",
        "",
        "是否能扩展到其他检索器、其他数据集，以及更严格的等实际 token 匹配，需另做验证。",
        "",
        "## 复现",
        "",
        "- `input/bge_rankings.jsonl`：固定的 500 题 BGE 排名。",
        "- `variants/budget_variants.jsonl`：3000 条同预算变体。",
        "- `variants/selection_metrics.jsonl`：每题实际 token、k 和召回。",
        "- `predictions/`、`scores/`：逐题 SQL 与执行评分。",
        "- `scripts/`、`logs/`：生成、续跑与日志。",
        "",
    ])
    report_dir = args.run_root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "equal_budget_execution_report.md").write_text("\n".join(lines), encoding="utf-8")
    (report_dir / "equal_budget_execution_summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (report_dir / "paired_accuracy.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--model-eval-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--timeout-hours", type=float, default=24)
    args = parser.parse_args()
    wait_and_score(args)
    analyze(args)
    (args.run_root / "COMPLETE").write_text("completed\n", encoding="utf-8")
    print("complete", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import sys
        import traceback
        root = None
        for index, value in enumerate(sys.argv):
            if value == "--run-root" and index + 1 < len(sys.argv):
                root = Path(sys.argv[index + 1])
                break
        if root is not None:
            (root / "FAILED").write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
        traceback.print_exc()
        raise
