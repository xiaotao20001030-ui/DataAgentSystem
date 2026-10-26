#!/usr/bin/env python3
"""Trace API bridge-table successes against read-only SQLite databases."""

import argparse
import csv
import json
import os
import re
import sqlite3
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path(os.environ.get('BIRD_EXPERIMENT_ROOT', str(PROJECT_ROOT.parent))).expanduser()
DEFAULT_DATA_ROOT = Path(os.environ.get(
    'BIRD_DATA_ROOT', str(DEFAULT_ROOT.parent / 'BIRD_MINIDEV_VALIDATION_20261013_server_old' / 'data')
)).expanduser()

CASE_NOTES = {
    1028: '读取隐藏 Match 表，按客场胜场数统计球队；evidence 暴露 away_team_api_id、进球及 season 列名。',
    862: '读取隐藏 results 表；省略 drivers 连接，使用 COUNT(*)，当前结果均为 12。',
    895: '直接读取隐藏 lapTimes 表，AVG(milliseconds) 与 gold 相同；evidence 给出 milliseconds。',
    933: '直接读取隐藏 results 表的 positionOrder；evidence 给出该列名，当前结果为 1。',
    954: '读取隐藏 results 表，以 COUNT(CASE...) 改写 SUM(IIF...)，当前结果相同。',
    981: '以未提供的 results 表替代隐藏 qualifying；把首次参加比赛当作首次排位赛，当前两者恰好都是 2017 中国站，不构成普遍等价。qualifying 在题目/evidence 中是自然语言词。',
    990: '读取隐藏 results，使用未给出的 positionOrder=1 替代 gold 的冠军时间格式条件，当前都得到 McLaren。',
    994: '以未提供的 results 表替代 constructorResults，按车手比赛积分汇总车队积分，当前都得到 McLaren 218.5 分；未证明所有年份/车队均等价。',
    1003: '读取隐藏 results，以 statusId=3 筛事故并按司机分组，当前最大事故数为 2。',
    723: '在子查询中读取隐藏 superhero 表的眼色信息，当前计数为 83；evidence 给出 eye_colour_id。',
    733: '读取隐藏 superhero 表并用子查询筛颜色和出版社，当前计数为 2。',
    772: '直接读取隐藏 superhero 表，返回五行颜色 ID；evidence 给出三种颜色列名。',
    775: '读取隐藏 superhero 表，LEFT JOIN 改写 gold 的 INNER JOIN，当前比例相同；未证明空值/缺失关联下普遍等价。',
    633: '使用未给出的 posts.OwnerUserId 直接连接 users，绕过 postHistory。发帖者与历史操作人并非同一关系，当前都返回帖子 351。',
    637: '使用未给出的 posts.OwnerUserId；预测 2 行、gold 5 行，去重后同为两个值，符合现有集合评分，但不满足多重集合一致。',
    260: '只用可见列，以 atom.molecule_id 和 bond.molecule_id 关联，省去 molecule；IN 消除 bond 重复，当前唯一匹配原子 TR499_2 也仅对应一个三键，所以都计为 1，额外三键会改变 gold 的重复计数。',
    263: '只用可见列，直接连接 atom 与 bond，省去 molecule；当前 molecule_id 唯一且无孤儿记录，因此冗余桥接表可被省去，比例均为约 2.684%。',
    149: '只用可见列，但错误地令 disp.account_id=district.district_id，跳过实际账户所属地区。预测 DISTINCT 仅返回 DISPONENT；gold 461 行也全为 DISPONENT，因此集合评分判对。',
}

CATEGORY_NAMES = {
    'reads_hidden_bridge_table': '读取隐藏桥接表',
    'alternative_uses_unprovided_schema': '改走其他未提供的表或列',
    'uses_only_visible_schema': '只使用可见 schema',
}


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def connect(path):
    return sqlite3.connect(f'file:{quote(str(path))}?mode=ro&immutable=1', uri=True, cached_statements=0)


def trace(path, sql, hidden, visible=None):
    reads, denied = set(), []
    connection = connect(path)

    def authorize(action, table, column, database, source):
        if action == sqlite3.SQLITE_READ:
            table, column = (table or '').lower(), (column or '').lower()
            reads.add((table, column))
            if visible is not None and (table not in visible or (column and column not in visible[table])):
                denied.append(f'{table}.{column}')
                return sqlite3.SQLITE_DENY
            if visible is None and table in hidden and hidden[table]:
                denied.append(f'{table}.{column}')
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)
    try:
        connection.execute('EXPLAIN ' + sql).fetchall()
        error = None
    except sqlite3.Error as exception:
        error = str(exception)
    finally:
        connection.close()
    return {'reads': sorted(f'{table}.{column}' for table, column in reads),
            'tables_read': sorted({table for table, _ in reads}),
            'denied': denied, 'error': error}


