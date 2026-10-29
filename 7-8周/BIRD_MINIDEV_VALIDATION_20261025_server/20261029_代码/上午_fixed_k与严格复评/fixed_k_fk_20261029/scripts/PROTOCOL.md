# BIRD Mini Dev 固定 k 补充对照

本次补齐老师明确指定的固定组合，原有逐题同 token 上限、动态 k 实验保留为独立实验。

- 500 题，BAAI/bge-base-en-v1.5 同一份排名。
- 130 档固定普通 top12 对 top10 加声明外键一跳，不设逐题 token 上限。
- 标准 top-k 返回 min(k, 候选数) 列；小库不足 k 时保留全部候选，不剔除题目，实际种子数量和饱和题数写入元数据。
- 200 档在生成任何新预测前，只按 schema token 均值选定一个全体共用的整数 k 组合。最小化 `abs(mean_plain-200)+abs(mean_fk-200)+abs(mean_fk-mean_plain)`；平局按目标距离、差距、普通 k、外键种子 k 排序。完整候选表及选定值保存于 variants/summary.json。
- 公共计数使用 Qwen3-0.6B tokenizer，只计实际注入提示的 schema 文本；报告实际均值、分位数和差值，不称为逐题严格相同 token。
- 外键从原始种子列出发，补入声明外键另一端列，双向一跳、去重、不递归。
- 原有五模型、同一提示、temperature=0、max_new_tokens=256、seed=20261019；复用完全相同 question/evidence/schema 的既有预测，来源保存于逐条记录。
- 评分使用本次保存的 score_predictions_resumable.py，与原 BIRD 动态 k 实验一致：float 四舍五入至 8 位；gold SQL 包含 ORDER BY 时按序比较，否则按多重集合比较。此自定义口径不冒称官方 BIRD 集合比较。数据库只读。
- 仅复用 SQL、数据库和 gold 一致且无评分错误或超时的评分；其他重新执行。预测失败计错，gold 执行错误按问题成对剔除。
- 10 个模型/档位比较均报告配对执行准确率和外键减普通的 pp 差值，按题配对 bootstrap 10000 次，95% 区间，seed=20261029；报告成对分母，不做多重比较校正。
- 不以成绩改变 k、样本、判定口径。本表与 Spider SQLite 三条件重试并列汇报，不能将固定 k 与逐题同预算结果混为同一实验。
