#!/usr/bin/env bash
set -euo pipefail

WORKER="/root/fsas/home/xiaotao/xiaotao/MINIDEV/BIRD_RESULTS/scripts/run_bird_missing_worker.sh"

launch() {
  local session="$1"
  local gpu="$2"
  local model_key="$3"

  if tmux has-session -t "$session" 2>/dev/null; then
    printf "already-running %s\n" "$session"
    return
  fi

  tmux new-session -d -s "$session" "bash '$WORKER' '$gpu' '$model_key'"
  printf "launched %s gpu=%s model=%s\n" "$session" "$gpu" "$model_key"
}

launch "bird-missing-qwen06" "4" "qwen3_0_6b"
launch "bird-missing-qwen17" "5" "qwen3_1_7b"
launch "bird-missing-qwen4" "6" "qwen3_4b"
launch "bird-missing-qwen25" "7" "qwen2_5_coder_1_5b"

tmux list-sessions | grep "bird-missing" || true
