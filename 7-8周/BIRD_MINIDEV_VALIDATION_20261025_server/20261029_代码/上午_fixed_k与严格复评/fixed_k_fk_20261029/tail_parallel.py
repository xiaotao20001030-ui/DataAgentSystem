#!/usr/bin/env python3
"""Shard the remaining qwen3_4b scoring work, then merge the shard outputs."""

import argparse
import json
from pathlib import Path


def read(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=("shard", "merge"))
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()
    run = Path(__file__).resolve().parent
    predictions = read(run / "predictions/qwen3_4b.jsonl")
    scores = read(run / "scores/qwen3_4b.jsonl")
    done = {row["variant_id"] for row in scores}
    pending = [row for row in predictions if row["variant_id"] not in done]

    if args.cmd == "shard":
        tail = run / "tail"
        tail.mkdir(exist_ok=True)
        (tail / "pending.json").write_text(
            json.dumps([row["variant_id"] for row in pending], indent=0), encoding="utf-8"
        )
        for index in range(args.shards):
            part = pending[index:: args.shards]
            (tail / f"shard_{index}.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in part),
                encoding="utf-8",
            )
            print(f"shard {index}: {len(part)}")
        print(f"pending total: {len(pending)}")
    else:
        merged = {row["variant_id"]: row for row in scores}
        for path in sorted((run / "tail").glob("out_*/qwen3_4b.jsonl")):
            for row in read(path):
                merged.setdefault(row["variant_id"], row)
        order = [row["variant_id"] for row in predictions]
        rows = [merged[vid] for vid in order if vid in merged]
        (run / "scores/qwen3_4b.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        print(f"merged: {len(rows)} of {len(predictions)}")


if __name__ == "__main__":
    main()
