#!/usr/bin/env bash
set -uo pipefail

ROOT="/root/fsas/home/xiaotao/xiaotao/MINIDEV"
PYTHON="/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python"
VARIANTS="$ROOT/perturbations/output/mini_dev_perturbations.jsonl"
OUTPUT_DIR="$ROOT/BIRD_RESULTS/predictions/missing"
LOG_DIR="$ROOT/BIRD_RESULTS/logs/missing"

gpu="$1"
model_key="$2"
log_path="$LOG_DIR/${model_key}.log"
status_path="$LOG_DIR/${model_key}.exit"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"
export CUDA_VISIBLE_DEVICES="$gpu"

printf "started=%s gpu=%s model=%s\n" "$(date -Iseconds)" "$gpu" "$model_key" >>"$log_path"
"$PYTHON" -u "$ROOT/model_eval/generate_predictions.py" \
  --variants "$VARIANTS" \
  --model-key "$model_key" \
  --families missing_bridge_table,missing_fk_column \
  --output-dir "$OUTPUT_DIR" >>"$log_path" 2>&1
status=$?
printf "%s\n" "$status" >"$status_path"
printf "finished=%s status=%s\n" "$(date -Iseconds)" "$status" >>"$log_path"
exit "$status"
