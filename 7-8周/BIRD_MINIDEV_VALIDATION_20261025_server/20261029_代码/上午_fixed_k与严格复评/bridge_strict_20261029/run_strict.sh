#!/usr/bin/env bash
set -Eeuo pipefail
RUN=/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025/bridge_strict_20261029
cd "$RUN"
PY=python3
mkdir -p logs
rm -rf strict_all
mkdir -p strict_all
rm -f COMPLETE FAILED
trap 'printf "failed line=%s\n" "$LINENO" > FAILED' ERR
date -Iseconds > STARTED

models=(qwen3_0_6b qwen3_1_7b qwen3_4b qwen2_5_coder_1_5b api_control)
pids=()
for m in "${models[@]}"; do
  "$PY" strict_rescore.py \
    --variants ../perturbations/output/mini_dev_perturbations.jsonl \
    --predictions-dir ../model_eval/predictions \
    --data-root ../mini_dev_data \
    --output-dir strict_all \
    --families missing_bridge_table,missing_fk_column \
    --models "$m" \
    --timeout-seconds 60 > "logs/strict_${m}.log" 2>&1 &
  pids+=("$!")
done
failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then failed=1; fi
done
if (( failed )); then
  echo "one or more models failed" > FAILED
  exit 1
fi
"$PY" summarize_strict.py strict_all > logs/summarize.log 2>&1
date -Iseconds > COMPLETE
rm -f FAILED
