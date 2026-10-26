#!/usr/bin/env bash
set -u

if [ "$#" -ne 1 ]; then
  echo "usage: $0 EXPERIMENT_ROOT" >&2
  exit 2
fi

experiment_root=$1
python_bin="$HOME/.conda/envs/grast-sql/bin/python"
families="base,add_random_5,add_random_10,add_random_20,add_random_50,add_synonym_5,add_synonym_10,add_synonym_20,add_synonym_50,missing_bridge_table,missing_fk_column"
log_dir="$experiment_root/logs/models"
state_dir="$experiment_root/run_state"
prediction_dir="$experiment_root/model_eval/predictions"
score_dir="$experiment_root/model_eval/scores"

mkdir -p "$log_dir" "$state_dir" "$prediction_dir" "$score_dir"
rm -f "$state_dir/api_control.done" "$state_dir/api_control.failed"

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  printf '%s\n' "$(date -Is) model=api_control state=blocked reason=DEEPSEEK_API_KEY_unset" > "$state_dir/api_control.status"
  exit 4
fi

printf '%s\n' "$(date -Is) model=api_control state=started" > "$state_dir/api_control.status"
cd "$experiment_root" || exit 3

if "$python_bin" -u model_eval/generate_predictions.py \
    --model-key api_control \
    --families "$families" \
    --output-dir "$prediction_dir" \
    --api-key-env DEEPSEEK_API_KEY \
    --seed 20261019 \
    > "$log_dir/api_control.generate.log" 2>&1 \
  && "$python_bin" -u model_eval/score_predictions.py \
    --predictions "$prediction_dir/api_control.jsonl" \
    --output-dir "$score_dir" \
    --comparison set \
    > "$log_dir/api_control.score.log" 2>&1; then
  printf '%s\n' "$(date -Is) model=api_control state=done" > "$state_dir/api_control.status"
  touch "$state_dir/api_control.done"
else
  exit_code=$?
  printf '%s\n' "$(date -Is) model=api_control state=failed exit=$exit_code" > "$state_dir/api_control.status"
  printf '%s\n' "$exit_code" > "$state_dir/api_control.failed"
  exit "$exit_code"
fi
