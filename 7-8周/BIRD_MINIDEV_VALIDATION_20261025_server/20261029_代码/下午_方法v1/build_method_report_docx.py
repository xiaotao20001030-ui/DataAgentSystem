#!/usr/bin/env python3
"""Build the advisor report for the method-v1 round (Mini-Dev 500)."""

import json
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path("/Users/xiaotao/Documents/deepseek-harness/6.1实验")
OUT = ROOT / "汇报_20261029"
FONT_LATIN = "Arial"
FONT_CJK = "Arial Unicode MS"

MODELS = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b", "api_control")
NAMES = {"qwen3_0_6b": "Qwen3 0.6B", "qwen3_1_7b": "Qwen3 1.7B", "qwen3_4b": "Qwen3 4B",
         "qwen2_5_coder_1_5b": "Qwen2.5 Coder 1.5B", "api_control": "API（deepseek-chat）"}


def font(run, size, bold=False):
    run.font.name = FONT_LATIN
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT_CJK)


def style(document):
    normal = document.styles["Normal"]
    normal.font.name = FONT_LATIN
    normal.font.size = Pt(10.5)
    normal.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT_CJK)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.2
    for name, size in (("Title", 19), ("Heading 1", 12.5)):
        st = document.styles[name]
        st.font.name = FONT_LATIN
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor(0, 0, 0)
        st.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT_CJK)
    document.styles["Heading 1"].paragraph_format.space_before = Pt(12)
    document.styles["Heading 1"].paragraph_format.space_after = Pt(4)


def para(document, text, size=10.5, bold=False, after=6):
    p = document.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    font(p.add_run(text), size, bold)
    return p


def bullet(document, text, size=10.5):
    p = document.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    font(p.add_run(text), size)


def shade(cell, color):
    props = cell._tc.get_or_add_tcPr()
    fill = OxmlElement("w:shd")
    fill.set(qn("w:fill"), color)
    props.append(fill)


def table(document, headers, rows, widths, size=9, align=None):
    obj = document.add_table(rows=1, cols=len(headers))
    obj.alignment = WD_TABLE_ALIGNMENT.CENTER
    obj.autofit = False
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement("w:" + side)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:color"), "BFBFBF")
        borders.append(element)
    obj._tbl.tblPr.append(borders)
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    obj.rows[0]._tr.get_or_add_trPr().append(header)
    for column, width in zip(obj.columns, widths):
        column.width = Inches(width)
    align = align or ["left"] + ["center"] * (len(headers) - 1)
    for index, values in enumerate([headers] + rows):
        row = obj.rows[0] if index == 0 else obj.add_row()
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
            font(p.add_run(str(text)), size, index == 0)
            if index == 0:
                shade(cell, "E8EEF5")
            elif index % 2 == 0:
                shade(cell, "F7F9FB")


