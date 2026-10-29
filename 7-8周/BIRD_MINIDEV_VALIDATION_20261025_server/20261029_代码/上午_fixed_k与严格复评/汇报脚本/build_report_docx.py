#!/usr/bin/env python3
"""Build the unified advisor report (DOCX) from fetched result files."""

import json
import os
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path("/Users/xiaotao/Documents/deepseek-harness/6.1实验")
DATA = Path(os.environ.get("REPORT_DATA", ROOT / "results_20261029"))
OUT = Path(os.environ.get("REPORT_OUT", ROOT / "汇报_20261029"))
BUILDER_DIR = Path("/Users/xiaotao/Documents/ChatGPT/6.1测试项目/fixed_k_fk_20261029")

MODELS = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b", "api_control")
NAMES = {
    "qwen3_0_6b": "Qwen3 0.6B",
    "qwen3_1_7b": "Qwen3 1.7B",
    "qwen3_4b": "Qwen3 4B",
    "qwen2_5_coder_1_5b": "Qwen2.5 Coder 1.5B",
    "api_control": "API 对照",
}
FONT_LATIN = "Arial"
FONT_CJK = "Arial Unicode MS"


def set_run_font(run, size, bold=False):
    run.font.name = FONT_LATIN
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT_CJK)


def style_document(document):
    normal = document.styles["Normal"]
    normal.font.name = FONT_LATIN
    normal.font.size = Pt(10.5)
    normal.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT_CJK)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.2
    for name, size in (("Title", 19), ("Heading 1", 12.5), ("Heading 2", 11)):
        style = document.styles[name]
        style.font.name = FONT_LATIN
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT_CJK)
    document.styles["Heading 1"].paragraph_format.space_before = Pt(12)
    document.styles["Heading 1"].paragraph_format.space_after = Pt(4)
    document.styles["Heading 2"].paragraph_format.space_before = Pt(8)
    document.styles["Heading 2"].paragraph_format.space_after = Pt(3)


def paragraph(document, text, size=10.5, bold=False, space_after=6):
    p = document.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    set_run_font(run, size, bold)
    return p


def bullet(document, text, size=10.5):
    p = document.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run(text)
    set_run_font(run, size)
    return p


def shade(cell, color):
    properties = cell._tc.get_or_add_tcPr()
    fill = OxmlElement("w:shd")
    fill.set(qn("w:fill"), color)
    properties.append(fill)


def table(document, headers, rows, widths, font_size=9, align=None):
    table_obj = document.add_table(rows=1, cols=len(headers))
    table_obj.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_obj.autofit = False
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement("w:" + side)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:color"), "BFBFBF")
        borders.append(element)
    table_obj._tbl.tblPr.append(borders)
    header_props = OxmlElement("w:tblHeader")
    header_props.set(qn("w:val"), "true")
    table_obj.rows[0]._tr.get_or_add_trPr().append(header_props)
    for column, width in zip(table_obj.columns, widths):
        column.width = Inches(width)
    align = align or ["left"] + ["center"] * (len(headers) - 1)
    for index, values in enumerate([headers] + rows):
        row = table_obj.rows[0] if index == 0 else table_obj.add_row()
        if index:
            no_split = OxmlElement("w:cantSplit")
            row._tr.get_or_add_trPr().append(no_split)
        for column_index, (cell, text) in enumerate(zip(row.cells, values)):
            cell.width = Inches(widths[column_index])
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.line_spacing = 1.05
            p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER}[align[column_index]]
            run = p.add_run(str(text))
            set_run_font(run, font_size, index == 0)
            if index == 0:
                shade(cell, "E8EEF5")
            elif index % 2 == 0:
                shade(cell, "F7F9FB")
    return table_obj


def load():
    bird = json.loads((DATA / "fixed/results.json").read_text())
    spider = json.loads((DATA / "spider/results.json").read_text())
    strict = json.loads((DATA / "strict/strict_summary.json").read_text())
    budget = json.loads((DATA / "budget/equal_budget_summary.json").read_text())
    retrieval = json.loads((DATA / "retrieval/fk_expansion_summary.json").read_text())
    synonym = json.loads((DATA / "synonym/real_synonym_rerun_summary.json").read_text())
    return bird, spider, strict, budget, retrieval, synonym


