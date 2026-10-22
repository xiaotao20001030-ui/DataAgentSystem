# BIRD Mini-Dev 验证性实验状态

## 已完成

- BIRD Mini-Dev 500 题和五个模型全部执行。
- 随机/合成近义加列 5/10/20/50 全部完成。
- 桥接表和外键列移除实验全部完成。
- 向量检索 k=5/10/20/50 漏选统计完成。
- 27,620 条预测已按 BIRD 官方 set 语义和 30 秒超时重新评分。
- 旧评分与新评分差异已逐条件审计。
- 生成脚本已补齐 Python、Torch、CUDA 和 API seed 设置。

## 正式结论

- 检索桥接偏差门槛：通过。
- 随机多给 20 列执行门槛：不通过。
- 6.1 原始综合标准：不通过。
- Baseline-correct 分析支持机制假设，但属于事后补充。
- 真实 schema 近义列支持机制，但影响显著弱于人工近义列。
- 漏给条件下 DeepSeek 普通准确率更高，但合规准确率仍很低。

## 文档版本

- 正式整合版：`BIRD_MiniDev_Experiment_Report_v2.md/.docx/.pdf`
- 两页版：`BIRD_MiniDev_Validation_2Page_Report_v2.md/.docx/.pdf`
- 7–8 周组会两页版：`BIRD_MiniDev_7-8周_两页报告_v2.md/.docx/.pdf`
- 组会 PPT：`组会汇报_7-8周.pptx`；提纲：`组会汇报_7-8周.md`
- 汇总图：`figures/fig1–fig4`
- 详细审计：`POSTHOC_REANALYSIS_2026-10-22.md/.docx/.pdf`
- v1 原始报告保留，PDF 未重生成。

## 事后重分析

- 检索匹配基线、random 新表混淆、synonym `same_name` 分层、gate 配对修复
  已写入 `result/POSTHOC_REANALYSIS_2026-10-22.md`。
- 新增纯列扰动生成器 `perturbations/generate_pure_column.py`；这是最小补实验，
  不需要重跑原始 27,620 条预测。
- 已在服务器用原始检索脚本的文档/标签复现匹配基线：k=10 时桥接表内列比
  多表非桥接目标列低 13.91pp（CI [-24.22, -3.69]），外键列高 13.75pp
  （CI [+9.79, +17.73]）。
- 已完成 synonym 分层、transition、gate qid 对齐、缺失 schema 合规审计；
  结果保存在服务器 `BIRD_RESULTS/analysis/`，本仓库有副本。
- 纯列 20 补实验（base + add_pure_column_20，五模型）已完成：全体准确率
  门槛仍不通过，但 baseline-correct 额外失败仍显著（10.00–34.13pp）。
  结果在服务器 `BIRD_RESULTS/analysis/reanalysis_pure_column/` 与本仓库
  `analysis/reanalysis_pure_column/`。
- 服务器完成的预测、官方评分、分析 JSON 和日志已同步到本地
  `7-8周/BIRD_RESULTS/`。

## 尚未完成

- Spider 2.0-Lite SQLite 回退实验尚未执行。
- Spider2-Lite 135 题列级标签仅覆盖 50 题。
