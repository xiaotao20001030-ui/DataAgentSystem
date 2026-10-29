#!/usr/bin/env bash
set -Eeuo pipefail
RUN=/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025/fixed_k_fk_20261029
SRC=/root/fsas/home/xiaotao/xiaotao/MINIDEV
PY=/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python
cd "$RUN"
trap 'status=$?; printf "exit=%s line=%s\n" "$status" "$LINENO" > FAILED' ERR
exec 9>RUN.lock
flock -n 9 || exit 0
test ! -e COMPLETE || exit 0
test -n "${DEEPSEEK_API_KEY:-}"
rm -f FAILED
date -Iseconds > STARTED
run_model() {
  local model=$1 gpu=$2
  if [[ "$model" != api_control ]]; then
    unset DEEPSEEK_API_KEY
    export CUDA_VISIBLE_DEVICES="$gpu"
  fi
  "$PY" scripts/generate_budget_predictions.py \
    --variants variants/fixed_variants.jsonl \
    --config "$SRC/model_eval/model_matrix.json" --model-key "$model" \
    --families plain_fixed_130,fk1_fixed_130,plain_fixed_200,fk1_fixed_200 \
    --output-dir predictions --max-new-tokens 256 --temperature 0 \
    --seed 20261019 --local-files-only --device cuda:0 \
    --api-key-env DEEPSEEK_API_KEY > "logs/generate_${model}.log" 2>&1
  "$PY" scripts/verify_run.py --stage predictions --model "$model"
  "$PY" scripts/score_predictions_resumable.py \
    --predictions "predictions/${model}.jsonl" --variants variants/fixed_variants.jsonl \
    --data-root "$SRC" --output-dir scores \
    --timeout-seconds 120 --progress-every 100 > "logs/score_${model}.log" 2>&1
}
models=(qwen3_0_6b qwen3_1_7b qwen3_4b qwen2_5_coder_1_5b api_control)
pids=()
for i in "${!models[@]}"; do
  run_model "${models[$i]}" "$i" &
  pids+=("$!")
  printf '%s %s\n' "${models[$i]}" "$!" >> worker_pids.txt
done
failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then failed=1; fi
done
test "$failed" = 0
unset DEEPSEEK_API_KEY
"$PY" scripts/verify_run.py --stage all
"$PY" scripts/analyze_fixed_results.py --run-root "$RUN" > logs/analyze.log 2>&1
date -Iseconds > COMPLETE
rm -f FAILED