def spider_rows(spider):
    rows = [r for r in spider["rows"] if r["stratum"] == "all"]
    by_key = {(r["condition"], r["model"]): r for r in rows}
    out = []
    for condition in ("random20", "synonym20"):
        for model in MODELS:
            r = by_key[(condition, model)]
            if model == "api_control":
                effect, ci = "—", "—"
            else:
                effect = f"{r['drop_difference_pp']:+.1f}"
                ci = f"[{r['ci95_lower_pp']:+.1f}, {r['ci95_upper_pp']:+.1f}]"
            out.append([condition, NAMES[model], str(r["n"]), f"{r['base_accuracy'] * 100:.1f}",
                        f"{r['perturbed_accuracy'] * 100:.1f}", effect, ci])
    return out


def bird_rows(bird):
    out = []
    for target in (130, 200):
        for model in MODELS:
            r = bird["models"][model][str(target)]
            out.append([f"BIRD {target}", NAMES[model], str(int(r["paired_n"])),
                        f"{r['plain_accuracy'] * 100:.1f}", f"{r['fk1_accuracy'] * 100:.1f}",
                        f"{r['fk1_gain_pp']:+.1f}", f"[{r['ci95_low_pp']:+.1f}, {r['ci95_high_pp']:+.1f}]"])
    return out


def budget_rows(budget):
    out = []
    for target in ("110", "130", "200"):
        for model in MODELS:
            r = budget["models"][model][target]
            out.append([f"{target} token", NAMES[model], str(int(r["paired_n"])),
                        f"{r['plain_accuracy'] * 100:.1f}", f"{r['fk1_accuracy'] * 100:.1f}",
                        f"{r['fk1_gain_pp']:+.1f}", f"[{r['ci95_low_pp']:+.1f}, {r['ci95_high_pp']:+.1f}]"])
    return out


def strict_rows(strict):
    out = []
    for model in MODELS:
        bridge = strict["families"]["missing_bridge_table"][model]
        fk = strict["families"]["missing_fk_column"][model]
        denied = bridge["status"].get("denied_hidden_access", 0) + fk["status"].get("denied_hidden_access", 0)
        out.append([NAMES[model],
                    f"{bridge['n_scoreable']}",
                    f"{bridge['permissive_accuracy'] * 100:.2f} → {bridge['strict_accuracy'] * 100:.2f}",
                    f"{fk['n_scoreable']}",
                    f"{fk['permissive_accuracy'] * 100:.2f} → {fk['strict_accuracy'] * 100:.2f}",
                    str(denied)])
    return out


def retrieval_rows(retrieval):
    names = {"all-MiniLM-L6-v2": "MiniLM-L6-v2", "bge-base-en-v1.5": "BGE-base-en-v1.5"}
    rows = []
    for path, value in retrieval.items():
        key = path.rstrip("/").split("/")[-1]
        single = value["original_hypothesis"]["10"]["single_target_columns"]["miss_rate"]
        fk = value["original_hypothesis"]["10"]["foreign_key_columns"]["miss_rate"]
        diff = value["original_hypothesis"]["10"]["foreign_key_columns_vs_single"]
        plain = value["plain"]["10"]
        expanded = value["expanded"]["10"]
        rows.append([
            names.get(key, key), f"{single * 100:.1f}", f"{fk * 100:.1f}",
            f"{diff['difference_percentage_points']:+.1f} [{diff['ci95_low_percentage_points']:+.1f}, {diff['ci95_high_percentage_points']:+.1f}]",
            f"{plain['miss_rate'] * 100:.1f} → {expanded['miss_rate'] * 100:.1f}",
            f"{plain['mean_schema_token_proxy']:.1f} → {expanded['mean_schema_token_proxy']:.1f}",
        ])
    return rows