def execute(path, sql, timeout):
    connection = connect(path)
    deadline = time.monotonic() + timeout
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 20000)
    try:
        rows = connection.execute(sql).fetchmany(200001)
        if len(rows) > 200000:
            raise ValueError('result exceeds 200000 rows')
        normalized = [tuple(round(value, 8) if isinstance(value, float) else value for value in row) for row in rows]
        return {'row_count': len(rows), 'unique_row_count': len(set(normalized)),
                'sample_rows': rows[:8], 'normalized': normalized, 'error': None}
    except Exception as exception:
        return {'error': f'{type(exception).__name__}: {exception}'}
    finally:
        connection.close()


def mentions(name, text):
    return bool(re.search(r'(?<![a-z0-9_])' + re.escape(name) + r'(?![a-z0-9_])', text, re.I))


def inspect_case(score, variant, data_root, timeout):
    path = data_root / variant['database_path']
    hidden = {item['id'].lower(): False for item in variant['perturbation']['removed'] if item['kind'] == 'table'}
    visible = {table['table'].lower(): {column['name'].lower() for column in table['columns']}
               for table in variant['schema']}
    traced = trace(path, score['predicted_sql'], hidden)
    hidden_deny = trace(path, score['predicted_sql'], {table: True for table in hidden})
    strict = trace(path, score['predicted_sql'], hidden, visible)
    outside = []
    for read in traced['reads']:
        table, column = read.split('.', 1)
        if table not in visible or (column and column not in visible[table]):
            outside.append(read)
    used_hidden = sorted(set(traced['tables_read']) & set(hidden))
    if used_hidden:
        category = 'reads_hidden_bridge_table'
    elif outside:
        category = 'alternative_uses_unprovided_schema'
    else:
        category = 'uses_only_visible_schema'
    predicted = execute(path, score['predicted_sql'], timeout)
    gold = execute(path, variant['gold_sql'], timeout)
    set_match = multiset_match = None
    if not predicted['error'] and not gold['error']:
        set_match = set(predicted['normalized']) == set(gold['normalized'])
        multiset_match = Counter(predicted['normalized']) == Counter(gold['normalized'])
    for result in (predicted, gold):
        result.pop('normalized', None)
    removed_columns = sorted({column.split('.', 1)[1] for item in variant['perturbation']['removed']
                              for column in item.get('columns', [])})
    return {'variant_id': score['variant_id'], 'question_id': score['question_id'],
            'db_id': score['db_id'], 'question': variant['question'], 'evidence': variant.get('evidence') or '',
            'hidden_tables': sorted(hidden), 'visible_schema': variant['schema'],
            'gold_sql': variant['gold_sql'], 'predicted_sql': score['predicted_sql'],
            'category': category, 'tables_read': traced['tables_read'],
            'used_hidden_tables': used_hidden, 'outside_visible_schema_reads': outside,
            'trace_error': traced['error'], 'hidden_table_deny_test': hidden_deny,
            'visible_schema_only_test': strict,
            'question_hidden_name_tokens': [table for table in hidden if mentions(table, variant['question'])],
            'evidence_hidden_name_tokens': [table for table in hidden if mentions(table, variant.get('evidence') or '')],
            'evidence_removed_column_tokens': [column for column in removed_columns if mentions(column, variant.get('evidence') or '')],
            'predicted_execution': predicted, 'gold_execution': gold,
            'reproduced_set_match': set_match, 'reproduced_multiset_match': multiset_match,
            'original_gold_row_count': score.get('gold_row_count'),
            'original_predicted_row_count': score.get('predicted_row_count'),
            'case_analysis': CASE_NOTES.get(score['question_id'], '待逐条审阅')}