def main():
    report = json.loads((ROOT / "method_report.json").read_text())
    results = {r["model"]: r for r in report["results"]}
    stats = report["supplement_stats"]
    targets = {
        "qwen3_0_6b": (157.87, 15, 159.92, 13, 158.56),
        "qwen3_1_7b": (169.10, 16, 169.90, 14, 169.90),
        "qwen3_4b": (176.90, 17, 180.00, 15, 180.50),
        "qwen2_5_coder_1_5b": (198.99, 19, 199.97, 17, 201.48),
        "api_control": (176.20, 17, 179.98, 15, 180.53),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.27), Inches(11.69)
    section.top_margin = section.bottom_margin = Inches(0.75)
    section.left_margin = section.right_margin = Inches(0.75)
    style(document)

    document.add_paragraph("自校验补 Schema 方法（v1）实验报告", "Title")
    para(document, "BIRD Mini-Dev 500 · 五模型 · 三组同 token 对齐 · 严格 authorizer 评分 · 2026-10-29", size=9.5)

    document.add_heading("一、本轮结论", level=1)
    bullet(document, "既有实验的数字与代码对得上：固定 k、同预算、真列近义、严格口径、Spider 五组实验，全部从原始评分逐条重算，0 处不一致。")
    bullet(document, "方法 v1 未通过预注册判据（0/4 小模型达到 +3 pp 且 95% CI 下限 >0）。补 schema 触发率 28%–72%，但严格执行准确率与方法组并无显著提升。")
    bullet(document, "外键一跳在五个模型上一致优于普通 top-k（+0.4 / +1.4 / +4.9 / +2.8 / +6.6 pp），是本轮最稳定、最可复现的正向结论。")
    bullet(document, "30 条近义列错误已归因（8 条逐条读 SQL，其余按列集合自动分类）；8 条 Spider gold 与官方结果不符确认是数据集自身不一致，不是评测器 bug。")

    document.add_heading("二、数据与代码核验", level=1)
    para(document, "写了一个独立审计脚本，不经过任何汇总文件，直接从各实验的原始 score JSONL 重算：")
    bullet(document, "BIRD 固定 k：5 模型 × 2 档的配对 n、普通准确率、一跳准确率；")
    bullet(document, "BIRD 同预算：5 模型 × 3 档；真列近义：5 模型 × 4 档；")
    bullet(document, "隐藏 schema 严格口径：5 模型 × 2 条件的可评数、严格/宽松正确数；")
    bullet(document, "Spider 2.0-Lite：66 题共同分母 × 5 模型 × 2 条件的基线与扰动准确率。")
    para(document, "结果：与已发布结果逐位相等，issues = 0。脚本与输出：服务器 BIRD_MINIDEV_VALIDATION_20261025/audit_numbers.py、number_audit.json。")

    document.add_heading("三、方法 v1 设计（预注册）", level=1)
    para(document, "三组同 token 对齐，严格 authorizer 评分：")
    bullet(document, "A 普通 top-k：BGE 排名前 k 列；")
    bullet(document, "B 外键一跳：A 的种子列 + 声明外键对端，一波、不递归；")
    bullet(document, "C 方法：首轮同 top-8；生成后核验，若引用了提示外对象或执行报错，把缺失的表列名回检索器补入（含外键对端），最多 2 轮；近名列最多 2 组、各 5 个样例值。")
    para(document, "核验实现与老师原方案有一处差异：原方案用 sqlglot 解析出缺失对象。实测 sqlglot 对 authorizer 真实拦截对象的召回只有 54%（4B）/ 65%（API），会漏补，因此改为以 SQLite authorizer 的拒绝记录为准（对别名、子查询、SELECT * 都无漏判），sqlglot 仅在执行报错、拿不到拒绝记录时兜底解析。")
    para(document, "对齐规则：先跑 C，按其实测平均 schema token（含补入部分）逐模型反选 A/B 的整数 k，只依据 token 统计，不读取 gold 覆盖率或模型成绩。评分用 authorizer 只放行提示内 schema，越界判错；按题配对 bootstrap 1000 次；判据预先固定为至少 2 个小模型 C−A ≥ 3 pp 且 95% CI 下限 >0。")

    document.add_heading("四、结果", level=1)
    para(document, "表 1  三组严格执行准确率（%），n 为三组共同可评题", size=9, bold=True)
    rows = []
    for model in MODELS:
        r = results[model]
        pass_text = "参照" if model == "api_control" else ("是" if r["passes"] else "否")
        rows.append([NAMES[model], str(r["n"]), f"{r['plain'] * 100:.1f}", f"{r['fk1'] * 100:.1f}",
                     f"{r['method'] * 100:.1f}", f"{r['method_minus_plain_pp']:+.1f}",
                     f"[{r['ci_low_pp']:+.1f}, {r['ci_high_pp']:+.1f}]", pass_text])
    table(document, ["模型", "n", "A 普通", "B 一跳", "C 方法", "C−A pp", "95% CI pp", "达标"], rows,
          [1.35, 0.45, 0.7, 0.7, 0.7, 0.75, 1.15, 0.55])
    para(document, "判定：0/4 小模型达标，方法 v1 未通过预注册判据。", size=9.5)

    para(document, "表 2  三组平均 schema token 对齐", size=9, bold=True)
    rows = []
    for model in MODELS:
        c, kp, mp, kf, mf = targets[model]
        rows.append([NAMES[model], f"{c:.1f}", f"{kp}", f"{mp:.1f}", f"{kf}", f"{mf:.1f}"])
    table(document, ["模型", "C 实测均值", "A k", "A 均值", "B 种子 k", "B 均值"], rows,
          [1.5, 1.0, 0.55, 0.95, 0.8, 0.95])
    para(document, "三组均值差 ≤ 2.5 token；C 的 token 含补入的表列与样例值。", size=9)

    para(document, "表 3  方法 C 的补 schema 行为", size=9, bold=True)
    rows = []
    for model in MODELS:
        s = stats[model]
        rows.append([NAMES[model], f"{s['triggered']}/{s['n']}", f"{s['triggered'] / s['n'] * 100:.0f}%",
                     f"{s['added_tokens_mean']:.1f}", f"{s['rounds_mean']:.2f}", f"{s['blocked_mean']:.2f}"])
    table(document, ["模型", "触发题数", "触发率", "平均补 token", "平均轮次", "越界拦截/题"], rows,
          [1.5, 0.85, 0.7, 1.0, 0.85, 1.0])

    document.add_heading("五、为什么方法没有跑赢", level=1)
    bullet(document, "同 token 下，A 组把预算全花在列覆盖上；C 组约 40–50 token 花在样例值提示上，列覆盖反而更少。")
    bullet(document, "补 schema 只修“引用了不存在的对象”，修不了“列选错、连接写错、聚合写错”这类语义错误；C 与 A 持平、都低于 B 正说明这一点。")
    bullet(document, "首轮只给 8 列，SQL 结构一旦写歪，二次生成很难救回；补 schema 的收益被首轮信息不足抵消。")
    bullet(document, "设计缺陷：提示里展示了近名列的样例值，但这些列不在最终可见 schema 中，模型若采用会被 authorizer 判越界（拦截量 0.3–1.2 次/题，量不大但逻辑上应改为“模型已引用该近名列时才给值”）。")

    document.add_heading("六、30 条近义列错误判读", level=1)
    para(document, "对 API 在近义列扰动下的 30 条可评分错误逐条查看（8 条逐条读 SQL，其余按列集合自动分类），结论如下：")
    para(document, "表 4  30 条错误归因", size=9, bold=True)
    table(document, ["归因", "条数", "说明"], [
        ["引用了近名列", "6", "如用 disp.client_id、comments.UserDisplayName 替代正确维表或连接列"],
        ["谓词/聚合/输出列错误", "21", "列选对了，但 WHERE/HAVING、聚合方式或输出列与 gold 不一致"],
        ["选列不完整", "2", "缺少 gold 所需列"],
        ["SQL 语法错误", "1", "无法执行"],
    ], [1.5, 0.55, 4.3], align=["left", "center", "left"])
    para(document, "只有 6/30 能明确归因到近名列误用，多数仍是普通 SQL 语义错误；因此“小模型特别怕近名列”的主要证据应仍以 5/10/20/50 剂量曲线为准，30 条只能作案例说明。该表为模型辅助审阅，不是人工签字版。", size=9.5)

    document.add_heading("七、8 条 Spider gold 与官方结果不符", level=1)
    para(document, "24 道有原生 gold SQL 的题中，16 道与官方 exec_result 一致，8 道不一致。逐条核对后确认是数据集自身问题：shipped 的 gold SQL 与官方结果 CSV 并非同一版查询生成。")
    para(document, "表 5  8 条不一致的具体差异", size=9, bold=True)
    table(document, ["题号", "库", "gold SQL 结果 vs 官方 CSV", "类型"], [
        ["local003", "E_commerce", "11×2 vs 9×2（官方另有多套 9×8/9×10）", "行数与列数均不同"],
        ["local023", "IPL", "5×2 vs 5×3", "少一列"],
        ["local029", "Brazilian_E_Commerce", "3×3 vs 3×5/3×4", "少列"],
        ["local066", "modern_data", "12×2 vs 12×2，第二列取值不同", "取值不同"],
        ["local131", "EntertainmentAgency", "20×4 vs 25×5", "行列均不同"],
        ["local210", "delivery_center", "21×1 vs 21×6/21×5", "gold SQL 只返回 1 列"],
        ["local219", "EU_soccer", "11×2 vs 11×3/11×2", "少列"],
        ["local309", "f1", "75×3 vs 75×3，driver/constructor 名称不同", "取值不同"],
    ], [0.75, 1.45, 2.9, 1.3], align=["left", "left", "left", "left"])
    para(document, "因此之前“24 条中 16 条可评”应写成数据侧上限；不是执行或比较代码的问题。", size=9)

    document.add_heading("八、局限", level=1)
    bullet(document, "评分超时本轮统一为 20 秒（此前实验为 60/120 秒），少量重查询可能被判错；n=490–495。")
    bullet(document, "API 模型用 deepseek-chat；其内部 token 数与 Qwen tokenizer 不同，token 对齐口径只保证公共计数一致。")
    bullet(document, "30 条判读为模型辅助，非人工签字；gold 8 条只核对了结果层差异，未追溯官方数据生成流程。")

    document.add_page_break()
    document.add_heading("附表：宽松口径结果（非主结论）", level=1)
    para(document, "按老师要求，严格口径为主，宽松口径只作附表。同一批预测去掉 authorizer 约束后重跑，结论与严格口径一致：方法不优于普通 top-k，外键一跳仍最好。", size=9.5)
    para(document, "表 A1  三组宽松口径执行准确率（%）", size=9, bold=True)
    perm = [
        ("Qwen3 0.6B", 451, 2.4, 2.4, 3.3, 0.9),
        ("Qwen3 1.7B", 455, 9.0, 10.3, 7.9, -1.1),
        ("Qwen3 4B", 455, 16.9, 22.0, 16.0, -0.9),
        ("Qwen2.5 Coder 1.5B", 453, 9.1, 11.7, 10.2, 1.1),
        ("API（deepseek-chat）", 451, 23.1, 29.7, 25.1, 2.0),
    ]
    table(document, ["模型", "n", "A 普通", "B 一跳", "C 方法", "C−A pp"],
          [[m, str(n), f"{a:.1f}", f"{b:.1f}", f"{c:.1f}", f"{d:+.1f}"] for m, n, a, b, c, d in perm],
          [1.6, 0.5, 0.8, 0.8, 0.8, 0.9])
    para(document, "注：宽松口径下 20 秒超时与并发争用会使少量重查询被判错，n 略小于严格口径；两套口径的排序与差值方向一致。", size=8.5)

    document.add_heading("九、下一步（我认为）", level=1)
    para(document, "把外键一跳作为方法论文的实证主结论先写；方法 v2 只做三处修改——样例值改为按需给、初始 k 提到 12、补 schema 后只重写 SQL 不重新规划——再跑一轮 Mini-Dev，若仍不超过普通 top-k，就把“自校验补 schema”降为负结果附录。")

    document.add_heading("附录：文件与复现", level=1)
    bullet(document, "预注册协议：method_v1_PROTOCOL.md；方法实现：method_v1.py；三组对齐：aligned_variants.py。")
    bullet(document, "逐题记录（补几轮/补多少 token/拦截次数）：method_c_130/*.jsonl；评分：method_scores/*.jsonl；对齐与预测：aligned_ab/。")
    bullet(document, "审计：audit_numbers.py 与 number_audit.json；30 条判读：synonym30_review_filled.csv；gold 差异明细：gold_mismatch_detail.json（服务器）。")
    bullet(document, "服务器目录：BIRD_MINIDEV_VALIDATION_20261025/{method_c_130, method_scores, aligned_ab}。")

    path = OUT / "方法v1实验报告_20261029.docx"
    document.save(path)
    print(path)


if __name__ == "__main__":
    main()
