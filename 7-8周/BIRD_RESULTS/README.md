# BIRD Mini-Dev 已完成结果（本地副本）

本目录是服务器 `MINIDEV/BIRD_RESULTS` 的已完成部分同步，包含：

- `predictions_pure_column/`：五模型 × 1,000 条（base + add_pure_column_20）
- `scores_official_pure_column/`：BIRD 官方 set 语义评分
- `analysis/reanalysis/`：原始官方分数的 qid 对齐 gate、transition、
  synonym/random/real-synonym 分层
- `analysis/reanalysis_pure_column/`：纯列 20 的门槛与 baseline-correct
- `analysis/retrieval_matched_exact/`：用原始检索文档/标签复现的匹配基线
- `analysis/retrieval_matched_exact_qe/`：question+evidence 版本
- `analysis/missing_compliance/`：缺失 schema 的 authorizer 合规审计
- `scripts/`：服务器实际使用的 official scorer、分析脚本
- `logs/pure_column/`：纯列生成与评分日志

## 关键结果

纯列 20（只加列、不加表）全体准确率门槛仍不通过：

| 模型 | base | pure 20 | 下降差 vs DeepSeek | 95% CI |
| --- | ---: | ---: | ---: | --- |
| Qwen3-0.6B | 14.60% | 9.60% | +0.60pp | [-3.00, +4.20] |
| Qwen3-1.7B | 27.20% | 18.20% | +4.60pp | [+0.20, +9.00] |
| Qwen3-4B | 50.60% | 44.40% | +1.80pp | [-2.40, +6.00] |
| Qwen2.5-Coder-1.5B | 26.60% | 26.00% | -3.80pp | [-8.20, +0.40] |
| DeepSeek | 68.60% | 64.20% | 对照 | - |

baseline-correct 额外失败仍显著：+32.35/+34.13/+20.51/+10.00pp。

检索匹配基线（k=10，question-only）：桥接表内列比多表非桥接目标列低
13.91pp（CI [-24.22, -3.69]），外键列高 13.75pp（CI [+9.79, +17.73]）。

更完整的解释见 `result/POSTHOC_REANALYSIS_2026-10-22.md` 与
`result/BIRD_MiniDev_Experiment_Report_v2.md/.docx/.pdf`。
