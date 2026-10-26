#!/usr/bin/env bash
set -uo pipefail

ROOT="/root/fsas/home/xiaotao/xiaotao/MINIDEV"
PYTHON="/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python"
VARIANTS="$ROOT/perturbations/output/mini_dev_perturbations.jsonl"
PREDICTIONS_DIR="$ROOT/BIRD_RESULTS/predictions/missing"
SCORES_DIR="$ROOT/BIRD_RESULTS/scores/missing"
LOG_DIR="$ROOT/BIRD_RESULTS/logs/missing_scores"

model_key="$1"
log_path="$LOG_DIR/${model_key}.log"
status_path="$LOG_DIR/${model_key}.exit"
predictions_path="$PREDICTIONS_DIR/${model_key}.jsonl"

mkdir -p "$SCORES_DIR" "$LOG_DIR"

printf "started=%s model=%s\n" "$(date -Iseconds)" "$model_key" >>"$log_path"
"$PYTHON" -u "$ROOT/model_eval/score_predictions_resumable.py" \
  --predictions "$predictions_path" \
  --variants "$VARIANTS" \
  --data-root "$ROOT" \
  --output-dir "$SCORES_DIR" \
  --progress-every 10 >>"$log_path" 2>&1
status=$?
printf "%s\n" "$status" >"$status_path"
printf "finished=%s status=%s\n" "$(date -Iseconds)" "$status" >>"$log_path"
exit "$status"
