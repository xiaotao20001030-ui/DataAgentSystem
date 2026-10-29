#!/usr/bin/env bash
set -euo pipefail

root=/root/fsas/home/xiaotao/xiaotao/Spider2-Lite/spider2_retry_20261028
python=/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python
data=/root/fsas/home/xiaotao/xiaotao/Spider2-Lite/Spider2-Lite-Experiment-Data
eval_root=/root/fsas/home/xiaotao/xiaotao/MINIDEV/model_eval

while [[ ! -f "$root/PERTURBATIONS_COMPLETE" ]]; do
  if [[ -f "$root/PERTURBATIONS_FAILED" ]]; then exit 1; fi
  sleep 30
done
mkdir -p "$root/predictions" "$root/scores" "$root/logs"

run_one() {
  local key=$1 gpu=$2
  export CUDA_VISIBLE_DEVICES="$gpu"
  "$python" -u "$root/run_models.py" \
    --variants "$root/variants/variants.jsonl" \
    --documents "$data/files/documents" \
    --model-eval-root "$eval_root" \
    --config "$eval_root/model_matrix.json" \
    --model-key "$key" --output-dir "$root/predictions" \
    --device cuda:0 --max-new-tokens 512
  "$python" -u "$root/score_predictions.py" \
    --variants "$root/variants/variants.jsonl" \
    --predictions "$root/predictions/$key.jsonl" \
    --data-root "$data" --evaluator-root "$root/official_evaluator" \
    --output "$root/scores/$key.jsonl"
  touch "$root/${key}_COMPLETE"
}

pids=()
keys=(qwen3_0_6b qwen3_1_7b qwen3_4b qwen2_5_coder_1_5b)
for i in 0 1 2 3; do
  (run_one "${keys[$i]}" "$i") > "$root/logs/${keys[$i]}.log" 2>&1 &
  pids+=("$!")
done
failed=0
for pid in "${pids[@]}"; do wait "$pid" || failed=1; done
if (( failed )); then
  printf 'One or more local model jobs failed; inspect logs/*.log\n' > "$root/LOCAL_MODELS_FAILED"
  exit 1
fi
touch "$root/LOCAL_MODELS_COMPLETE"
