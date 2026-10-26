#!/bin/sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    echo "DEEPSEEK_API_KEY is not set in this shell." >&2
    exit 1
fi

cd "$ROOT"

python3 -u model_eval/generate_predictions.py \
    --model-key api_control \
    --families add_random_5,add_random_10,add_random_50,add_synonym_5,add_synonym_10,add_synonym_50 \
    --output-dir model_eval/predictions_all_levels \
    --api-key-env DEEPSEEK_API_KEY
