#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/fsas/home/xiaotao/xiaotao/MINIDEV"
PYTHON="/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python"
SCRIPTS="$ROOT/BIRD_RESULTS/scripts"
COMBINED="$ROOT/BIRD_RESULTS/scores_official/combined"

"$PYTHON" "$SCRIPTS/merge_bird_official_scores.py"

"$PYTHON" "$SCRIPTS/analyze_column_curves.py" \
  --project-root "$ROOT" \
  --scores-dir "$COMBINED" \
  --output-prefix column_level_curves_official

"$PYTHON" "$SCRIPTS/analyze_execution_gate.py" \
  --config "$ROOT/model_eval/model_matrix.json" \
  --scores-dir "$COMBINED" \
  --output "$ROOT/BIRD_RESULTS/analysis/execution_gate_official.json" || true

"$PYTHON" "$SCRIPTS/analyze_conditional_robustness.py" \
  --scores-dir "$COMBINED" \
  --output "$ROOT/BIRD_RESULTS/analysis/conditional_robustness_official.json"

"$PYTHON" "$SCRIPTS/analyze_real_synonym_sensitivity.py" \
  --base-scores-dir "$COMBINED" \
  --sensitivity-scores-dir "$COMBINED" \
  --output "$ROOT/BIRD_RESULTS/analysis/real_synonym_sensitivity_official.json"

"$PYTHON" "$SCRIPTS/analyze_bird_missing_results.py" \
  --root "$ROOT" \
  --scores-dir "$ROOT/BIRD_RESULTS/scores_official/missing" \
  --base-scores-dir "$ROOT/BIRD_RESULTS/scores_official/base" \
  --variants "$ROOT/perturbations/output/mini_dev_perturbations.jsonl" \
  --output-prefix missing_schema_official

"$PYTHON" "$SCRIPTS/compare_bird_scores.py"
