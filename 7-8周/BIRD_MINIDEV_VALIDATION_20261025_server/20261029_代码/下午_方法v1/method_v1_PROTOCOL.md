# 自校验 + 按需补 schema 方法（method_v1）预注册协议

日期：2026-10-29
数据：BIRD Mini-Dev 500 题（`mini_dev_sqlite.json`，11 库）；全量 dev 1534 题（dev 2025-11-06）作为后续验证集，不参与本轮调参。

## 三种条件

| 组 | 输入 schema | 说明 |
|---|---|---|
| A 普通 top-k | BGE 排名的前 k 列 | 与 B/C 平均 schema token 对齐 |
| B top-k + 外键一跳 | A 的种子 k 列 + 声明外键对端列，双向一波、不递归 | 同上 |
| C 我们的方法 | 首轮同 A，之后按需补 schema | 补进来的 token 计入 C 的总 token |

## 方法（C）

1. 用首轮 schema 生成 SQL。
2. `sqlglot`（sqlite 方言）解析，抽取引用的表、列（解析别名、CTE，跳过子查询别名）。
3. 判定缺失：引用对象不在当前提示 schema 中，或 SQL 在只读库上执行报错。
4. 若缺失且轮次 < 2：把缺失的表名/列名文本作为查询，在本题数据库的 schema 列上做向量检索，补入命中的表和列，并附其声明外键对端；补入量每轮上限 30 token。重新生成。
5. 近名列提示：对当前 schema 中每一列，若库内存在同库近名列（列名 token Jaccard ≥ 0.5 或编辑相似度 ≥ 0.6），从该近名列取 5 个非空样例值放入提示，帮助模型按值选列；总提示值条目上限 20 列。

最多 2 轮补充（即最多 3 次生成）；第 3 次生成后不再补，直接打分。

## 对齐 token 的预注册规则

1. 先跑 C 的 20 题 × 5 模型 pilot，估计每题平均补充 token δ。
2. A/B 的首轮预算设为 T − δ，T 取 130 与 200 两档（与之前固定 k 实验一致）。
3. C 全量跑完后，用实际平均 token 重新选 A/B 的整数 k：最小化 `|mean_A − mean_C| + |mean_B − mean_C|`，平局按普通 k 小、种子 k 小排序；只依据 token 统计，不读取 gold 覆盖率或模型成绩。
4. 报告三组实际平均/中位数/P05–P95 token，并注明 C 的 token 含补入部分。

## 生成与评分

- 模型：Qwen3-0.6B / 1.7B / 4B、Qwen2.5-Coder-1.5B、deepseek-chat；同一提示模板，temperature=0，max_new_tokens=256。
- 严格评分：SQLite authorizer 只放行当前提示 schema（含 C 补入的对象）；越界读取判错；gold 超时不可评按题成对剔除。
- 宽松评分只作附表。
- 统计：按题配对 bootstrap 1000 次；预注册判据：至少 2 个小模型满足 `strict_EX(C) − strict_EX(A) ≥ 3 pp` 且 95% 区间下限 > 0。
- 每题记录：补了几轮、补了多少 token、验证拦截几次越界读取、最终 SQL 与评分。

## 交付

先在 Mini-Dev 500 上出初步数字（三组 × 5 模型 + 通过与否 + 补 schema 统计），老师确认后再上 dev 1534 全量。
