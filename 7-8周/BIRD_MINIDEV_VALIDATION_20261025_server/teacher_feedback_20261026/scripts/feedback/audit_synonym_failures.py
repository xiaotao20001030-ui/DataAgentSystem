#!/usr/bin/env python3
"""Revalidate the fixed 30 eligible API synonym20 failures and their SQL review.

Review annotations are versioned in review_data/synonym20_review.json. They
are model-assisted review, not human sign-off. SQLite access is read-only.
"""

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sqlite3
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path(os.environ.get("BIRD_EXPERIMENT_ROOT", str(PROJECT_ROOT.parent))).expanduser()
DEFAULT_DATA_ROOT = Path(os.environ.get(
    "BIRD_DATA_ROOT", str(DEFAULT_ROOT.parent / "BIRD_MINIDEV_VALIDATION_20261013_server_old" / "data")
)).expanduser()
CATEGORY_NAMES = {
    'generated_nonexistent_column': '误选物理库不存在的生成列',
    'output_projection_mismatch': '输出投影不匹配',
    'incomplete_sql_generation': 'SQL 生成不完整',
}


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def sha256(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def unscorable(score):
    return bool(score.get('gold_unscorable')) or (score.get('error') or '').startswith('GoldUnscorable')


def open_database(path):
    connection = sqlite3.connect(f'file:{quote(str(path))}?mode=ro&immutable=1', uri=True)
    connection.execute('PRAGMA query_only=ON')
    return connection


def inspect_sql(path, sql, timeout, explain=False):
    reads = set()
    started = time.monotonic()
    connection = open_database(path)
    deadline = started + timeout
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 20000)

    def authorize(action, table, column, database, source):
        if action == sqlite3.SQLITE_READ:
            reads.add(f'{table}.{column}')
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)
    try:
        if not re.match(r'^\s*(SELECT|WITH)\b', sql, re.I):
            raise ValueError('Only SELECT/WITH queries are accepted')
        cursor = connection.execute(('EXPLAIN ' if explain else '') + sql)
        columns = [column[0] for column in cursor.description or []]
        count = 0
        samples = []
        for batch in iter(lambda: cursor.fetchmany(512), []):
            count += len(batch)
            if count > 200000:
                raise RuntimeError('Result exceeds 200000 rows')
            if not explain and len(samples) < 3:
                samples.extend([list(row[:8]) for row in batch[:3-len(samples)]])
        result = {'error': None, 'columns': columns if not explain else [],
                  'column_count': len(columns) if not explain else None,
                  'row_count': count if not explain else None,
                  'sample_rows_first_8_columns': samples}
    except Exception as exception:
        result = {'error': f'{type(exception).__name__}: {exception}'}
    finally:
        connection.close()
    result['reads'] = sorted(reads)
    return result


def physical_lineage(path, variant, review):
    connection = open_database(path)
    try:
        schema = {}
        for table in variant['schema']:
            name = table['table']
            escaped = '"' + name.replace('"', '""') + '"'
            schema[name.lower()] = {str(row[1]).lower() for row in connection.execute(f'PRAGMA table_info({escaped})')}
        added = []
        by_id = {}
        for item in variant['perturbation']['added']:
            entry = {'id': item['id'], 'relation': item.get('relation'),
                     'seed_column': item.get('seed_column'), 'generated': bool(item.get('generated')),
                     'exists_in_sqlite': item['column'].lower() in schema[item['table'].lower()]}
            added.append(entry)
            by_id[item['id'].lower()] = entry
        referenced = []
        for expected in review['referenced_generated_columns']:
            actual = by_id.get(expected['id'].lower())
            if actual is None or not actual['generated']:
                raise ValueError(f"q{review['question_id']}: reviewed column not in generated metadata: {expected['id']}")
            if actual['seed_column'] != expected['seed_column'] or actual['relation'] != expected['relation']:
                raise ValueError(f"q{review['question_id']}: generated column lineage changed: {expected['id']}")
            if actual['exists_in_sqlite']:
                raise ValueError(f"q{review['question_id']}: reviewed nonexistent column now exists: {expected['id']}")
            referenced.append(actual)
        return added, referenced
    finally:
        connection.close()


