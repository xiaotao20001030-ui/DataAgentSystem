#!/bin/sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    echo "DEEPSEEK_API_KEY is not set in this shell." >&2
    exit 1
fi

cd "$ROOT"

python3 -u model_eval/generate_predictions.py \
    --variants perturbations/output/real_synonym_sensitivity/mini_dev_add_real_synonym_20.jsonl \
    --model-key api_control \
    --families add_real_synonym_20 \
    --output-dir model_eval/predictions_real_synonym \
    --api-key-env DEEPSEEK_API_KEY
