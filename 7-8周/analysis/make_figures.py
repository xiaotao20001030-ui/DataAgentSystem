#!/usr/bin/env python3
"""Generate the four summary figures for the 7-8 week report."""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FIG_DIR = ROOT / "result" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

MODEL_LABELS = {
    "qwen3_0_6b": "Qwen3-0.6B",
    "qwen3_1_7b": "Qwen3-1.7B",
    "qwen3_4b": "Qwen3-4B",
    "qwen2_5_coder_1_5b": "Qwen2.5-Coder-1.5B",
    "api_control": "DeepSeek",
}
MODEL_ORDER = [
    "qwen3_0_6b",
    "qwen3_1_7b",
    "qwen3_4b",
    "qwen2_5_coder_1_5b",
    "api_control",
]
COLORS = {
    "qwen3_0_6b": "#4C78A8",
    "qwen3_1_7b": "#F58518",
    "qwen3_4b": "#54A24B",
    "qwen2_5_coder_1_5b": "#B279A2",
    "api_control": "#E45756",
}
BASE = {
    "qwen3_0_6b": 14.6,
    "qwen3_1_7b": 27.2,
    "qwen3_4b": 50.4,
    "qwen2_5_coder_1_5b": 26.4,
    "api_control": 68.2,
}


def setup_style():
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 150
    plt.rcParams["savefig.dpi"] = 220
    plt.rcParams["axes.spines.top"] = False
    plt.rcParams["axes.spines.right"] = False
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.25
    plt.rcParams["font.size"] = 10


def curve_panel(ax, df, perturbation, title):
    levels = [0, 5, 10, 20, 50]
    for model in MODEL_ORDER:
        rows = df[(df["model"] == model) & (df["perturbation"] == perturbation)]
        rows = rows.set_index("level").sort_index()
        values = [BASE[model]] + [rows.loc[level, "accuracy_percent"] for level in levels[1:]]
        ax.plot(
            levels,
            values,
            marker="o",
            markersize=4,
            linewidth=1.8,
            color=COLORS[model],
            label=MODEL_LABELS[model],
        )
        ax.annotate(
            f"{values[-1]:.1f}",
            (levels[-1], values[-1]),
            xytext=(4, -2),
            textcoords="offset points",
            fontsize=7,
            color=COLORS[model],
        )
    ax.set_xscale("symlog", linthresh=5)
    ax.set_xticks(levels)
    ax.set_xticklabels(["base", "5", "10", "20", "50"])
    ax.set_xlabel("新增列数")
    ax.set_ylabel("执行准确率 (%)")
    ax.set_title(title, fontsize=10.5, loc="left", fontweight="bold")
    ax.set_ylim(0, 75)


def make_fig1(df):
    fig, ax = plt.subplots(figsize=(8.4, 3.6))
    curve_panel(ax, df, "random", "随机加列：总体影响温和，但该条件同时引入了新表")
    ax.legend(
        ncol=1,
        fontsize=7.5,
        frameon=False,
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
    )
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig1_random_curve.png", bbox_inches="tight")
    plt.close(fig)


def make_fig2(df):
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8), gridspec_kw={"width_ratios": [1.05, 1]})
    curve_panel(axes[0], df, "synonym", "同名/近义加列：5 列即出现断崖")
    axes[0].legend(ncol=2, fontsize=6.8, frameon=False, loc="lower left")

    counts = [0, 2, 3, 4, 5]
    qwen = [59.30, 8.06, 10.48, 20.27, 8.82]
    deepseek = [74.42, 25.81, 16.19, 29.73, 18.24]
    x = np.arange(len(counts))
    width = 0.36
    axes[1].bar(x - width / 2, qwen, width, color=COLORS["qwen3_4b"], label="Qwen3-4B")
    axes[1].bar(x + width / 2, deepseek, width, color=COLORS["api_control"], label="DeepSeek")
    for index, value in enumerate(qwen):
        axes[1].text(index - width / 2, value + 1.5, f"{value:.1f}", ha="center", fontsize=6.5)
    for index, value in enumerate(deepseek):
        axes[1].text(index + width / 2, value + 1.5, f"{value:.1f}", ha="center", fontsize=6.5)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([str(value) for value in counts])
    axes[1].set_xlabel("同一变体内的 same_name 列数")
    axes[1].set_ylabel("执行准确率 (%)")
    axes[1].set_title("5 列条件内部：同名干扰驱动断崖", fontsize=10.5, loc="left", fontweight="bold")
    axes[1].set_ylim(0, 85)
    axes[1].legend(frameon=False, fontsize=7.5)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig2_synonym_and_same_name.png", bbox_inches="tight")
    plt.close(fig)


