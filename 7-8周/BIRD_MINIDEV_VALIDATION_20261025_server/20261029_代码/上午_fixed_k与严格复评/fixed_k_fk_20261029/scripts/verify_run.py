#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

MODELS = ('qwen3_0_6b', 'qwen3_1_7b', 'qwen3_4b', 'qwen2_5_coder_1_5b', 'api_control')
def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
ap = argparse.ArgumentParser()
ap.add_argument('--stage', choices=('predictions','all'), required=True)
ap.add_argument('--model', choices=MODELS)
a = ap.parse_args()
root = Path(__file__).resolve().parent.parent
expected = {r['variant_id'] for r in read(root/'variants/fixed_variants.jsonl')}
assert len(expected) == 2000
for model in (a.model,) if a.model else MODELS:
    for directory in ('predictions',) if a.stage == 'predictions' else ('predictions','scores'):
        rows = read(root/directory/f'{model}.jsonl')
        assert len(rows) == 2000 and {r['variant_id'] for r in rows} == expected, (model, directory, len(rows))
        if directory == 'predictions':
            errors = [r['variant_id'] for r in rows if r.get('error')]
            assert not errors, (model, 'generation errors', errors[:10])
print('Verified', a.stage, a.model or 'all five models')
