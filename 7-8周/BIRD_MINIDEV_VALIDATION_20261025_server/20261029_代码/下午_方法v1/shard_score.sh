#!/usr/bin/env bash
set -Eeuo pipefail
B=/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025
P=/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python
cd "$B"
SHARDS=8
TIMEOUT=20

shard_score() {
  local variants=$1 preds=$2 out=$3 tag=$4
  local dir="$B/shard_tmp/$tag"
  rm -rf "$dir"; mkdir -p "$dir"
  "$P" - "$preds" "$dir" "$SHARDS" <<'PY'
import sys
from pathlib import Path
src, out, shards = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
rows = [l for l in src.read_text().splitlines() if l.strip()]
for i in range(shards):
    (out / f"part_{i}.jsonl").write_text("".join(line + "\n" for line in rows[i::shards]))
PY
  local pids=()
  for i in $(seq 0 $((SHARDS-1))); do
    "$P" "$B/score_strict_generic.py" --variants "$variants" --predictions "$dir/part_$i.jsonl" \
      --output "$dir/out_$i.jsonl" --timeout "$TIMEOUT" > "$dir/log_$i" 2>&1 &
    pids+=("$!")
  done
  local failed=0
  for pid in "${pids[@]}"; do wait "$pid" || failed=1; done
  if (( failed )); then echo "shard failure $tag" >&2; return 1; fi
  "$P" - "$dir" "$out" <<'PY'
import json, sys
from pathlib import Path
d, out = Path(sys.argv[1]), Path(sys.argv[2])
rows = []
for f in sorted(d.glob("out_*.jsonl")):
    rows += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
Path(out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
print(out.name, len(rows), "correct", sum(r["strict_correct"] for r in rows), flush=True)
PY
}

shard_score "$B/aligned_ab/variants_qwen3_0_6b.jsonl" "$B/aligned_ab/predictions/qwen3_0_6b.jsonl" "$B/method_scores/qwen3_0_6b_ab_all.jsonl" ab06 &
shard_score "$B/aligned_ab/variants_qwen3_1_7b.jsonl" "$B/aligned_ab/predictions/qwen3_1_7b.jsonl" "$B/method_scores/qwen3_1_7b_ab_all.jsonl" ab17 &
shard_score "$B/aligned_ab/variants_qwen3_4b.jsonl" "$B/aligned_ab/predictions/qwen3_4b.jsonl" "$B/method_scores/qwen3_4b_ab_all.jsonl" ab4b &
shard_score "$B/aligned_ab/variants_qwen2_5_coder_1_5b.jsonl" "$B/aligned_ab/predictions/qwen2_5_coder_1_5b.jsonl" "$B/method_scores/qwen2_5_coder_1_5b_ab_all.jsonl" ab25 &
wait
shard_score "$B/method_c_130/variants/qwen3_1_7b.jsonl" "$B/method_c_130/qwen3_1_7b.jsonl" "$B/method_scores/qwen3_1_7b_method.jsonl" c17 &
shard_score "$B/method_c_130/variants/qwen3_4b.jsonl" "$B/method_c_130/qwen3_4b.jsonl" "$B/method_scores/qwen3_4b_method.jsonl" c4b &
shard_score "$B/method_c_130/variants/qwen2_5_coder_1_5b.jsonl" "$B/method_c_130/qwen2_5_coder_1_5b.jsonl" "$B/method_scores/qwen2_5_coder_1_5b_method.jsonl" c25 &
wait
echo all-done