def targeted_diagnostics(data_root):
    queries = {
        'toxicology': {
            'molecule_key_duplicates': 'SELECT COUNT(*)-COUNT(DISTINCT molecule_id) FROM molecule',
            'atom_orphan_molecules': 'SELECT COUNT(*) FROM atom a WHERE NOT EXISTS (SELECT 1 FROM molecule m WHERE m.molecule_id=a.molecule_id)',
            'bond_orphan_molecules': 'SELECT COUNT(*) FROM bond b WHERE NOT EXISTS (SELECT 1 FROM molecule m WHERE m.molecule_id=b.molecule_id)',
            'q260_matching_atoms_and_triple_bonds': "SELECT a.atom_id,a.molecule_id,COUNT(*) FROM atom a JOIN bond b ON a.molecule_id=b.molecule_id WHERE b.bond_type='#' AND a.element IN ('p','br') GROUP BY a.atom_id,a.molecule_id",
        },
        'financial': {
            'q149_correct_join_counts': "SELECT COUNT(*),COUNT(DISTINCT d.account_id) FROM disp d JOIN account a ON d.account_id=a.account_id JOIN district di ON a.district_id=di.district_id WHERE d.type<>'OWNER' AND di.A11 BETWEEN 8000 AND 9000",
            'q149_wrong_join_with_actual_district': "SELECT d.account_id,di.district_id,di.A11,a.district_id,actual.A11 FROM disp d JOIN district di ON d.account_id=di.district_id JOIN account a ON a.account_id=d.account_id JOIN district actual ON a.district_id=actual.district_id WHERE d.type<>'OWNER' AND di.A11>8000 AND di.A11<=9000",
        },
    }
    result = {}
    for database, items in queries.items():
        path = data_root / 'dev_databases' / database / 'sqlite' / f'{database}.sqlite'
        result[database] = {key: {'sql': sql, 'execution': execute(path, sql, 30)} for key, sql in items.items()}
    return result


