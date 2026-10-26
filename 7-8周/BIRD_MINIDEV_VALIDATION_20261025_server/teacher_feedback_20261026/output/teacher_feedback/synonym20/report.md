# API synonym20：30 条有效错误的逐条审阅

本报告完成模型辅助 SQL 审阅和只读 SQLite 复现。它未获得人工签字，语义有歧义的案例已单列，不能称为已完成独立人工确认。

原随机样本中 q116、q145 是 gold 查询超时，被错误混入“模型错误”样本。保留其历史记录并剔除，使用相同种子 20261026，从原样本之外的可评分错误中补入 q1457、q1105，最终 30 条均通过 gold 可执行性检查。

| 主分类 | 数量 | 占 30 条 |
| --- | ---: | ---: |
| 误选物理库不存在的生成列 | 26 | 86.67% |
| 输出投影不匹配 | 3 | 10.00% |
| SQL 生成不完整 | 1 | 3.33% |

26 条直接误选了提示词中新增、但物理 SQLite 不存在的同名列。它们的错误已在真实 SQLite 中复现，不是一个可执行、语义合理的近义列答案仅因与 gold 名称不同而被判错。其余 3 条有输出投影差异（q1145、q340、q341），1 条 SQL 生成不完整（q944）。q340 的原始评分还发生运行超时；本次复跑可执行，但 SELECT * 的 74 列输出仍与 gold 的单列输出不匹配。

## 近义列里有什么数据

生成器只向提示 schema 添加列元数据，没有 ALTER TABLE，也没有给这些列填充数据值。因此这组条件混合了 schema 名称歧义和提示 schema 与真实库不一致。`generated=True` 只是生成器的来源标记；少数名称碰巧已存在于物理表，不能说所有生成元数据列都物理不存在。此次对被认定误选的列分别检查了 PRAGMA table_info，26 条的直接失败列确实不存在。

本次 30 条中共核查 600 个新增列元数据条目；其中 11 个条目名称已存在于原物理表。这是按案例计数的元数据出现次数，并非全体 10,000 个干扰列的外推。

## gold / evidence / 题意疑点

下列疑点不与主失败分类互斥，也不能直接据此把当前不可执行预测改判为正确：

- q1254：同时存在金标准/证据边界歧义：evidence 为 IGA>80 且 <500、YEAR>=1990，gold 为 BETWEEN80AND500 且年份>1990，并且 gold 按化验行计数而非 DISTINCT患者。此项需人工复核，不能直接把合理边界解读认定模型推理错误。
- q1275：evidence 指示 (-,+-) 而 gold 使用 (negative,0)。实际 Laboratory 取值审计会列出原始编码；这一证据与金标准的编码矛盾需要人工确认，不影响当前预测因不存在列而无法执行的事实。
- q1322：另有 gold/题意问题：gold 对每个 Meeting 分组再 COUNT(DISTINCT event_id)，符合条件的每组都返回1；题目问“有多少个”，通常应再外层COUNT。预测外层COUNT的思路合理，修复连接后可用于人工复核，当前不应归为纯 gold 误判。
- q1387：“管理预算”与 expense 花费成员是否同义，题意本身可能需确认；但当前预测不存在列，不能作为可执行替代答案。
- q219：question/gold 计算“含三键分子中致癌分子比例”，但 evidence 给出“致癌分子中的三键比例”且按bond计数，条件方向与统计单位不同。需人工确认题意/evidence，当前预测不具备可执行等价答案资格。
- q260：gold 按 atom×bond 连接行数计数，题意也可理解为去重原子；当前数据匹配原子仅对应一个三键，未造成数值差异。
- q341：gold 的 OR 两端重复 cardKingdomId IS NULL，完全未检查 cardKingdomFoilId；结合题意/evidence 是疑似标注笔误。即便修正 gold，预测的 SELECT * 仍有投影不匹配。
- q726：自然语言 rank 可理解为排序，但 gold 显式返回排名列；这属于可能的输出形状歧义，不能抵消当前不存在列的错误。
- q92：题目 more than 6000 but less than 10000 对应严格边界，gold 使用闭区间 BETWEEN；需人工确认边界口径，但当前主要失败仍是不存在的列。
- q989：问题要求冠军是谁并给出时间，gold 仅返回 time，未输出司机姓名，是疑似输出标注不完整。仍不影响预测读取不存在列的直接失败事实。

