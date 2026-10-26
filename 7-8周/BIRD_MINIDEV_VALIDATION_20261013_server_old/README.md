# 7-8 周：小模型 Schema 鲁棒性与向量检索外键偏差（最终版）

数据 500 题 / 11 库，5 个模型。

## 入口

- **结论**：[结论.md](结论.md)
- **正式完整报告**：`report/实验报告.md/.docx/.pdf`
- **两页版**：`report/两页报告.md/.docx/.pdf`
- **组会 PPT**：`report/组会汇报_7-8周.pptx`

## 目录结构

```text
结论.md            结论摘要
report/            最终报告（md/docx/pdf/pptx）与汇总图 figures/
data/              原始数据（JSON/gold SQL/校验报告）与 11 个 SQLite 库
scripts/           全部脚本（perturbations / analysis / 模型预测评分）
output/            扰动、预测、评分、分析的 JSON/JSONL/CSV 产物
```

## 关键结论

- 向量检索对外键/连接列存在稳健漏选偏差（+13.75pp，95% CI [+9.79, +17.73]）。
- 「小模型加 20 个真实无关列后总体比大模型多下降 10pp」的主门槛不通过（四模型额外下降 0.00 到 +5.10pp）。
- 在基线可解子集上，小模型保持率显著更低（+16.5 到 +51.9pp），机制存在。
