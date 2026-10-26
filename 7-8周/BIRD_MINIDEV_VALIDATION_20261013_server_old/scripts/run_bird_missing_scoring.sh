#!/usr/bin/env bash
set -euo pipefail

WORKER="/root/fsas/home/xiaotao/xiaotao/MINIDEV/BIRD_RESULTS/scripts/run_bird_missing_score_worker.sh"

launch() {
  local model_key="$1"
  local session="bird-score-missing-${model_key}"

  if tmux has-session -t "$session" 2>/dev/null; then
    printf "already-running %s\n" "$session"
    return
  fi

  tmux new-session -d -s "$session" "bash '$WORKER' '$model_key'"
  printf "launched %s\n" "$session"
}

launch "qwen3_0_6b"
launch "qwen3_1_7b"
launch "qwen3_4b"
launch "qwen2_5_coder_1_5b"
launch "api_control"

tmux list-sessions | grep "bird-score-missing" || true
