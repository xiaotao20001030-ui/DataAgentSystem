#!/usr/bin/env bash
set -Eeuo pipefail
RUN=/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025/fixed_k_fk_20261029
SRC=/root/fsas/home/xiaotao/xiaotao/MINIDEV
PY=/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python
cd "$RUN"

# stop the single-threaded scorer; its parent runner will record FAILED, which we clear.
pkill -f "score_predictions_resumable.py --predictions predictions/qwen3_4b.jsonl" || true
for _ in $(seq 1 20); do pgrep -f "score_predictions_resumable.py --predictions predictions/qwen3_4b.jsonl" >/dev/null || break; sleep 2; done
sleep 5
rm -f FAILED

"$PY" tail_parallel.py shard --shards 4

mkdir -p tail/out_0 tail/out_1 tail/out_2 tail/out_3
pids=()
for i in 0 1 2 3; do
  "$PY" scripts/score_predictions_resumable.py \
    --predictions "tail/shard_${i}.jsonl" \
    --variants variants/fixed_variants.jsonl \
    --data-root "$SRC" --output-dir "tail/out_${i}" \
    --timeout-seconds 120 --progress-every 10 > "logs/tail_${i}.log" 2>&1 &
  pids+=("$!")
done
failed=0
for pid in "${pids[@]}"; do wait "$pid" || failed=1; done
test "$failed" = 0

"$PY" tail_parallel.py merge
"$PY" scripts/verify_run.py --stage all
"$PY" scripts/analyze_fixed_results.py --run-root "$RUN" > logs/analyze.log 2>&1
date -Iseconds > COMPLETE
rm -f FAILED
echo done
