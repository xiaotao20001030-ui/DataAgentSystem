# BIRD Mini-Dev 数据检查报告

- 问题数：500
- 数据库数：11
- sqlite3 验证通过：11/11
- 验证方式：每个数据库执行一条 gold SQL

| 数据库 | 问题数 | 描述文件 | 完整性 | 验证问题 | 输出行数 | 耗时 | 结果 |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| california_schools | 30 | 3 | ok | 5 | 1 | 7.17 ms | passed |
| card_games | 52 | 6 | ok | 340 | 25061 | 28.35 ms | passed |
| codebase_community | 49 | 8 | ok | 531 | 1 | 15.88 ms | passed |
| debit_card_specializing | 30 | 5 | ok | 1471 | 1 | 6.01 ms | passed |
| european_football_2 | 51 | 7 | ok | 1025 | 1 | 18.12 ms | passed |
| financial | 32 | 8 | ok | 89 | 1 | 4.58 ms | passed |
| formula_1 | 66 | 13 | ok | 846 | 5 | 4.32 ms | passed |
| student_club | 48 | 8 | ok | 1312 | 1 | 4.04 ms | passed |
| superhero | 52 | 10 | ok | 717 | 4 | 3.44 ms | passed |
| thrombosis_prediction | 50 | 3 | ok | 1149 | 1 | 3.58 ms | passed |
| toxicology | 40 | 4 | ok | 195 | 1 | 4.94 ms | passed |