def revalidate(review, variants, scores, data_root, timeout):
    variant_id = review['variant_id']
    score = scores[variant_id]
    variant = variants[variant_id]
    qid = review['question_id']
    if score['question_id'] != qid or variant['question_id'] != qid or score['db_id'] != review['db_id']:
        raise ValueError(f'q{qid}: question/variant/database identity mismatch')
    if score['family'] != 'add_synonym_20' or score['correct']:
        raise ValueError(f'q{qid}: not a synonym20 failure')
    perturbation = variant['perturbation']
    if perturbation['family'] != 'add_synonym' or perturbation['level'] != 20:
        raise ValueError(f'q{qid}: wrong perturbation family or level')
    if unscorable(score) != review['excluded_legacy']:
        raise ValueError(f'q{qid}: gold-scorability status changed')
    if sha256(score['predicted_sql']) != review['predicted_sql_sha256']:
        raise ValueError(f'q{qid}: prediction changed since review')
    if sha256(variant['gold_sql']) != review['gold_sql_sha256'] or score['gold_sql'] != variant['gold_sql']:
        raise ValueError(f'q{qid}: gold SQL changed since review')
    path = data_root / variant['database_path']
    added, referenced = physical_lineage(path, variant, review)
    explain = inspect_sql(path, score['predicted_sql'], timeout, explain=True)
    predicted = inspect_sql(path, score['predicted_sql'], timeout)
    gold = ({'skipped': 'Legacy gold timeout; excluded from valid failure sample'}
            if review['excluded_legacy'] else inspect_sql(path, variant['gold_sql'], timeout))
    if not review['excluded_legacy']:
        if gold['error']:
            raise RuntimeError(f'q{qid}: cannot revalidate gold execution: {gold["error"]}')
        if review['category'] == 'generated_nonexistent_column':
            if not referenced or 'no such column' not in (explain['error'] or '').lower():
                raise ValueError(f'q{qid}: reviewed generated-column compile failure not reproduced')
        if review['category'] == 'output_projection_mismatch':
            if explain['error'] or predicted.get('column_count') == gold['column_count']:
                raise ValueError(f'q{qid}: reviewed output shape mismatch not reproduced')
        if review['category'] == 'incomplete_sql_generation' and not explain['error']:
            raise ValueError(f'q{qid}: incomplete SQL now compiles; review must be repeated')
    return {**review, 'question': variant['question'], 'evidence': variant.get('evidence') or '',
            'predicted_sql': score['predicted_sql'], 'gold_sql': variant['gold_sql'],
            'original_score_error': score.get('error'), 'original_gold_unscorable': unscorable(score),
            'predicted_explain': explain, 'predicted_execution': predicted, 'gold_execution': gold,
            'added_column_physical_audit': added, 'selected_generated_absent_columns': referenced,
            'human_reviewed': False}


def verify_sampling(fixture, all_scores):
    original_ids = fixture['original_sample_question_ids']
    initial = random.Random(fixture['seed']).sample(
        [row for row in all_scores if row['family'] == 'add_synonym_20' and not row['correct']], 30)
    initial_ids = [row['question_id'] for row in sorted(initial, key=lambda row: str(row['question_id']))]
    if initial_ids != original_ids:
        raise ValueError('Original seeded sample does not match the versioned review fixture')
    excluded = [row['question_id'] for row in initial if unscorable(row)]
    if set(excluded) != set(fixture['excluded_legacy_question_ids']):
        raise ValueError('Legacy exclusions changed')
    eligible = [row for row in all_scores if row['family'] == 'add_synonym_20'
                and not row['correct'] and not unscorable(row) and row['question_id'] not in original_ids]
    replacement_ids = [row['question_id'] for row in random.Random(fixture['seed']).sample(eligible, len(excluded))]
    if replacement_ids != fixture['replacement_question_ids']:
        raise ValueError('Seeded replacement draw does not match the versioned review fixture')


