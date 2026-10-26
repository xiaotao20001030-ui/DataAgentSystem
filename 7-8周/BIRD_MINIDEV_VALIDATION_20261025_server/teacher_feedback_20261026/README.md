# 老师反馈补充实验（2026-10-26）

本包放在 `7-8周/BIRD_MINIDEV_VALIDATION_20261025_server/teacher_feedback_20261026/`。父目录是主实验版本；本包保存今天新增的代码、结果和报告，直接读取父目录已有变体和评分。旧补实验继续保留在 [BIRD_MINIDEV_VALIDATION_20261013_server_old](../../BIRD_MINIDEV_VALIDATION_20261013_server_old/)。

## 阅读入口

- [老师反馈整合报告](report/实验报告_老师反馈整合版.md)与[完成清单](report/老师反馈完成清单.md)。
- [相对下降与配对区间](output/teacher_feedback/relative_execution/report.md)：random20 下 API 相对下降 9.33%，0.6B 下降 31.51%。
- [近义列构造核查](output/teacher_feedback/construction/audit_report.md)、[30 条失败审阅](output/teacher_feedback/synonym20/report.md)：26 条读取不存在的生成列、3 条投影不匹配、1 条 SQL 不完整。
- [18 条桥接表成功审计](output/teacher_feedback/bridge_api_successes/审计报告.md)：11 条读取隐藏桥接表、4 条使用其他未提供 schema、3 条仅访问可见 schema。
- [MiniLM/BGE 原假设对照](output/retrieval_fk/original_hypothesis_report.md)、[一跳扩展报告](output/retrieval_fk/fk_expansion_report.md)与[漏选率/token 曲线](output/retrieval_fk/fk_expansion_tradeoff.png)。

top-10 外键列相对单表列多漏选 MiniLM 29.14 pp、BGE 30.44 pp。外键一跳使桥接成分并集漏选率由 56.88%/61.05% 降至 37.79%/37.02%。这些是检索结果；下游 SQL 准确率与相同 token 预算比较尚待实验。

30 条案例为模型辅助 SQL 审阅，10 条题意或 gold 疑点保留人工确认栏。未据此修改 gold 或主准确率。

## 目录与数据来源

```text
../model_eval/{predictions,scores}/   主版本原始预测、评分
../perturbations/output/             主版本 5,097 变体及结构标签
scripts/feedback/                   今天新增的分析、审计和检索入口
scripts/feedback/review_data/        固定抽样身份和版本化审阅标注
scripts/score_predictions_official.py 可选的独立评分复核入口
output/teacher_feedback/            今天的构造核查、案例审计、相对下降
output/retrieval_fk/                MiniLM/BGE 排名、一跳结果、曲线
report/                            今天的报告与完成清单
tests/                             方法及评分续跑回归验证
```

本机数据库与元数据默认读取 `../../BIRD_MINIDEV_VALIDATION_20261013_server_old/data/`，SQLite 位置为 `dev_databases/<db>/sqlite/<db>.sqlite`。可用环境变量 `BIRD_DATA_ROOT` 或各命令的 `--data-root /absolute/path` 切换数据位置。模型和大型数据库不放进本包。

## 复现今天的分析

以下命令在本增量包目录执行，依赖见 `requirements.txt`。Python 需要已有 SQLite、NumPy 等依赖；检索另外需要本地模型、sentence-transformers 和生成 tokenizer。

```bash
python3 scripts/feedback/analyze_relative_execution.py \
  --scores-dir ../model_eval/scores
python3 scripts/feedback/teacher_feedback_audit.py --experiment-root ..
python3 scripts/feedback/audit_bridge_api_successes.py --experiment-root ..
python3 scripts/feedback/audit_synonym_failures.py --source-root ..
python3 -m unittest discover -s tests -v
```

换机器可先设置数据根目录，再执行以上命令：

```bash
export BIRD_DATA_ROOT=/absolute/path/to/data
```

重跑 MiniLM/BGE 检索需要两个模型和同一个 Qwen3-0.6B tokenizer。远程实验的本地模型位置如下；在其他机器上替换路径及 `--device`：

```bash
python3 scripts/feedback/retrieval_fk_expansion.py \
  --experiment-root .. \
  --models /root/fsas/home/xiaotao/xiaotao/models/all-MiniLM-L6-v2 \
           /root/fsas/home/xiaotao/xiaotao/MINIDEV/modules/bge-base-en-v1.5 \
  --tokenizer /root/fsas/home/xiaotao/xiaotao/MINIDEV/modules/Qwen3-0.6B \
  --device cuda:0
```

## 主评分与可选复核

主实验采用父目录 [model_eval/score_predictions.py](../model_eval/score_predictions.py) 的口径：浮点数保留 8 位，按结果元组集合比较。本报告的历史准确率仍使用该批次保存的评分。重跑时将结果写到本包的新目录：

```bash
python3 ../model_eval/score_predictions.py \
  --predictions ../model_eval/predictions/api_control.jsonl \
  --variants ../perturbations/output/mini_dev_perturbations.jsonl \
  --data-root "${BIRD_DATA_ROOT:-../../BIRD_MINIDEV_VALIDATION_20261013_server_old/data}" \
  --output-dir output/runs/server_score_recheck
```

本包的可选官方 scorer 使用精确元组集合比较，单列不可评分 gold，并检查续跑输入和评分版本。它用于独立复核；新旧浮点归一化与不可评分分母可能产生不同统计，应在新输出目录记录：

```bash
python3 scripts/score_predictions_official.py \
  --predictions ../model_eval/predictions/api_control.jsonl \
  --variants ../perturbations/output/mini_dev_perturbations.jsonl \
  --output-dir output/runs/official_score_recheck
```

旧 [pure-column 评分](../../BIRD_MINIDEV_VALIDATION_20261013_server_old/output/scores/)每模型 1,000 条，主实验每模型 5,097 条；分别保留各自批次与分母。
