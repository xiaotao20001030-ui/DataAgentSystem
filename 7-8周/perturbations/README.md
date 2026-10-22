# BIRD Mini-Dev Schema 扰动集

该目录把 `mini_dev_data/mini_dev_sqlite.json` 的前 500 道题转换为可复现的
schema 扰动样本。所有变体共享原始问题、标准 SQL、数据库和答案。

## 生成方式

```bash
cd /Users/xiaotao/PycharmProjects/DataAgentSystem/7-8周
../.venv/bin/python perturbations/generate_perturbations.py
```

也可显式指定路径：

```bash
../.venv/bin/python perturbations/generate_perturbations.py \
  --data-root mini_dev_data \
  --output-dir perturbations/output
```

## 基线定义

基线 schema 只保留 gold SQL 实际引用的表和列。join 列属于 gold SQL 的显式
引用，因此包含在基线中。解析使用 `sqlglot`，并按 SQLite 方言执行
schema qualification。

## 扰动类别

| family | 含义 |
| --- | --- |
| `base` | gold SQL 所需表和列 |
| `add_random` | 加入 5/10/20/50 个随机列；优先使用真实未引用列，池不足时补中性合成列 |
| `add_synonym` | 加入 5/10/20/50 个与 gold 列同名或近义的合成列 |
| `missing_bridge_table` | 多表问题中删除一个桥接表 |
| `missing_fk_column` | 多表问题中删除一个关键 join/外键列 |
| `add_pure_column` | 只向 gold tables 加入无关列，不新增表；由 `generate_pure_column.py` 生成 |
| `add_pure_synonym` | 只加入词法近义列，不含 `same_name`；由 `generate_pure_column.py --include-pure-synonym` 生成 |

桥接表定义为：在 gold join 图上，删除该表后连通分量增加的顶点。
外键列优先使用 `dev_tables.json` 声明的 FK 侧；若 gold SQL 使用了未声明的
连接键，则退化为删除该关键边的一个连接列，并在记录中标记
`declared_foreign_key=false`。

## 输出

- `output/mini_dev_perturbations.jsonl`：所有基线及扰动变体。
- `output/question_structures.jsonl`：每题的表、列、join 边和桥接表分析。
- `output/summary.json`：数量、可扰动题数、输出 SHA-256。
- `output/validation_report.md`：便于查看的覆盖率和完整性检查报告。

随机列和近义列均使用以题号派生的固定随机种子 20261019。重复运行会得到
相同结果。每条新增列都带有 `generated` 和 `relation` 元数据，可以区分真实列、
同名合成列和近义合成列。

## 纯列补充条件

原 `add_random_*` 会从任意表采列，因此同时引入新表。`generate_pure_column.py`
生成只从 gold tables 采列的 `add_pure_column`，用于隔离“列数”本身：

```bash
../.venv/bin/python perturbations/generate_pure_column.py --levels 20
../.venv/bin/python perturbations/generate_pure_column.py   --levels 5,10,20   --output-dir perturbations/output/pure_column_5_10_20
```

输出文件同时包含 500 条 `base`，因此可以直接与新增条件一起生成预测、
评分和执行门槛，不需要再合并原始文件。`validation_report.md` 会记录真实列
与合成 filler 的比例，并验证所有新增列都属于 gold tables。
