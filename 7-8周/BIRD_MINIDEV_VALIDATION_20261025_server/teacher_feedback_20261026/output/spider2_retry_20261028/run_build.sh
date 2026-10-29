#!/usr/bin/env bash
set -euo pipefail

root=/root/fsas/home/xiaotao/xiaotao/Spider2-Lite/spider2_retry_20261028
python=/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python

trap 'printf "perturbation build failed at %s\n" "$(date -Is)" > "$root/PERTURBATIONS_FAILED"' ERR

"$python" "$root/build_perturbations.py" \
  --data-root /root/fsas/home/xiaotao/xiaotao/Spider2-Lite/Spider2-Lite-Experiment-Data \
  --database-root /root/fsas/home/xiaotao/xiaotao/Spider2-Lite \
  --evaluator-root "$root/official_evaluator" \
  --labels "$root/labels/schema_labels.jsonl" \
  --output-dir "$root/variants"

touch "$root/PERTURBATIONS_COMPLETE"
