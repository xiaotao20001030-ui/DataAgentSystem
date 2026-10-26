#!/usr/bin/env bash
set -u

if [ "$#" -ne 3 ]; then
  echo "usage: $0 EXPERIMENT_ROOT MODEL_KEY GPU_ID" >&2
  exit 2
fi

experiment_root=$1
model_key=$2
gpu_id=$3
python_bin="$HOME/.conda/envs/grast-sql/bin/python"
families="base,add_random_5,add_random_10,add_random_20,add_random_50,add_synonym_5,add_synonym_10,add_synonym_20,add_synonym_50,missing_bridge_table,missing_fk_column"
log_dir="$experiment_root/logs/models"
state_dir="$experiment_root/run_state"
prediction_dir="$experiment_root/model_eval/predictions"
score_dir="$experiment_root/model_eval/scores"

mkdir -p "$log_dir" "$state_dir" "$prediction_dir" "$score_dir"
printf '%s\n' "$(date -Is) model=$model_key gpu=$gpu_id engine=vllm state=started" > "$state_dir/$model_key.status"

cd "$experiment_root" || exit 3
export CUDA_VISIBLE_DEVICES=$gpu_id
export TOKENIZERS_PARALLELISM=false

if "$python_bin" -u model_eval/generate_predictions_vllm.py \
    --model-key "$model_key" \
    --families "$families" \
    --output-dir "$prediction_dir" \
    --seed 20261019 \
    > "$log_dir/$model_key.generate.log" 2>&1 \
  && "$python_bin" -u model_eval/score_predictions.py \
    --predictions "$prediction_dir/$model_key.jsonl" \
    --output-dir "$score_dir" \
    --comparison set \
    > "$log_dir/$model_key.score.log" 2>&1; then
  printf '%s\n' "$(date -Is) model=$model_key gpu=$gpu_id engine=vllm state=done" > "$state_dir/$model_key.status"
  touch "$state_dir/$model_key.done"
else
  exit_code=$?
  printf '%s\n' "$(date -Is) model=$model_key gpu=$gpu_id engine=vllm state=failed exit=$exit_code" > "$state_dir/$model_key.status"
  printf '%s\n' "$exit_code" > "$state_dir/$model_key.failed"
  exit "$exit_code"
fi
