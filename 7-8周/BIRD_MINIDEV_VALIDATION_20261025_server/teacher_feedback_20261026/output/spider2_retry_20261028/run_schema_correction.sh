#!/usr/bin/env bash
set -euo pipefail
root=/root/fsas/home/xiaotao/xiaotao/Spider2-Lite/spider2_retry_20261028
python=/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python
data=/root/fsas/home/xiaotao/xiaotao/Spider2-Lite/Spider2-Lite-Experiment-Data
eval_root=/root/fsas/home/xiaotao/xiaotao/MINIDEV/model_eval
trap 'printf "Schema correction failed; inspect logs/schema_correction*.log\n" > "$root/FAILED"' ERR
run_one() {
  local key=$1 gpu=$2
  if [[ "$key" != api_control ]]; then unset DEEPSEEK_API_KEY; export CUDA_VISIBLE_DEVICES="$gpu"; fi
  "$python" -u "$root/run_models.py" \
    --variants "$root/schema_correction/variants.jsonl" \
    --documents "$data/files/documents" --model-eval-root "$eval_root" \
    --config "$eval_root/model_matrix.json" --model-key "$key" \
    --output-dir "$root/schema_correction/predictions" --max-new-tokens 512
  "$python" -u "$root/score_predictions.py" \
    --variants "$root/schema_correction/variants.jsonl" \
    --predictions "$root/schema_correction/predictions/$key.jsonl" \
    --data-root "$data" --evaluator-root "$root/official_evaluator" \
    --output "$root/schema_correction/scores/$key.jsonl"
}
mkdir -p "$root/schema_correction/predictions" "$root/schema_correction/scores"
keys=(qwen3_0_6b qwen3_1_7b qwen3_4b qwen2_5_coder_1_5b api_control)
pids=()
for i in 0 1 2 3 4; do
  (run_one "${keys[$i]}" "$i") > "$root/logs/schema_correction_${keys[$i]}.log" 2>&1 &
  pids+=("$!")
done
failed=0
for pid in "${pids[@]}"; do wait "$pid" || failed=1; done
if (( failed )); then
  printf 'A correction model job failed; inspect logs/schema_correction*.log\n' > "$root/FAILED"
  exit 1
fi
"$python" - "$root" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1])
for kind in ('predictions','scores'):
 for f in (p/'schema_correction'/kind).glob('*.jsonl'):
  patches={x['variant_id']:x for x in map(json.loads,f.open())}
  if len(patches)!=3: raise RuntimeError(f'{f}: expected 3 corrected variants')
  if kind=='predictions' and any(x.get('error') for x in patches.values()):
   raise RuntimeError(f'{f}: generation error')
  target=p/kind/f.name
  original=[json.loads(s) for s in target.open()]
  rows=[patches.get(x['variant_id'],x) for x in original]
  temp=target.with_suffix('.jsonl.tmp')
  temp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
  temp.replace(target)
PY
"$python" "$root/finalize_results.py" --scores-dir "$root/scores" \
  --variants "$root/variants/variants.jsonl" --output-dir "$root/reports" \
  > "$root/logs/finalize_after_schema_correction.log" 2>&1
rm "$root/QUALITY_RECHECK_PENDING"
touch "$root/COMPLETE"
