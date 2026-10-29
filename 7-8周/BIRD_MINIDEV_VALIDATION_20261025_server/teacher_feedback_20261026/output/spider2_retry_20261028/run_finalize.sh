#!/usr/bin/env bash
set -euo pipefail

root=/root/fsas/home/xiaotao/xiaotao/Spider2-Lite/spider2_retry_20261028
python=/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python
trap 'printf "Final validation or report failed; inspect logs/finalize.log\n" > "$root/FAILED"' ERR
while [[ ! -f "$root/LOCAL_MODELS_COMPLETE" || ! -f "$root/API_MODEL_COMPLETE" ]]; do
  if [[ -f "$root/LOCAL_MODELS_FAILED" || -f "$root/API_MODEL_FAILED" || -f "$root/PERTURBATIONS_FAILED" ]]; then
    printf 'An upstream job failed; inspect logs and *_FAILED markers\n' > "$root/FAILED"
    exit 1
  fi
  sleep 60
done
"$python" - "$root" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
variants = [json.loads(s) for s in (root / 'variants/variants.jsonl').open()]
want = {x['variant_id'] for x in variants}
if len(want) != len(variants) or len(want) % 3:
    raise SystemExit('Variant IDs are duplicated or incomplete')
for model in ('qwen3_0_6b', 'qwen3_1_7b', 'qwen3_4b',
              'qwen2_5_coder_1_5b', 'api_control'):
    for kind in ('predictions', 'scores'):
        path = root / kind / f'{model}.jsonl'
        rows = [json.loads(s) for s in path.open()]
        by_id = {x['variant_id']: x for x in rows}
        if set(by_id) != want:
            raise SystemExit(f'{model} {kind}: {len(by_id)} IDs vs {len(want)} variants')
        if kind == 'predictions' and any(x.get('error') for x in by_id.values()):
            raise SystemExit(f'{model}: generation errors remain')
print(f'Validated {len(want)} variants for five predictions and scores')
PY
"$python" "$root/finalize_results.py" \
  --scores-dir "$root/scores" --variants "$root/variants/variants.jsonl" \
  --output-dir "$root/reports" > "$root/logs/finalize.log" 2>&1
touch "$root/COMPLETE"
