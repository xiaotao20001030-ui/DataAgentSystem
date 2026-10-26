# synonym20 审阅标注

`synonym20_review.json` 是版本化的模型辅助 SQL 审阅标注，包含原始30条抽样的顺序、2条 gold 超时剔除、2条随机补样和32条审阅记录。它不是人工签字结果。

在本次反馈包根目录运行 `python scripts/feedback/audit_synonym_failures.py` 可核验源数据与标注是否仍一致。默认读取包的父目录（服务器主实验），物理数据库从 `BIRD_DATA_ROOT` 或兄弟旧归档的 `data/` 读取；可通过 `--source-root` 和 `--data-root` 指定其他路径。

脚本会核验问题与变体身份、SQL SHA-256、原抽样及补样种子、gold可评分状态、生成列来源和物理存在性、SQLite 编译和查询列数，再输出 `output/teacher_feedback/synonym20/` 下的报告与案例明细。所有 SQLite 访问均为只读。

`cases.csv` 的 `human_verdict`、`human_notes` 是供人工填写的列；同一变体重跑时会保留这两列。填写文本不会自动宣称全部案例已经人工确认。需修订 gold 或升级为人工定稿时，应另行确认、更新版本化标注和相关报告，不能静默修改源分数。
