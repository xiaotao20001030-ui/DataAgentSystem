#!/usr/bin/env python3
"""Summarise strict-vs-permissive rescoring of hidden-schema predictions."""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

MODELS = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b", "api_control")
NAMES = {
    "qwen3_0_6b": "Qwen3 0.6B",
    "qwen3_1_7b": "Qwen3 1.7B",
    "qwen3_4b": "Qwen3 4B",
    "qwen2_5_coder_1_5b": "Qwen2.5 Coder 1.5B",
    "api_control": "API 对照 (deepseek-chat)",
}
FAMILIES = {"missing_bridge_table": "隐藏桥接表", "missing_fk_column": "隐藏外键列"}


def main():
    root = Path(sys.argv[1])
    data = defaultdict(dict)
    for model in MODELS:
        path = root / f"strict_{model}.jsonl"
        if not path.is_file():
            raise SystemExit(f"missing {path}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for family in FAMILIES:
            sub = [r for r in rows if r["family"] == family]
            scoreable = [r for r in sub if r["status"] != "gold_unscoreable"]
            strict = sum(1 for r in scoreable if r["strict_correct"])
            permissive = sum(1 for r in scoreable if r["permissive_correct"])
            status = Counter(r["status"] for r in sub)
            data[family][model] = {
                "n_total": len(sub),
                "n_scoreable": len(scoreable),
                "strict_correct": strict,
                "permissive_correct": permissive,
                "strict_accuracy": strict / len(scoreable) if scoreable else None,
                "permissive_accuracy": permissive / len(scoreable) if scoreable else None,
                "status": dict(status),
            }

    summary = {"families": data, "definition": {
        "strict": "execute with SQLite authorizer allowing READ only on schema_columns shown in the prompt; any other table/column read raises and counts as incorrect",
        "permissive": "same prediction executed without the authorizer (original scoring basis)",
        "excluded": "gold SQL unscoreable under the shared timeout is removed pairwise; prediction errors count as incorrect",
    }}
    (root / "strict_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 隐藏 schema 条件的严格口径复评（不重跑模型）", "",
             "同一批已保存的预测，在评分侧加 SQLite authorizer：只允许读取提示 schema 里真实出现的表和列，"
             "越界读取（隐藏桥接表、隐藏外键列、其他未展示的表列）直接判错。", "",
             "定义：严格 = authorizer 放行后执行并与 gold 结果集一致；宽松 = 不加约束执行（原评分口径）。"
             "gold 在超时内不可执行的题成对剔除；预测执行失败计错。", ""]
    for family, title in FAMILIES.items():
        rows = data[family]
        if not rows:
            continue
        lines += [f"## {title}（{family}）", "",
                  "| 模型 | n | 宽松 EX | 严格 EX | 严格-宽松 pp | 越界读取 | 其他执行错误 |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for model in MODELS:
            d = rows[model]
            delta = (d["strict_accuracy"] - d["permissive_accuracy"]) * 100
            denied = d["status"].get("denied_hidden_access", 0)
            err = d["status"].get("execution_error", 0) + d["status"].get("prediction_error", 0)
            lines.append(
                f"| {NAMES[model]} | {d['n_scoreable']} | {d['permissive_accuracy']:.2%} | "
                f"{d['strict_accuracy']:.2%} | {delta:+.1f} | {denied} | {err} |"
            )
        lines.append("")
    lines += ["## 解释", "",
              "- 宽松列与此前报告的执行集合匹配率一致；严格列是同一批 SQL 在可见 schema 约束下的结果。",
              "- 两列之差就是“靠读取未提供对象才答对”的虚高部分，不需要重新生成模型输出。",
              "- 严格口径下仍答对的题，是仅用可见表列把结果算对的样本。", ""]
    (root / "strict_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
