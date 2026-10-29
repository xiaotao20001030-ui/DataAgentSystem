#!/usr/bin/env bash
set -Eeuo pipefail
B=/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025
P=/root/fsas/home/xiaotao/.conda/envs/grast-sql/bin/python
SHARDS=4
TIMEOUT=20
cd "$B"

shard_perm() {
  local variants=$1 preds=$2 out=$3 tag=$4
  local dir="$B/shard_perm/$tag"; rm -rf "$dir"; mkdir -p "$dir"
  "$P" - "$preds" "$dir" "$SHARDS" <<'PY'
import sys
from pathlib import Path
src,out,n=Path(sys.argv[1]),Path(sys.argv[2]),int(sys.argv[3])
rows=[l for l in src.read_text().splitlines() if l.strip()]
for i in range(n): (out/f"part_{i}.jsonl").write_text("".join(x+"\n" for x in rows[i::n]))
PY
  local pids=()
  for i in $(seq 0 $((SHARDS-1))); do
    "$P" "$B/score_strict_generic.py" --variants "$variants" --predictions "$dir/part_$i.jsonl" \
      --output "$dir/out_$i.jsonl" --timeout "$TIMEOUT" --permissive > "$dir/log_$i" 2>&1 &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do wait "$pid" || true; done
  "$P" - "$dir" "$out" <<'PY'
import json,sys
from pathlib import Path
d,out=Path(sys.argv[1]),Path(sys.argv[2])
rows=[]
for f in sorted(d.glob("out_*.jsonl")): rows += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
Path(out).write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows))
print(out.name,len(rows),"correct",sum(r["strict_correct"] for r in rows))
PY
}

for m in qwen3_0_6b qwen3_1_7b qwen3_4b qwen2_5_coder_1_5b api_control; do
  shard_perm "$B/aligned_ab/variants_$m.jsonl" "$B/aligned_ab/predictions/$m.jsonl" "$B/method_scores/${m}_ab_perm_all.jsonl" "ab_$m" &
  shard_perm "$B/method_c_130/variants/$m.jsonl" "$B/method_c_130/$m.jsonl" "$B/method_scores/${m}_method_perm.jsonl" "c_$m" &
done
wait
echo done