def render_report(summary, cases):
    lines = ['# API 隐藏桥接表实验：18 个执行成功案例审计', '',
             '已逐条读取 SQL，并通过 SQLite authorizer 的 EXPLAIN 记录实际访问的表和列；同时复跑预测和 gold，复现全部 18 个集合匹配成功。所有数据库以只读方式打开。', '',
             '原分母：103 个变体，4 个 gold 不可评分；18/99=18.18%。以下结果说明这 18 个成功的来源。', '',
             '| 来源 | 数量 | 占 18 个成功 |', '| --- | ---: | ---: |']
    for category, name in CATEGORY_NAMES.items():
        number = summary['categories'].get(category, 0)
        lines.append(f'| {name} | {number} | {number/len(cases):.2%} |')
    lines += ['', '在 SQL 准备阶段禁止读取隐藏表，11 条被拒绝，剩余 7 条；进一步禁止读取任何提示词未提供的表或列，4 条额外被拒绝，仅 3 条通过。因此，“遵守可见 schema 且结果集合匹配”的成功率是 3/99=3.03%，它仍不能等同于语义正确率。', '',
              '## 3 个只使用可见 schema 的案例', '',
              '- q260：原子表和键表共享 molecule_id，可绕过 molecule；当前匹配原子只有一个三键，IN 与 gold 的连接计数一致。若同分子增加另一个三键，gold 可能重复计数，因此不能宣称通用等价。',
              '- q263：直接按 molecule_id 连接 atom 与 bond。诊断确认 molecule_id 唯一，atom 和 bond 均无找不到 molecule 的记录，所以当前数据中省略 molecule 不改变结果。',
              '- q149：错误连接账户 ID 与地区 ID。gold 返回 461 行 DISPONENT，预测 DISTINCT 返回 1 行 DISPONENT；结果集合相同，但筛选的账户并不相同。这是低信息输出造成的集合匹配假阳性，不能视为有效替代路径。', '',
              'q637 同样因去重而匹配：预测 2 行、gold 5 行，唯一值同为 `<books>` 与 NULL。现有评分采用集合语义，这符合原评分规则；它不能证明查询在语义上等价。', '',
              '## question / evidence 是否泄露隐藏表名', '',
              '只有 q981 的 qualifying 与 q149 的 account 在 question/evidence 中出现完整同名词，均为自然语言用词；未发现这 18 条 evidence 以 `隐藏表.列名` 的形式直接写出隐藏表标识。多条 evidence 保留了隐藏列名，例如 q895 的 milliseconds、q933 的 positionOrder、q772 的颜色列名。', '',
              'SQL 访问记录能够证明模型引用了未提供的 schema；它无法区分模型是从语义线索推断、猜测还是已有知识中恢复了表名。不能将全部 11 条直接归因于记忆或某种确定的“泄漏”机制。', '',
              '## 逐条结论', '', '| question_id | 数据库 | 隐藏表 | 类型 | 审阅结论 |', '| ---: | --- | --- | --- | --- |']
    for case in cases:
        lines.append(f"| {case['question_id']} | {case['db_id']} | {', '.join(case['hidden_tables'])} | {CATEGORY_NAMES[case['category']]} | {case['case_analysis']} |")
    lines += ['', '## 可用于修订报告的表述', '',
              '> missing_bridge_table 条件仅从提示 schema 隐藏表，原数据库保留全部数据。API 在 99 个可评分变体中有 18 个结果集合匹配成功。其中 11 个读取隐藏桥接表，4 个使用其他未提供的表或列，只有 3 个完全遵守可见 schema；这 3 个中又有 1 个明显错误连接因输出值重复而被判对。因此 18.18% 体现的是完整数据库上的执行集合匹配成功率，不能直接解释为在严格 schema 缺失约束下的推理成功率。', '',
              '建议保留原执行指标，另报 schema 合规指标与误匹配案例。先对预测加 SQLite 访问限制即可验证这些失败，不需要为此次核查物理删除源数据库表。', '',
              '## 每条 SQL 与复现记录', '']
    for case in cases:
        lines += [f"### q{case['question_id']} — {case['db_id']}", '',
                  f"问题：{case['question']}", '', f"Evidence：{case['evidence']}", '',
                  f"隐藏表：{', '.join(case['hidden_tables'])}；类型：{CATEGORY_NAMES[case['category']]}", '',
                  '预测：', '```sql', case['predicted_sql'], '```', '', 'Gold：', '```sql', case['gold_sql'], '```', '',
                  f"实际读取：{', '.join(case['tables_read'])}。", '',
                  f"预测行数 / 唯一行数：{case['predicted_execution'].get('row_count')} / {case['predicted_execution'].get('unique_row_count')}；gold：{case['gold_execution'].get('row_count')} / {case['gold_execution'].get('unique_row_count')}。", '',
                  f"隐藏表禁读检查：{case['hidden_table_deny_test']['error'] or '通过'}；仅可见 schema 检查：{case['visible_schema_only_test']['error'] or '通过'}。", '', case['case_analysis'], '']
    return '\n'.join(line.rstrip() for line in lines).rstrip() + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment-root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--data-root', type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument('--output-dir', type=Path, default=PROJECT_ROOT / 'output/teacher_feedback/bridge_api_successes')
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    variants = {record['variant_id']: record for record in read_jsonl(args.experiment_root / 'perturbations/output/mini_dev_perturbations.jsonl')}
    scores = [record for record in read_jsonl(args.experiment_root / 'model_eval/scores/api_control.jsonl')
              if record['family'] == 'missing_bridge_table']
    successful = [record for record in scores if record['correct']]
    with ThreadPoolExecutor(max_workers=4) as pool:
        cases = list(pool.map(lambda score: inspect_case(score, variants[score['variant_id']], args.data_root, args.timeout), successful))
    summary = {'total_bridge_variants': len(scores),
               'unscorable_gold': sum(bool(record.get('gold_unscorable')) for record in scores),
               'original_successes': len(successful),
               'categories': dict(Counter(case['category'] for case in cases)),
               'trace_errors': sum(bool(case['trace_error']) for case in cases),
               'set_matches_reproduced': sum(case['reproduced_set_match'] is True for case in cases),
               'unreproduced_or_errors': [case['question_id'] for case in cases if case['reproduced_set_match'] is not True],
               'multiset_mismatches_among_set_matches': [case['question_id'] for case in cases if case['reproduced_set_match'] and not case['reproduced_multiset_match']],
               'cases_with_question_hidden_name_token': [case['question_id'] for case in cases if case['question_hidden_name_tokens']],
               'cases_with_evidence_hidden_name_token': [case['question_id'] for case in cases if case['evidence_hidden_name_tokens']]}
    summary['hidden_table_denials'] = sum(bool(case['hidden_table_deny_test']['denied']) for case in cases)
    summary['visible_schema_denials'] = sum(bool(case['visible_schema_only_test']['denied']) for case in cases)
    summary['visible_schema_only_successes'] = sum(not case['visible_schema_only_test']['error'] for case in cases)
    diagnostics = targeted_diagnostics(args.data_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'audit.json').write_text(json.dumps({'summary': summary, 'cases': cases, 'targeted_diagnostics': diagnostics}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    fields = ['question_id', 'variant_id', 'db_id', 'category', 'hidden_tables', 'tables_read',
              'used_hidden_tables', 'outside_visible_schema_reads', 'question_hidden_name_tokens',
              'evidence_hidden_name_tokens', 'evidence_removed_column_tokens',
              'reproduced_set_match', 'reproduced_multiset_match', 'case_analysis', 'question', 'evidence', 'predicted_sql', 'gold_sql']
    with (args.output_dir / 'cases.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            writer.writerow({field: '; '.join(case[field]) if isinstance(case[field], list) else case[field] for field in fields})
    (args.output_dir / '审计报告.md').write_text(render_report(summary, cases), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