def synonym_rows(synonym):
    levels = (("base", "基线"), ("add_real_synonym_5", "+5"), ("add_real_synonym_10", "+10"),
              ("add_real_synonym_20", "+20"), ("add_real_synonym_50", "+50"))
    rows = []
    for model in MODELS:
        fixed = synonym["fixed_248"][model]
        base = fixed["base"]["accuracy"]
        end = fixed["add_real_synonym_50"]["accuracy"]
        rows.append([NAMES[model]] + [f"{fixed[key]['accuracy'] * 100:.1f}" for key, _ in levels]
                    + [f"{(base - end) * 100:.1f} pp / {(base - end) / base * 100:.1f}%"])
    return rows


def build():
    bird, spider, strict, budget, retrieval, synonym = load()
    import importlib.util

    spec = importlib.util.spec_from_file_location("builder", BUILDER_DIR / "build_teacher_table.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    rows, passing = builder.build_rows(bird, spider)

    OUT.mkdir(parents=True, exist_ok=True)
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.27), Inches(11.69)
    section.top_margin = section.bottom_margin = Inches(0.75)
    section.left_margin = section.right_margin = Inches(0.75)
    style_document(document)

    document.add_paragraph("BIRD Mini-Dev 与 Spider 2.0-Lite 阶段结果汇总", "Title")
    paragraph(document, "2026 年 10 月 29 日 · RQ1 检索侧 · 同预算与固定 k 外键一跳 · Spider 重试 · 严格口径与真实近名扰动", size=9.5)

    document.add_heading("一、结论", level=1)
    gate = "；".join(f"{c} {len(passing[c])}/4" for c in ("random20", "synonym20"))
    mini = retrieval["/root/fsas/home/xiaotao/xiaotao/models/all-MiniLM-L6-v2"]
    bge = retrieval["/root/fsas/home/xiaotao/xiaotao/MINIDEV/modules/bge-base-en-v1.5"]
    bullet(document, f"RQ1 检索侧成立：top-10 外键/连接列漏选率 MiniLM {mini['original_hypothesis']['10']['foreign_key_columns']['miss_rate'] * 100:.2f}% 对单表 {mini['original_hypothesis']['10']['single_target_columns']['miss_rate'] * 100:.2f}%；BGE {bge['original_hypothesis']['10']['foreign_key_columns']['miss_rate'] * 100:.2f}% 对 {bge['original_hypothesis']['10']['single_target_columns']['miss_rate'] * 100:.2f}%。沿外键补一跳把桥接成分并集漏选降到 MiniLM {mini['expanded']['10']['miss_rate'] * 100:.1f}%、BGE {bge['expanded']['10']['miss_rate'] * 100:.1f}%，schema token 增加约 17–21。")
    bullet(document, f"Spider 2.0-Lite 重试按预注册判据未通过（{gate}）。6.1 假设在 SQLite 子集上未获支持，论文按约定收缩为 RQ1 系统实证研究。")
    bullet(document, "BIRD 同预算（逐题 110/130/200 token 上限）：只有 Qwen3 1.7B 在 110 档（+3.4 pp，[+1.4, +5.4]）和 130 档（+2.2 pp，[+0.4, +4.2]）区间下限为正；200 档所有模型区间跨 0，其余小模型三档均不显著。")
    gains = []
    for target in (130, 200):
        positive = [NAMES[m] for m in MODELS if m != "api_control" and bird["models"][m][str(target)]["ci95_low_pp"] > 0]
        gains.append(f"{target} 档区间下限为正的小模型：{'、'.join(positive) if positive else '无'}")
    bullet(document, "BIRD 固定 k 外键一跳：" + "；".join(gains) + "。")
    bullet(document, "隐藏 schema 严格口径：API 隐藏桥接表 19.42% → 4.85%，Qwen3 4B 隐藏外键列 20.73% → 1.42%，API 外键列 36.99% → 2.44%；原宽松口径下靠读取提示外对象答对的部分被剔除。")
    syn_api = synonym["fixed_248"]["api_control"]
    syn_4b = synonym["fixed_248"]["qwen3_4b"]
    syn_06 = synonym["fixed_248"]["qwen3_0_6b"]
    bullet(document, f"真列近义扰动（重做版，固定 248 题）：干扰列 0→50 时 API {syn_api['base']['accuracy'] * 100:.1f}% → {syn_api['add_real_synonym_50']['accuracy'] * 100:.1f}%（−{(syn_api['base']['accuracy'] - syn_api['add_real_synonym_50']['accuracy']) * 100:.1f} pp），Qwen3 4B {syn_4b['base']['accuracy'] * 100:.1f}% → {syn_4b['add_real_synonym_50']['accuracy'] * 100:.1f}%，0.6B {syn_06['base']['accuracy'] * 100:.1f}% → {syn_06['add_real_synonym_50']['accuracy'] * 100:.1f}%；相对下降最大的是 0.6B（−{(syn_06['base']['accuracy'] - syn_06['add_real_synonym_50']['accuracy']) / syn_06['base']['accuracy'] * 100:.1f}%），API 为 −{(syn_api['base']['accuracy'] - syn_api['add_real_synonym_50']['accuracy']) / syn_api['base']['accuracy'] * 100:.1f}%。")
    bullet(document, "11 月 6 日交付表见第八节（表 7，20 行）：BIRD 130/200 两组 × 5 模型、Spider 随机/近义两组 × 5 模型。")

    document.add_heading("二、RQ1 检索侧：外键列漏选与一跳扩展", level=1)
    paragraph(document, "BIRD Mini-Dev 500 题，用问题文本对 schema 列做向量检索，统计 gold 需要的列是否进入 top-10。桥接成分并集按 391 道有桥接标签问题的 1,032 个目标列计算；token 仅计所选列的 schema 文本。")
    paragraph(document, "表 1  RQ1 检索侧：top-10 漏选率（%）与外键一跳的效果", size=9, bold=True)
    table(document,
          ["编码器", "top10 单表漏选", "top10 外键漏选", "差值 pp [95% CI]", "一跳前 → 后（并集）", "schema token 前 → 后"],
          retrieval_rows(retrieval),
          [1.15, 0.85, 0.85, 1.55, 1.05, 1.25])
    paragraph(document, "结论：外键/连接列的漏选在两种编码器上都显著高于单表目标列（MiniLM +29.1 pp、BGE +30.4 pp，区间下限均大于 0），换 BGE 后结论不变，可作论文出发点。外键一跳显著降低漏选，但只证明检索侧改善，下游执行准确率见第三节和第四节。", size=9.5)

    document.add_heading("三、Spider 2.0-Lite 重试", level=1)
    paragraph(document, f"题源 135 道 SQLite 题：24 道有原生 gold SQL（16 道通过官方结果比较）；其余 111 道每题由 API 在完整 schema 下生成 3 次 SQL，56 道有结果匹配的银标签；最终五模型三条件共同可评 {spider['common_scored_n']} 题（gold {spider['common_gold_n']} 题、银标签 {spider['common_silver_n']} 题）。随机列从同库非答案列抽取，近义列在 SQLite 副本中真实建列并填同类型值，固定随机种子。")
    paragraph(document, "表 2  Spider 2.0-Lite 三条件执行准确率（%），效应为小模型掉点减 API 掉点", size=9, bold=True)
    table(document,
          ["条件", "模型", "n", "基线", "扰动", "效应 pp", "95% CI pp"],
          spider_rows(spider),
          [0.9, 1.5, 0.4, 0.75, 0.75, 0.75, 1.5])
    paragraph(document, "判定（预先固定，跑完不改）：同一种扰动中，4 个小模型至少 2 个额外下降 >10 pp 且配对 bootstrap 95% 区间下限 >0，才算通过。本次两个条件均为 0/4，未通过。小模型基线仅 0.0%–9.1%，存在地板效应；银标签由 API 结果匹配产生，可能偏向 API。", size=9.5)

    document.add_heading("四、BIRD 同预算对比（逐题 token 上限）", level=1)
    paragraph(document, "500 题共用同一份 BGE 排名。按 Qwen3-0.6B tokenizer 对实际注入提示的 schema 文本计数，每题分别在 110/130/200 token 上限内选择能容纳的最大检索前缀；外键组从同一份排名的种子列出发，沿声明外键补一跳。列长度离散，实际用量略低于上限：三档普通/一跳平均 104.9/102.2、124.9/122.8、188.9/187.8 token。")
    paragraph(document, "表 3  BIRD 同预算条件下普通 top-k 与外键一跳的执行准确率（%）", size=9, bold=True)
    table(document,
          ["预算", "模型", "n", "普通 EX", "一跳 EX", "效应 pp", "95% CI pp"],
          budget_rows(budget),
          [0.8, 1.5, 0.4, 0.75, 0.75, 0.75, 1.5])
    paragraph(document, "结论：只有 Qwen3 1.7B 在 110 档（+3.4 pp，95% CI [+1.4, +5.4]）和 130 档（+2.2 pp，[+0.4, +4.2]）区间下限为正；200 档所有模型（含 API）区间均跨 0。其余小模型三档都不显著。同预算下外键一跳的提升不稳定，也没有随预算增大而扩大的趋势。本实验与下一节的固定 k 实验是两组独立实验，不能合并解释。", size=9.5)

    document.add_heading("五、BIRD 固定 k 外键一跳", level=1)
    fixed = {t: bird["fixed_ks"][str(t)] for t in (130, 200)}
    tokens = {t: (bird["retrieval_summary"][f"plain_fixed_{t}"]["mean_schema_tokens"],
                  bird["retrieval_summary"][f"fk1_fixed_{t}"]["mean_schema_tokens"]) for t in (130, 200)}
    paragraph(document,
              f"130 档：普通 top{ fixed[130]['plain']} 对 top{ fixed[130]['fk1']} 加声明外键一跳，实际平均 schema token {tokens[130][0]:.1f}/{tokens[130][1]:.1f}；"
              f"200 档：普通 k={ fixed[200]['plain']} 对种子 k={ fixed[200]['fk1']} 加一跳，实际平均 {tokens[200][0]:.1f}/{tokens[200][1]:.1f}。"
              "k 在题间固定，列数不足时取全部可用列；名义 130/200 是长度目标，不逐题严格相等。")
    paragraph(document, "表 4  BIRD 固定 k 外键一跳执行准确率（%），效应 = 一跳 − 普通", size=9, bold=True)
    table(document,
          ["档位", "模型", "n", "普通 EX", "一跳 EX", "效应 pp", "95% CI pp"],
          bird_rows(bird),
          [0.8, 1.5, 0.4, 0.75, 0.75, 0.75, 1.5])
    paragraph(document, "评分为项目自定义 SQLite 结果比较器（浮点四舍五入 8 位，gold 含 ORDER BY 时按序，否则多重集），不是 BIRD 官方集合相等评分；配对 bootstrap 区间未做多重比较校正。", size=9.5)

    document.add_heading("六、隐藏 schema 条件的严格口径复评", level=1)
    paragraph(document, "对象：原 Mini-Dev 的隐藏桥接表 103 条与隐藏外键列 494 条变体，五模型已保存的预测。做法：不重新生成，评分时给 SQLite 挂 authorizer，只允许读取提示 schema 中真实出现的表和列；越界读取（隐藏桥接表、隐藏外键列、其他未展示的表列）直接判错。gold 超时不可执行的题成对剔除。")
    paragraph(document, "对账：API 隐藏桥接表在原 99 道可评题上是 18/99 = 18.18%，严格口径 3/99 = 3.03%，与上轮审计一致。本次复评把原评分器判为 gold 超时的 4 道桥接题也纳入，故表 5 桥接分母为 103，对应 20/103 = 19.42% → 5/103 = 4.85%。")
    paragraph(document, "表 5  隐藏 schema 条件的宽松与严格执行准确率（%）", size=9, bold=True)
    table(document,
          ["模型", "桥接 n", "桥接 宽松 → 严格", "外键 n", "外键 宽松 → 严格", "越界读取"],
          strict_rows(strict),
          [1.5, 0.55, 1.4, 0.55, 1.4, 0.8])
    paragraph(document, "两列之差就是“读取了提示中不存在的对象才答对”的虚高部分。原 EXPLAIN 审计把大量记录判成不可判定；本次用 authorizer 在执行期判定，全部记录都有确定分类。", size=9.5)

    document.add_heading("七、真列近义扰动（重做版）", level=1)
    paragraph(document, "上一版近义列只在提示里加名字、没有在 SQLite 建列，结论作废。重做版从每题真实列中选取近名干扰列：同一数据库、非 gold 所需列，列名 token Jaccard 或字符相似度 ≥0.25，同类型加权；每个加入的 table.column 都经 PRAGMA 验证，gold 在副本上通过 EXPLAIN。四档共加入 28,035 次真实列；下表固定四档都能构造的同一批 248 题。")
    paragraph(document, "表 6  真列近义扰动的执行准确率（%），固定 248 题", size=9, bold=True)
    table(document,
          ["模型", "基线", "+5", "+10", "+20", "+50", "50 列下降"],
          synonym_rows(synonym),
          [1.5, 0.75, 0.7, 0.7, 0.7, 0.7, 1.15])
    paragraph(document, "结论：干扰列越多掉点越大，存在剂量效应。相对下降最大的是 Qwen3 0.6B（−36.8%），API 相对下降最小（−12.9%），Qwen3 4B 绝对下降最大（−11.9 pp）。这是真实列名的近名干扰，列名相近不保证语义同义；30 条 API 错误的人工判读仍未完成。", size=9.5)

    document.add_page_break()
    document.add_heading("八、交付总表", level=1)
    caption = paragraph(document, "表 7  五模型合表（BIRD 固定 k 与 Spider2 扰动）", size=9, bold=True)
    caption.paragraph_format.keep_with_next = True
    table(document,
          ["实验", "模型", "n", "对照 EX %", "处理 EX %", "效应 pp", "95% CI pp"],
          [[c.replace("Spider2 random20", "Spider2 随机").replace("Spider2 synonym20", "Spider2 近义")
            for c in builder.display_cells(r)] for r in rows],
          [0.9, 1.5, 0.4, 0.75, 0.75, 0.75, 1.5])
    paragraph(document, "效应定义：BIRD 为一跳 − 普通，正值表示一跳更好；Spider2 为小模型掉点 − API 掉点，正值表示小模型额外下降。API 行只作参照，效应与区间记为 —。", size=9)

    document.add_heading("九、口径与未完成事项", level=1)
    bullet(document, "Spider 银标签由 API 结果匹配产生，存在偏向 API 的选择偏差；小模型基线低，绝对掉点受地板效应限制。")
    bullet(document, "Spider 24 道 gold 中有 8 道执行结果与官方评测不一致，已按不可用剔除，原因尚未逐条查明。")
    bullet(document, "真列近名扰动的 30 条人工判读尚未完成；近名列与语义同义列不是一回事。")
    bullet(document, "BIRD 130/200 的 token 为共同 tokenizer 下的实际均值，不逐题相等；固定 k 与逐题同预算实验是两组独立实验，不合并解释。")
    bullet(document, "随机加列实验的相对下降只有 Qwen3 0.6B 显著，按上轮约定不作主结论。")
    bullet(document, "RQ2（预算内选择 vs 连接图补全）在 6.1 未通过后不再单独展开，论文按约定收缩到 RQ1。")
    bullet(document, "下一步：按 6.1 未通过收缩为 RQ1 系统实证研究；11 月中旬在 BIRD 全量与 Spider 2.0-Lite 全量上跑完整实验。")

    paragraph(document, "数据来源：MINIDEV/retrieval_fk_results_complete/fk_expansion_summary.json、equal_budget_fk_20261028/reports/equal_budget_execution_summary.json、fixed_k_fk_20261029/reports/results.json、bridge_strict_20261029/strict_all/strict_summary.json、synonym_real_rerun_20261028/reports/real_synonym_rerun_summary.json、Spider2-Lite/spider2_retry_20261028/reports/results.json。", size=8.5)

    path = OUT / "BIRD_Spider2_阶段汇总_20261029.docx"
    document.save(path)
    print(path)
    return path


if __name__ == "__main__":
    build()