优先复核 q1275（evidence 与物理数据编码不一致）、q1322（gold 每组输出 1 而问题问总数）、q219（条件方向和统计单位不一致）、q341（gold OR 两端重复同一条件）、q989（问题要求姓名和时间而 gold 仅返回时间）。所有疑点保留原标签，不据此修改主准确率。

## 可用于报告的结论

> 在 30 个可评分 API synonym20 错误中，26 个因引用提示中新增但物理库不存在的列而失败，3 个存在输出投影不匹配，1 个 SQL 生成不完整。该抽样说明 API 约 60% 的相对下降需要结合 schema 与执行库不一致解释，不能直接视为真实近义数据列下的语义推理退化。样本中还发现多处 gold/evidence 歧义，已记录待人工确认。该结果不等同于对全部错误做完整重标注，不能据此直接重算全部 500 题或其他模型的准确率。

## 30 条明细

| qid | 数据库 | 主分类 | 直接证据 | 人工语义确认 |
| ---: | --- | --- | --- | --- |
| 1036 | european_football_2 | 误选物理库不存在的生成列 | 预测把 Team_Attributes 的 date、buildUpPlayPassing 当作 Team 的列，二者均由 same_name 干扰生成且在 Team 物理表中不存在；省略所需连接导致编译失败。 | 未签字 |
| 1076 | european_football_2 | 误选物理库不存在的生成列 | 预测把 Player_Attributes.ball_control 当作 Player.ball_control，恰好对应生成的 same_name 干扰；物理 Player 没有该列。 | 未签字 |
| 1145 | european_football_2 | 输出投影不匹配 | 预测只读取真实列并可执行，和 gold 选择相同四个联赛；额外投影 COUNT(m.id) 使两列输出与 gold 的单列输出不匹配。 | 未签字 |
| 1155 | thrombosis_prediction | 误选物理库不存在的生成列 | Patient.LDH 来自 Laboratory.LDH 的 same_name 干扰，在 Patient 物理表中不存在。预测省略 Laboratory 连接。 | 未签字 |
| 1157 | thrombosis_prediction | 误选物理库不存在的生成列 | Patient.Thrombosis 来自 Examination.Thrombosis 的 same_name 干扰，物理 Patient 不含该列，直接编译失败。 | 未签字 |
| 1254 | thrombosis_prediction | 误选物理库不存在的生成列 | Patient.IGA 是 Laboratory.IGA 的 same_name 干扰，Patient 中不存在，预测首先编译失败。 | 待确认 |
| 1275 | thrombosis_prediction | 误选物理库不存在的生成列 | Patient.CENTROMEA 与 Patient.SSB 均来自 Laboratory 的 same_name 干扰，物理 Patient 中不存在。 | 待确认 |
| 1322 | student_club | 误选物理库不存在的生成列 | attendance.event_id 是从 event.event_id 生成的 same_name 干扰；真实连接列是 attendance.link_to_event，预测因此编译失败。 | 待确认 |
| 1387 | student_club | 误选物理库不存在的生成列 | 预测读取生成的 budget.event_name（来自 event.event_name）以及 member.link_to_budget；实际预算通过 expense 链接 member，当前查询首先在 budget.event_name 编译失败。 | 待确认 |
| 1422 | student_club | 误选物理库不存在的生成列 | 预测将 budget.category 的 same_name 干扰 event.category 当作物理列，省略 budget 连接；event.category 实际不存在。 | 未签字 |
| 1480 | debit_card_specializing | 误选物理库不存在的生成列 | yearmonth.Segment 是从 customers.Segment 生成的 same_name 干扰，实际不存在；预测省略 customers 连接。 | 未签字 |
| 219 | toxicology | 误选物理库不存在的生成列 | molecule.bond_type 是从 bond.bond_type 生成的 same_name 干扰，物理 molecule 中不存在，故查询无法执行。 | 待确认 |
| 260 | toxicology | 误选物理库不存在的生成列 | atom.bond_type 是从 bond.bond_type 生成的 same_name 干扰，物理 atom 中不存在，预测因此编译失败。 | 待确认 |
| 1457 | student_club | 误选物理库不存在的生成列 | 补样：expense.member_id 来自 member.member_id 的 same_name 干扰，真实 expense 使用 link_to_member，故 e.member_id 编译失败。 | 未签字 |
| 1105 | european_football_2 | 误选物理库不存在的生成列 | 补样：Player_Attributes.player_name 来自 Player.player_name 的 same_name 干扰，在实际 Player_Attributes 不存在；预测省略 Player 连接。 | 未签字 |
| 340 | card_games | 输出投影不匹配 | 预测 SELECT * 返回 cards 全部 74 列；gold 仅返回 id。原记录 interrupted 是运行时失败，实际筛选谓词与 gold 一致，符合条件 25,061 行。没有证据表明模型选择了某个不存在的生成近义列。 | 未签字 |
| 341 | card_games | 输出投影不匹配 | 预测 SELECT * 有 74 列，gold 只有 id；同时预测检查 foil 或普通 cardKingdomId 为空，比 gold 多 5 张牌。 | 待确认 |
| 41 | california_schools | 误选物理库不存在的生成列 | 把 satscores.AvgScrRead 的生成同名副本当作 schools 的真实列，省略连接，SQLite 编译失败。另有 ROW_NUMBER 替代 RANK、过滤 NULL 的潜在语义差异。 | 未签字 |
| 469 | card_games | 误选物理库不存在的生成列 | 使用由 sets.mtgoCode 复制而来的 cards.mtgoCode，同名列在真实 cards 表中不存在，编译失败。EXISTS 合并多个版本且 Yes/No 大小写也不同于 gold，修复列仍不保证通过。 | 未签字 |
| 5 | california_schools | 误选物理库不存在的生成列 | 使用由 satscores.AvgScrMath 复制的 schools.AvgScrMath，省略连接并计数所有行；SQLite 报不存在该列。 | 未签字 |
| 683 | codebase_community | 误选物理库不存在的生成列 | 使用 users.Reputation 的生成副本 posts.Reputation，省略 users 连接；在真实 posts 上无法编译。CreaionDate 是原库真实拼写，不能据此判成拼写错误。 | 未签字 |
| 726 | superhero | 误选物理库不存在的生成列 | 使用 publisher.publisher_name 的生成副本 superhero.publisher_name，省略 publisher 连接，SQLite 报不存在列；另外只排序，未输出 gold 的 RANK 列。 | 待确认 |
| 728 | superhero | 误选物理库不存在的生成列 | 使用不存在的 superhero.publisher_name；另以 eye_colour_id 分组输出 ID，gold 输出颜色名称、计数和 RANK，存在额外投影差异。 | 未签字 |
| 739 | superhero | 误选物理库不存在的生成列 | 把同名生成列分布在三张表中，再用 UNION 联合三个单表 SELECT；多列均为真实表中不存在的生成副本。SQL 也省略了 hero_power 连接关系。 | 未签字 |
| 758 | superhero | 误选物理库不存在的生成列 | 使用 race.race 的生成副本 superhero.race，真实 superhero 没有 race 文本列；且 human 与 gold 的 Human 大小写不同。 | 未签字 |
| 761 | superhero | 误选物理库不存在的生成列 | 使用 gender.gender 的生成副本 superhero.gender；权重阈值公式基本对应 gold，但无法在真实表编译。 | 未签字 |
| 92 | financial | 误选物理库不存在的生成列 | 使用 client.gender 的生成副本 district.gender，将地区误当含性别字段的实体，真实 district 中无该列。 | 待确认 |
| 944 | formula_1 | SQL 生成不完整 | raw_response 与 predicted_sql 均在 ON r_last.race 处终止；该 race 列不是本条件添加的生成列。SQL 输出不完整，SQLite 报 no such column。不能仅凭文本证明是 max_tokens 导致，原记录未保存 finish_reason。时间解析还把增量时间当成完整时刻，存在额外逻辑问题。 | 未签字 |
| 955 | formula_1 | 误选物理库不存在的生成列 | 把 races.year 的生成同名副本 results.year 用于 WHERE/GROUP BY；真实 results 无 year，省略 races 连接导致编译失败。 | 未签字 |
| 989 | formula_1 | 误选物理库不存在的生成列 | 使用 races.name 的生成副本 results.name；真实 results 无 name。即使迁移为真实 races.name，它也是赛事名，不能表示冠军车手姓名。 | 待确认 |

## 可复现文件

`cases.json` 保留原 SQL、真实库读列记录、编译错误、gold 执行和生成列血缘；`cases.csv` 供人工复核；`excluded_legacy_cases.json` 保存被剔除的两条 gold 超时案例。版本化审阅标注位于 `scripts/feedback/review_data/synonym20_review.json`。脚本核对 SQL SHA-256、问题/变体身份、seed 抽样、生成列来源、物理列是否存在和执行结果列数。
