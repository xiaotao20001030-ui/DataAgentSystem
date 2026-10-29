#!/usr/bin/env bash
set -euo pipefail

root=/root/fsas/home/xiaotao/xiaotao/Spider2-Lite/spider2_retry_20261028
python=/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python
data=/root/fsas/home/xiaotao/xiaotao/Spider2-Lite/Spider2-Lite-Experiment-Data
eval_root=/root/fsas/home/xiaotao/xiaotao/MINIDEV/model_eval
trap 'printf "API model job failed; inspect logs/api_control.log\n" > "$root/API_MODEL_FAILED"' ERR

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo 'API key absent from process environment' >&2
  exit 1
fi
while [[ ! -f "$root/PERTURBATIONS_COMPLETE" ]]; do
  if [[ -f "$root/PERTURBATIONS_FAILED" ]]; then exit 1; fi
  sleep 30
done
mkdir -p "$root/predictions" "$root/scores" "$root/logs"
"$python" -u "$root/run_models.py" \
  --variants "$root/variants/variants.jsonl" \
  --documents "$data/files/documents" \
  --model-eval-root "$eval_root" \
  --config "$eval_root/model_matrix.json" \
  --model-key api_control --output-dir "$root/predictions" \
  --max-new-tokens 512
"$python" -u "$root/score_predictions.py" \
  --variants "$root/variants/variants.jsonl" \
  --predictions "$root/predictions/api_control.jsonl" \
  --data-root "$data" --evaluator-root "$root/official_evaluator" \
  --output "$root/scores/api_control.jsonl"
touch "$root/API_MODEL_COMPLETE"
