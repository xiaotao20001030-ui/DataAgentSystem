# BIRD 扰动数据审计

## 原始扰动文件

```text
perturbations/output/mini_dev_perturbations.jsonl
SHA-256: b1271267ebb3dcd4af584127422108f9eec304cbfd9ce150f998bbc04eb364e5
```

服务器文件与本地项目、最终备份的 SHA-256 完全一致。

## 数量

- 总记录：5097
- 唯一 variant_id：5097
- base：500
- add_random_5/10/20/50：各 500
- add_synonym_5/10/20/50：各 500
- missing_bridge_table：103
- missing_fk_column：494

## 自动检查

以下检查全部通过，问题数 0：

- 每个新增条件正好 500 条
- 每个变体的 added 数量等于对应 level
- schema_columns 数量等于 gold columns + level
- schema_columns 无重复
- gold columns 全部保留在 schema 中
- added columns 全部出现在 schema 中
- 500 个 base question_id 全部唯一

## 当前模型输出检查

- JSONL 无效行：0
- family/question/db 与扰动源文件不匹配：0
- 空预测 SQL：0
- 模型生成过程 error：0
- 本地四个模型当前 variant_id：全部唯一
- DeepSeek 存在并发写入造成的重复记录，最终整理器会按 variant_id 去重

## 漏给实验检查

- 五个模型各完成 597 条预测和评分，共 2,985 条。
- 桥接表移除 103 条，外键列移除 494 条。
- 正式评分使用官方 set 语义和 30 秒超时，执行错误按 incorrect 记录，
  错误信息逐条保留。
- 所有完成评分的记录均通过 SQLite `EXPLAIN` 编译，并由 authorizer 记录实际
  读取的表和列。
- DeepSeek 173 条外键正确预测中 162 条仍读取被移除列；Qwen3-4B 为 92/100。
- 因此报告同时给出普通执行准确率与合规准确率，不能只报告前者。

## 官方重评分

- 27,620 条预测全部使用 BIRD 官方 `set(prediction) == set(gold)` 语义重评。
- 旧评分结果保留用于差异审计，不再用于论文正式数字。
- 逐条件差异见 `official_rescore_delta.csv`。
- 生成脚本已补齐 Python、Torch、CUDA 和 API seed；既有 greedy 预测没有重跑。

## 必须注意的构造定义

- 随机列优先使用真实但未被 gold SQL 使用的 schema 列。
- 某些小 schema 无法提供 50 个真实未使用列，因此原 50 列条件中存在少量合成
  随机列，并标记 `generated=true`。
- 合成近义列同样是 schema 元数据扰动，不对 SQLite 数据库做物理加列。
- 另行构造的 427 题真实 schema 近义列敏感性数据中，`generated` 数量为 0。

这些定义在正式报告里必须保留，不能把合成近义列结果直接等同于真实 schema 中
本来就存在同名列的影响。
