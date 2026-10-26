# BIRD Mini-Dev Schema 扰动检查报告

- 题目数：500
- 数据库数：11
- 单表题：86
- 多表题：414
- 可生成桥接表扰动：91 题
- 可生成外键/连接键扰动：391 题
- 生成变体：5097 条
- 变体 ID 唯一：是
- 基线 schema qualification：500/500
- 固定随机种子：20261019
- JSONL SHA-256：`b1271267ebb3dcd4af584127422108f9eec304cbfd9ce150f998bbc04eb364e5`

## 变体数量

| family | 数量 |
| --- | ---: |
| add_random | 2000 |
| add_synonym | 2000 |
| base | 500 |
| missing_bridge_table | 103 |
| missing_fk_column | 494 |

## 缺失成分覆盖

- 414 道多表题中，396 道具有完整连接图。
- 91 道题的连接图存在桥接表。
- 391 道题存在关键外键/连接键列。
- `missing_fk_column` 共 494 条，其中 445 条来自显式外键定义，49 条为 gold join 回退。

## 输出文件

- `mini_dev_perturbations.jsonl`
- `question_structures.jsonl`
- `summary.json`
- `validation_report.md`