def make_fig3():
    data = json.loads(
        (ROOT / "BIRD_RESULTS" / "analysis" / "retrieval_matched_exact"
         / "retrieval_matched_exact.json").read_text(encoding="utf-8")
    )
    k = "10"
    categories = ["single", "multi_nonbridge", "bridge_cols", "fk_cols", "union"]
    labels = ["单表目标列", "多表非桥接", "桥接表内列", "外键/join 列", "并集"]
    values = [data["results"][k][category]["miss_rate_pct"] for category in categories]
    colors = ["#9E9E9E", "#4C78A8", "#54A24B", "#E45756", "#B279A2"]

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8), gridspec_kw={"width_ratios": [1, 1]})
    bars = axes[0].bar(range(len(categories)), values, color=colors)
    for index, value in enumerate(values):
        axes[0].text(index, value + 1.2, f"{value:.1f}%", ha="center", fontsize=7)
    axes[0].set_xticks(range(len(categories)))
    axes[0].set_xticklabels(labels, rotation=18, ha="right")
    axes[0].set_ylabel("k=10 漏选率 (%)")
    axes[0].set_ylim(0, 70)
    axes[0].set_title("检索漏选率：外键列最高", fontsize=10.5, loc="left", fontweight="bold")

    comparisons = [
        ("桥接表内列 - 多表非桥接", data["paired_by_question"][k]["bridge_cols_minus_multi_nonbridge"]),
        ("外键列 - 多表非桥接", data["paired_by_question"][k]["fk_cols_minus_multi_nonbridge"]),
        ("并集 - 多表非桥接", data["paired_by_question"][k]["union_minus_multi_nonbridge"]),
    ]
    names = [item[0] for item in comparisons]
    diffs = [item[1]["difference_pp"] for item in comparisons]
    lows = [item[1]["ci95_pp"][0] for item in comparisons]
    highs = [item[1]["ci95_pp"][1] for item in comparisons]
    y = np.arange(len(names))
    axes[1].axvline(0, color="#666", linewidth=1)
    axes[1].errorbar(
        diffs,
        y,
        xerr=[np.array(diffs) - np.array(lows), np.array(highs) - np.array(diffs)],
        fmt="o",
        color="#333",
        ecolor="#333",
        capsize=4,
    )
    axes[1].set_yticks(y)
    axes[1].set_yticklabels(names, fontsize=8)
    axes[1].set_xlabel("漏选率差 (pp)，按问题配对 bootstrap")
    axes[1].set_title("控制多表题后的配对差", fontsize=10.5, loc="left", fontweight="bold")
    axes[1].set_xlim(min(lows) - 4, max(highs) + 4)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig3_retrieval_matched.png", bbox_inches="tight")
    plt.close(fig)


def make_fig4():
    data = json.loads(
        (ROOT / "BIRD_RESULTS" / "analysis" / "reanalysis_pure_column"
         / "reanalysis.json").read_text(encoding="utf-8")
    )
    models = ["qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b"]
    family = "add_pure_column_20"
    gate_diff = [data["gate"][model][family]["difference"] * 100 for model in models]
    gate_low = [data["gate"][model][family]["ci95"][0] * 100 for model in models]
    gate_high = [data["gate"][model][family]["ci95"][1] * 100 for model in models]
    extra = [data["baseline_correct"][model][family]["mean"] * 100 for model in models]
    extra_low = [data["baseline_correct"][model][family]["ci95"][0] * 100 for model in models]
    extra_high = [data["baseline_correct"][model][family]["ci95"][1] * 100 for model in models]

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8))
    y = np.arange(len(models))
    axes[0].axvline(0, color="#666", linewidth=1)
    axes[0].axvline(10, color="#E45756", linewidth=1.2, linestyle="--")
    axes[0].errorbar(
        gate_diff,
        y,
        xerr=[np.array(gate_diff) - np.array(gate_low), np.array(gate_high) - np.array(gate_diff)],
        fmt="o",
        color="#4C78A8",
        ecolor="#4C78A8",
        capsize=4,
    )
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([MODEL_LABELS[model] for model in models], fontsize=8)
    axes[0].set_xlabel("小模型下降 - DeepSeek 下降 (pp)")
    axes[0].set_title("纯列 20 全体门槛仍未通过", fontsize=10.5, loc="left", fontweight="bold")
    axes[0].text(10.2, y[-1] + 0.2, "10pp 门槛", color="#E45756", fontsize=7)

    axes[1].axvline(0, color="#666", linewidth=1)
    axes[1].errorbar(
        extra,
        y,
        xerr=[np.array(extra) - np.array(extra_low), np.array(extra_high) - np.array(extra)],
        fmt="o",
        color="#54A24B",
        ecolor="#54A24B",
        capsize=4,
    )
    axes[1].set_yticks(y)
    axes[1].set_yticklabels([MODEL_LABELS[model] for model in models], fontsize=8)
    axes[1].set_xlabel("baseline-correct 额外失败 (pp)")
    axes[1].set_title("但可解题上的机制仍显著", fontsize=10.5, loc="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig4_pure_column.png", bbox_inches="tight")
    plt.close(fig)


def main():
    setup_style()
    df = pd.read_csv(
        ROOT / "BIRD_RESULTS" / "analysis" / "column_level_curves_official.csv"
    )
    make_fig1(df)
    make_fig2(df)
    make_fig3()
    make_fig4()
    print("\n".join(str(path) for path in sorted(FIG_DIR.glob("*.png"))))


if __name__ == "__main__":
    main()
