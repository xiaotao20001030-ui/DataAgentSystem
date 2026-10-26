#!/usr/bin/env bash
set -uo pipefail

ROOT="/root/fsas/home/xiaotao/xiaotao/MINIDEV"
PYTHON="/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python"
SCORER="$ROOT/BIRD_RESULTS/scripts/score_predictions_official.py"
PRED_ROOT="$ROOT/BIRD_RESULTS/predictions"
SCORE_ROOT="$ROOT/BIRD_RESULTS/scores_official"
LOG_ROOT="$ROOT/BIRD_RESULTS/logs/official_scoring"

group="$1"
prediction_dir="$2"
variants_path="$3"
score_subdir="$4"
log_path="$LOG_ROOT/${group}.log"
status_path="$LOG_ROOT/${group}.exit"

mkdir -p "$SCORE_ROOT/$score_subdir" "$LOG_ROOT"

printf "started=%s group=%s\n" "$(date -Iseconds)" "$group" >>"$log_path"
mapfile -t prediction_files < <(find "$prediction_dir" -maxdepth 1 -type f -name "*.jsonl" | sort)

"$PYTHON" -u "$SCORER" \
  --predictions "${prediction_files[@]}" \
  --variants "$variants_path" \
  --data-root "$ROOT" \
  --output-dir "$SCORE_ROOT/$score_subdir" \
  --prediction-timeout 30 \
  --gold-timeout 30 \
  --progress-every 25 >>"$log_path" 2>&1
status=$?
printf "%s\n" "$status" >"$status_path"
printf "finished=%s status=%s\n" "$(date -Iseconds)" "$status" >>"$log_path"
exit "$status"
