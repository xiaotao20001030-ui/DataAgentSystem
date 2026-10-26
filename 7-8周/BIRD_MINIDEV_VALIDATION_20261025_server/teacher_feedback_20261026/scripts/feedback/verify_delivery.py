#!/usr/bin/env python3
"""Verify today's artifacts and that the server baseline was not overwritten."""

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment-root', type=Path, default=PROJECT_ROOT.parent)
    args = parser.parse_args()
    baseline = read(PROJECT_ROOT/'provenance/server_baseline_sha256.json')
    for record in baseline['files']:
        path = args.experiment_root/record['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError(f'Server baseline changed or missing: {path}')
    server = args.experiment_root
    variants = jsonl(server/'perturbations/output/mini_dev_perturbations.jsonl')
    assert len(variants) == len({row['variant_id'] for row in variants}) == 5097
    models = ['api_control', 'qwen3_0_6b', 'qwen3_1_7b', 'qwen3_4b', 'qwen2_5_coder_1_5b']
    for model in models:
        rows = jsonl(server/'model_eval/scores'/f'{model}.jsonl')
        assert len(rows) == len({row['variant_id'] for row in rows}) == 5097
    synonym = read(PROJECT_ROOT/'output/teacher_feedback/synonym20/cases.json')
    assert len(synonym['cases']) == 30
    bridge = read(PROJECT_ROOT/'output/teacher_feedback/bridge_api_successes/audit.json')['summary']
    assert bridge['set_matches_reproduced'] == 18
    assert bridge['visible_schema_only_successes'] == 3
    relative = read(PROJECT_ROOT/'output/teacher_feedback/relative_execution/summary.json')
    assert relative['new_relative_threshold_gate'] is None
    retrieval = read(PROJECT_ROOT/'output/retrieval_fk/fk_expansion_summary.json')
    assert len(retrieval) == 2
    for model, summary in retrieval.items():
        assert summary['question_count'] == 391
        predictions = jsonl(PROJECT_ROOT/'output/retrieval_fk'/f'{Path(model).name}_predictions.jsonl')
        assert len(predictions) == len({row['question_id'] for row in predictions}) == 500
        for k in ('5', '10', '20', '50'):
            assert summary['expanded'][k]['miss_rate'] <= summary['plain'][k]['miss_rate']
            assert summary['original_hypothesis'][k]['foreign_key_columns_vs_single']['ci95_low_percentage_points'] > 0
    checks = {
        'server_baseline_files_unchanged': len(baseline['files']),
        'main_experiment_variants': 5097,
        'execution_models': len(models),
        'valid_synonym_cases': 30,
        'bridge_successes_reproduced': 18,
        'relative_analysis_has_no_new_gate': True,
        'retrieval_models_with_500_rankings': len(retrieval),
    }
    output = PROJECT_ROOT/'provenance/verification.json'
    output.write_text(json.dumps({'status': 'passed', 'checks': checks}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
