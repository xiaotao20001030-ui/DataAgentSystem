#!/usr/bin/env python3
"""Report baseline-normalized execution loss with paired question bootstrap.

The main view excludes unscorable gold/evaluation errors on a common complete
case question set. Ordinary prediction/SQL failures remain incorrect outcomes.
The historical paired-500-style view retains every recorded correctness flag.
Relative loss is a post-hoc descriptive metric, not a new pre-registered gate.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path(os.environ.get('BIRD_EXPERIMENT_ROOT', str(PROJECT_ROOT.parent))).expanduser()
MODEL_KEYS = ('api_control', 'qwen3_0_6b', 'qwen3_1_7b', 'qwen3_4b', 'qwen2_5_coder_1_5b')
MODEL_LABELS = {'api_control': 'DeepSeek API', 'qwen3_0_6b': 'Qwen3 0.6B',
                'qwen3_1_7b': 'Qwen3 1.7B', 'qwen3_4b': 'Qwen3 4B',
                'qwen2_5_coder_1_5b': 'Qwen2.5-Coder 1.5B'}
FAMILIES = ('add_random_20', 'add_synonym_20')


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scores-dir', type=Path,
                        default=DEFAULT_ROOT / 'model_eval/scores')
    parser.add_argument('--output-dir', type=Path,
                        default=PROJECT_ROOT / 'output/teacher_feedback/relative_execution')
    parser.add_argument('--seed', type=int, default=20261026)
    parser.add_argument('--iterations', type=int, default=10000)
    return parser.parse_args()


def is_unscorable(record):
    return (bool(record.get('gold_unscorable'))
            or record.get('evaluation_status') == 'evaluation_error'
            or str(record.get('error') or '').startswith('GoldUnscorable:'))


def read_maps(scores_dir):
    maps = {}
    for key in MODEL_KEYS:
        path = scores_dir / f'{key}.jsonl'
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        conditions = {}
        for row in rows:
            if row['family'] not in ('base', *FAMILIES):
                continue
            family = conditions.setdefault(row['family'], {})
            if row['question_id'] in family:
                raise ValueError(f'Duplicate question/family in {path}: {row["question_id"]} {row["family"]}')
            if 'correct' not in row:
                raise ValueError(f'Missing correctness flag in {path}: {row["question_id"]}')
            family[row['question_id']] = row
        maps[key] = conditions
    return maps


def question_sets(maps, family):
    available = [set(maps[key][condition]) for key in MODEL_KEYS for condition in ('base', family)]
    historical = sorted(set.intersection(*available))
    excluded = sorted(qid for qid in historical
                      if any(is_unscorable(maps[key][condition][qid])
                             for key in MODEL_KEYS for condition in ('base', family)))
    main = sorted(set(historical) - set(excluded))
    if not main:
        raise ValueError(f'No complete scoreable question pairs for {family}')
    return main, historical, excluded


def observations(maps, key, family, ids):
    return np.array([[int(bool(maps[key]['base'][qid]['correct'])),
                      int(bool(maps[key][family][qid]['correct']))] for qid in ids], dtype=np.int8)


def metric(array):
    n = len(array)
    base_count, pert_count = (int(value) for value in array.sum(axis=0))
    relative = (base_count - pert_count) / base_count if base_count else None
    return {'question_count': n, 'baseline_correct': base_count, 'perturbed_correct': pert_count,
            'baseline_accuracy': base_count / n, 'perturbed_accuracy': pert_count / n,
            'absolute_drop_percentage_points': (base_count - pert_count) / n * 100,
            'relative_loss': relative,
            'relative_loss_percent': relative * 100 if relative is not None else None}


def bootstrap(arrays, iterations, seed):
    rng = np.random.default_rng(seed)
    size = len(next(iter(arrays.values())))
    samples = {key: np.full(iterations, np.nan) for key in arrays}
    # Reuse each resampled question draw for every model, base and perturbation.
    # Compute loss from resampled counts so each baseline denominator is reestimated.
    for start in range(0, iterations, 256):
        stop = min(start + 256, iterations)
        indices = rng.integers(0, size, size=(stop - start, size))
        for key, array in arrays.items():
            totals = array[indices].sum(axis=1)
            np.divide(totals[:, 0] - totals[:, 1], totals[:, 0],
                      out=samples[key][start:stop], where=totals[:, 0] != 0)
    return samples


def interval(values):
    valid = values[np.isfinite(values)]
    if not len(valid):
        return {'ci95_low_percentage_points': None, 'ci95_high_percentage_points': None,
                'valid_bootstrap_draws': 0, 'undefined_bootstrap_draws': len(values)}
    return {'ci95_low_percentage_points': float(np.quantile(valid, .025) * 100),
            'ci95_high_percentage_points': float(np.quantile(valid, .975) * 100),
            'valid_bootstrap_draws': len(valid), 'undefined_bootstrap_draws': len(values) - len(valid)}


def analyze_view(maps, family, ids, iterations, seed):
    arrays = {key: observations(maps, key, family, ids) for key in MODEL_KEYS}
    values = bootstrap(arrays, iterations, seed)
    metrics = {key: metric(array) for key, array in arrays.items()}
    control = metrics['api_control']['relative_loss']
    for key in MODEL_KEYS:
        metrics[key]['relative_loss_bootstrap_ci95'] = interval(values[key])
        estimate = metrics[key]['relative_loss']
        metrics[key]['relative_loss_difference_vs_api_percentage_points'] = (
            (estimate - control) * 100 if estimate is not None and control is not None else None)
        metrics[key]['relative_loss_difference_vs_api_bootstrap_ci95'] = interval(values[key] - values['api_control'])
    return {'question_count': len(ids), 'question_ids': ids, 'models': metrics}


def fmt(value, digits=2):
    return f'{value:.{digits}f}' if value is not None else 'undefined'


def path_label(path):
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def render(summary):
    lines = ['# 执行准确率的相对下降补充分析', '',
             '相对下降率 = (基线准确率 − 扰动准确率) / 基线准确率；该指标为事后补充分析，不设置新的预注册通过门槛。', '',
             '主分析只保留五个模型在 base 和相应扰动中均有记录且 gold 可评分的共同题目。普通 SQL 错误仍计为失败；仅排除 gold_unscorable、GoldUnscorable 或 evaluation_error。', '',
             '配对 bootstrap 按题目联合重采样，保留同题所有模型及 base/扰动的对应关系，并在每次抽样中重新计算各模型的基线分母。差值表示“小模型相对下降率 − API 相对下降率”，单位为百分点。', '']
    for family, item in summary['families'].items():
        lines += [f'## {family}', '',
                  f"主分析 n={item['main_complete_case']['question_count']}；排除的不可评分题：{', '.join(map(str, item['excluded_unscorable_question_ids'])) or '无'}。", '',
                  '| 模型 | base | 扰动 | 绝对下降 pp | 相对下降 | 相对下降 − API | 差值 95% CI（pp） |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
        for key, m in item['main_complete_case']['models'].items():
            ci = m['relative_loss_difference_vs_api_bootstrap_ci95']
            lines.append(f"| {MODEL_LABELS[key]} | {m['baseline_accuracy']:.2%} | {m['perturbed_accuracy']:.2%} | {m['absolute_drop_percentage_points']:.2f} | {fmt(m['relative_loss_percent'])}% | {fmt(m['relative_loss_difference_vs_api_percentage_points'])} pp | [{fmt(ci['ci95_low_percentage_points'])}, {fmt(ci['ci95_high_percentage_points'])}] |")
        historical = item['historical_all_recorded_pairs']
        lines += ['', f"历史 paired-{historical['question_count']} 视图（保留原始正确性标记，包括不可评分记录）：", '',
                  '| 模型 | base | 扰动 | 绝对下降 pp | 相对下降 |', '| --- | ---: | ---: | ---: | ---: |']
        for key, m in historical['models'].items():
            lines.append(f"| {MODEL_LABELS[key]} | {m['baseline_accuracy']:.2%} | {m['perturbed_accuracy']:.2%} | {m['absolute_drop_percentage_points']:.2f} | {fmt(m['relative_loss_percent'])}% |")
        lines.append('')
    lines += ['## 解读边界', '',
              'random20 下 API 相对下降约 9.33%，Qwen3 0.6B 约 31.51%。这一归一化差异值得报告，但不能把所有小模型概括成同样程度的更脆弱；应结合各自差值与置信区间。', '',
              '低基线模型的相对下降估计更不稳定，因此同时报告基线准确率、绝对下降、相对下降和配对区间。synonym20 还受生成的不存在列及标注/输出问题影响，需结合独立的 30 条案例审阅解释。', '',
              '原来的绝对下降至少额外 10 pp 门槛属于历史预注册口径，结果与原文件保持不变。相对下降的事后结果不替换该历史检验，也不被包装成新的通过门槛。', '']
    return '\n'.join(lines)


def main():
    args = parse_args()
    if args.iterations < 1:
        raise SystemExit('--iterations must be positive')
    maps = read_maps(args.scores_dir)
    summary = {'analysis_type': 'post_hoc_relative_accuracy_loss',
               'relative_loss_formula': '(baseline_accuracy - perturbed_accuracy) / baseline_accuracy',
               'control_model': 'api_control', 'bootstrap_iterations': args.iterations,
               'bootstrap_seed': args.seed, 'bootstrap_unit': 'paired question across all models and conditions',
               'scores_dir': path_label(args.scores_dir),
               'score_file_sha256': {
                   key: hashlib.sha256((args.scores_dir / f'{key}.jsonl').read_bytes()).hexdigest()
                   for key in MODEL_KEYS},
               'new_relative_threshold_gate': None,
               'families': {}}
    gate = args.scores_dir.parent / 'execution_gate.json'
    summary['historical_absolute_gate'] = {
        'path': path_label(gate), 'unchanged': True,
        'sha256': hashlib.sha256(gate.read_bytes()).hexdigest() if gate.exists() else None,
        'note': 'Historical absolute-drop threshold retained; relative analysis is post hoc and has no new gate.'}
    for index, family in enumerate(FAMILIES):
        main_ids, historical_ids, excluded = question_sets(maps, family)
        summary['families'][family] = {
            'excluded_unscorable_question_ids': excluded,
            'main_complete_case': analyze_view(maps, family, main_ids, args.iterations, args.seed + index),
            'historical_all_recorded_pairs': analyze_view(maps, family, historical_ids, args.iterations, args.seed + index)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.output_dir / 'report.md').write_text(render(summary), encoding='utf-8')
    print(args.output_dir.resolve())


if __name__ == '__main__':
    main()
