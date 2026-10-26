#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/fsas/home/xiaotao/xiaotao/MINIDEV"
WORKER="$ROOT/BIRD_RESULTS/scripts/run_bird_official_scoring_worker.sh"
MAIN_VARIANTS="$ROOT/perturbations/output/mini_dev_perturbations.jsonl"
REAL_VARIANTS="$ROOT/perturbations/output/real_synonym_sensitivity/mini_dev_add_real_synonym_20.jsonl"
PRED_ROOT="$ROOT/BIRD_RESULTS/predictions"

launch() {
  local group="$1"
  local prediction_dir="$2"
  local variants_path="$3"
  local score_subdir="$4"
  local session="bird-official-${group}"

  if tmux has-session -t "$session" 2>/dev/null; then
    printf "already-running %s\n" "$session"
    return
  fi

  tmux new-session -d -s "$session" \
    "bash '$WORKER' '$group' '$prediction_dir' '$variants_path' '$score_subdir'"
  printf "launched %s\n" "$session"
}

launch "base" "$PRED_ROOT/base" "$MAIN_VARIANTS" "base"
launch "random5" "$PRED_ROOT/random/level_5" "$MAIN_VARIANTS" "random/level_5"
launch "random10" "$PRED_ROOT/random/level_10" "$MAIN_VARIANTS" "random/level_10"
launch "random20" "$PRED_ROOT/random/level_20" "$MAIN_VARIANTS" "random/level_20"
launch "random50" "$PRED_ROOT/random/level_50" "$MAIN_VARIANTS" "random/level_50"
launch "synonym5" "$PRED_ROOT/synonym/level_5" "$MAIN_VARIANTS" "synonym/level_5"
launch "synonym10" "$PRED_ROOT/synonym/level_10" "$MAIN_VARIANTS" "synonym/level_10"
launch "synonym20" "$PRED_ROOT/synonym/level_20" "$MAIN_VARIANTS" "synonym/level_20"
launch "synonym50" "$PRED_ROOT/synonym/level_50" "$MAIN_VARIANTS" "synonym/level_50"
launch "real20" "$PRED_ROOT/real_synonym/level_20" "$REAL_VARIANTS" "real_synonym/level_20"
launch "missing" "$PRED_ROOT/missing" "$MAIN_VARIANTS" "missing"

tmux list-sessions | grep "bird-official" || true
