# 2026-10-29 代码归档（上午 + 下午）

服务器项目根：`/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025`
Python 环境：`/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python`（sqlglot 30.23、vLLM 0.10.2）

## 上午：固定 k 外键一跳 + 隐藏 schema 严格口径复评

- `fixed_k_fk_20261029/scripts/`：变体生成、预测、可恢复评分、验证、分析与 PROTOCOL
- `fixed_k_fk_20261029/tail_parallel.py`、`tail_fix.sh`、`tail_fix2.sh`：4B 尾部慢查询的 12 路并行评分与合并
- `bridge_strict_20261029/`：`strict_rescore.py`（authorizer 严格复评）、`summarize_strict.py`、`run_strict.sh`
- `audit_numbers.py`：从原始 score 重算五组实验数字（固定 k、同预算、真列近义、严格口径、Spider），结果 0 处不一致
- `schema_check.py` / `schema_check2.py`：sqlglot 引用抽取原型与 authorizer 对照
- `authorizer_detect.py`：普通 top-k 组越界读检测（4B 32%、API 49%、2.5 Coder 27%）
- `汇报脚本/`：汇总报告 `build_report_docx.py` 与 20 行总表 `build_teacher_table_workspace.py`

## 下午：自校验补 schema 方法 v1

- `method_v1.py`：生成 SQL → authorizer 核验（sqlglot 兜底）→ 补 schema（最多 2 轮）→ 近名列样例值
- `method_v1_PROTOCOL.md`：预注册协议
- `aligned_variants.py`：按 C 组实测平均 token 反选 A/B 的整数 k
- `prep_c_variants.py`：把 C 的最终可见 schema 转成评分用 variants
- `score_strict_generic.py`：严格评分；`--permissive` 为宽松附表
- `analyze_method.py`：按题配对 bootstrap 1000 + 预注册判据
- `vllm_schema_gen.py`：vLLM 批量生成 A/B
- `shard_score.sh`、`shard_api.sh`、`permissive_score.sh`：分片评分脚本
- `build_method_report_docx.py`：方法实验报告生成
- `method_v1_preliminary_20261029.md`：初步结果说明
- `synonym30_review_filled.csv`：30 条近义列错误判读明细

## 运行注意

- API 模型（deepseek-chat）需要 `DEEPSEEK_API_KEY` 环境变量，不要写入任何文件。
- 评分脚本的 `--timeout` 本轮为 20 秒；严格模式默认只放行提示内 schema。
- 分片脚本里的绝对路径按服务器目录写死，本地复跑需改 `B=` 变量。

## 数据位置（代码不含预测与评分文件）

- 服务器：`method_c_130/`、`method_scores/`、`aligned_ab/`、`fixed_k_fk_20261029/scores/`、`bridge_strict_20261029/strict_all/`
- 本地归档：`~/Documents/deepseek-harness/6.1实验/server_archive_20261029/`（5.0 GB，含清单）
  与 `~/Documents/deepseek-harness/6.1实验/method_v1_20261029/`（29 MB）

## 复现顺序（方法 v1）

1. `method_v1.py --model-key <model> --start-k 8 --limit 500 --output ...`
2. `prep_c_variants.py --models <model>`
3. `aligned_variants.py --models <model>`
4. 本地模型用 `vllm_schema_gen.py`，API 用 `generate_budget_predictions.py`
5. `score_strict_generic.py`（严格）与 `--permissive`（附表）
6. `analyze_method.py --scores-dir method_scores --method-dir method_c_130 --out method_report.json`