def render_report(summary, cases):
    lines = ['# API synonym20：30 条有效错误的逐条审阅', '',
             '本报告完成模型辅助 SQL 审阅和只读 SQLite 复现。它未获得人工签字，语义有歧义的案例已单列，不能称为已完成独立人工确认。', '',
             '原随机样本中 q116、q145 是 gold 查询超时，被错误混入“模型错误”样本。保留其历史记录并剔除，使用相同种子 20261026，从原样本之外的可评分错误中补入 q1457、q1105，最终 30 条均通过 gold 可执行性检查。', '',
             '| 主分类 | 数量 | 占 30 条 |', '| --- | ---: | ---: |']
    for category, name in CATEGORY_NAMES.items():
        count = summary['category_counts'].get(category, 0)
        lines.append(f'| {name} | {count} | {count/len(cases):.2%} |')
    lines += ['', '26 条直接误选了提示词中新增、但物理 SQLite 不存在的同名列。它们的错误已在真实 SQLite 中复现，不是一个可执行、语义合理的近义列答案仅因与 gold 名称不同而被判错。其余 3 条有输出投影差异（q1145、q340、q341），1 条 SQL 生成不完整（q944）。q340 的原始评分还发生运行超时；本次复跑可执行，但 SELECT * 的 74 列输出仍与 gold 的单列输出不匹配。', '',
              '## 近义列里有什么数据', '',
              '生成器只向提示 schema 添加列元数据，没有 ALTER TABLE，也没有给这些列填充数据值。因此这组条件混合了 schema 名称歧义和提示 schema 与真实库不一致。`generated=True` 只是生成器的来源标记；少数名称碰巧已存在于物理表，不能说所有生成元数据列都物理不存在。此次对被认定误选的列分别检查了 PRAGMA table_info，26 条的直接失败列确实不存在。', '',
              f"本次 30 条中共核查 {summary['added_metadata_column_occurrences']} 个新增列元数据条目；其中 {summary['added_metadata_occurrences_already_physical']} 个条目名称已存在于原物理表。这是按案例计数的元数据出现次数，并非全体 10,000 个干扰列的外推。", '',
              '## gold / evidence / 题意疑点', '',
              '下列疑点不与主失败分类互斥，也不能直接据此把当前不可执行预测改判为正确：', '']
    for case in cases:
        if case['needs_human_semantic_verification']:
            lines.append(f"- q{case['question_id']}：{case['gold_or_question_issue']}")
    lines += ['', '优先复核 q1275（evidence 与物理数据编码不一致）、q1322（gold 每组输出 1 而问题问总数）、q219（条件方向和统计单位不一致）、q341（gold OR 两端重复同一条件）、q989（问题要求姓名和时间而 gold 仅返回时间）。所有疑点保留原标签，不据此修改主准确率。', '',
              '## 可用于报告的结论', '',
              '> 在 30 个可评分 API synonym20 错误中，26 个因引用提示中新增但物理库不存在的列而失败，3 个存在输出投影不匹配，1 个 SQL 生成不完整。该抽样说明 API 约 60% 的相对下降需要结合 schema 与执行库不一致解释，不能直接视为真实近义数据列下的语义推理退化。样本中还发现多处 gold/evidence 歧义，已记录待人工确认。该结果不等同于对全部错误做完整重标注，不能据此直接重算全部 500 题或其他模型的准确率。', '',
              '## 30 条明细', '', '| qid | 数据库 | 主分类 | 直接证据 | 人工语义确认 |', '| ---: | --- | --- | --- | --- |']
    for case in cases:
        lines.append(f"| {case['question_id']} | {case['db_id']} | {CATEGORY_NAMES[case['category']]} | {case['analysis']} | {'待确认' if case['needs_human_semantic_verification'] else '未签字'} |")
    lines += ['', '## 可复现文件', '',
              '`cases.json` 保留原 SQL、真实库读列记录、编译错误、gold 执行和生成列血缘；`cases.csv` 供人工复核；`excluded_legacy_cases.json` 保存被剔除的两条 gold 超时案例。版本化审阅标注位于 `scripts/feedback/review_data/synonym20_review.json`。脚本核对 SQL SHA-256、问题/变体身份、seed 抽样、生成列来源、物理列是否存在和执行结果列数。', '']
    return '\n'.join(line.rstrip() for line in lines).rstrip() + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--data-root', type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument('--output-dir', type=Path, default=PROJECT_ROOT/'output/teacher_feedback/synonym20')
    parser.add_argument('--review-fixture', type=Path, default=Path(__file__).resolve().parent/'review_data/synonym20_review.json')
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    fixture = json.loads(args.review_fixture.read_text(encoding='utf-8'))
    scores_path = args.source_root/'model_eval/scores/api_control.jsonl'
    variants_path = args.source_root/'perturbations/output/mini_dev_perturbations.jsonl'
    all_scores = read_jsonl(scores_path)
    verify_sampling(fixture, all_scores)
    scores = {row['variant_id']: row for row in all_scores}
    variants = {row['variant_id']: row for row in read_jsonl(variants_path)}
    reviews = fixture['cases']
    if len(reviews) != 32 or len({row['question_id'] for row in reviews}) != 32:
        raise ValueError('Expected 30 eligible reviews and 2 legacy exclusions with unique question IDs')
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        inspected = list(pool.map(lambda row: revalidate(row, variants, scores, args.data_root, args.timeout), reviews))
    cases = [row for row in inspected if not row['excluded_legacy']]
    excluded = [row for row in inspected if row['excluded_legacy']]
    if len(cases) != 30 or len(excluded) != 2:
        raise ValueError('Valid/error sample denominator changed')
    counts = Counter(row['category'] for row in cases)
    summary = {'question_count': len(cases), 'legacy_excluded_count': len(excluded),
               'category_counts': dict(counts), 'gold_executions_revalidated': len(cases),
               'needs_human_semantic_verification': [row['question_id'] for row in cases if row['needs_human_semantic_verification']],
               'human_reviewed': False, 'seed': fixture['seed'],
               'replacement_question_ids': fixture['replacement_question_ids'],
               'excluded_legacy_question_ids': fixture['excluded_legacy_question_ids'],
               'added_metadata_column_occurrences': sum(len(row['added_column_physical_audit']) for row in cases),
               'added_metadata_occurrences_already_physical': sum(column['exists_in_sqlite'] for row in cases for column in row['added_column_physical_audit']),
               'source_scores_sha256': hashlib.sha256(scores_path.read_bytes()).hexdigest(),
               'source_variants_sha256': hashlib.sha256(variants_path.read_bytes()).hexdigest(),
               'review_fixture_sha256': hashlib.sha256(args.review_fixture.read_bytes()).hexdigest()}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    human_annotations = {}
    csv_path = args.output_dir/'cases.csv'
    if csv_path.exists():
        with csv_path.open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                human_annotations[row.get('variant_id')] = {
                    'human_verdict': row.get('human_verdict', ''),
                    'human_notes': row.get('human_notes', ''),
                }
    (args.output_dir/'cases.json').write_text(json.dumps({'summary': summary, 'cases': cases}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (args.output_dir/'excluded_legacy_cases.json').write_text(json.dumps({'reason': 'original gold queries unscorable; excluded from valid failure sample', 'cases': excluded}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    with csv_path.open('w', encoding='utf-8-sig', newline='') as handle:
        fields = ['question_id', 'variant_id', 'db_id', 'category', 'analysis', 'gold_or_question_issue',
                  'needs_human_semantic_verification', 'human_reviewed', 'question', 'evidence',
                  'predicted_sql', 'gold_sql', 'predicted_compile_error', 'referenced_generated_absent_columns',
                  'human_verdict', 'human_notes']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            row = {key: case[key] for key in fields if key in case}
            row.update(predicted_compile_error=case['predicted_explain']['error'],
                       referenced_generated_absent_columns='; '.join(item['id'] for item in case['selected_generated_absent_columns']),
                       **human_annotations.get(case['variant_id'], {'human_verdict': '', 'human_notes': ''}))
            writer.writerow(row)
    (args.output_dir/'report.md').write_text(render_report(summary, cases), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
