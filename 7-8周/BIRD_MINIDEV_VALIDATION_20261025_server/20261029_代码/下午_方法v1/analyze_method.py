#!/usr/bin/env python3
"""Analyse method C vs aligned A/B: strict EX, paired bootstrap 1000, pass gate."""

import argparse
import json
import random
from pathlib import Path

MODELS = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b", "api_control")
NAMES = {"qwen3_0_6b": "Qwen3 0.6B", "qwen3_1_7b": "Qwen3 1.7B", "qwen3_4b": "Qwen3 4B",
         "qwen2_5_coder_1_5b": "Qwen2.5 Coder 1.5B", "api_control": "API"}


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def acc(rows, ids, flag="strict_correct"):
    return sum(1 for i in ids if rows[i].get(flag)) / len(ids)


def bootstrap(rows_a, rows_c, ids, iterations=1000, seed=20261029):
    rng = random.Random(seed)
    diffs = []
    for _ in range(iterations):
        sample = [ids[rng.randrange(len(ids))] for _ in ids]
        diffs.append((acc(rows_c, sample) - acc(rows_a, sample)) * 100)
    diffs.sort()
    return diffs[int(0.025 * iterations)], diffs[int(0.975 * iterations) - 1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores-dir", required=True)
    parser.add_argument("--method-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    scores = Path(args.scores_dir)
    results = []
    for model in MODELS:
        try:
            a = {r["question_id"]: r for r in read(scores / f"{model}_plain.jsonl")}
            b = {r["question_id"]: r for r in read(scores / f"{model}_fk1.jsonl")}
            c = {r["question_id"]: r for r in read(scores / f"{model}_method.jsonl")}
        except FileNotFoundError:
            continue
        ids = [i for i in a if i in b and i in c and a[i]["status"] != "gold_unscoreable"
               and b[i]["status"] != "gold_unscoreable" and c[i]["status"] != "gold_unscoreable"]
        if not ids:
            continue
        ea, eb, ec = acc(a, ids), acc(b, ids), acc(c, ids)
        low, high = bootstrap(a, c, ids)
        diff = (ec - ea) * 100
        result = {"model": model, "n": len(ids), "plain": ea, "fk1": eb, "method": ec,
                  "method_minus_plain_pp": diff, "ci_low_pp": low, "ci_high_pp": high,
                  "passes": bool(diff >= 3.0 and low > 0)}
        results.append(result)
        print(f"{NAMES[model]:22s} n={len(ids)} plain={ea:.3f} fk1={eb:.3f} method={ec:.3f} "
              f"diff={diff:+.1f}pp CI=[{low:+.1f},{high:+.1f}] pass={result['passes']}")

    # supplement stats
    stats = {}
    for model in MODELS:
        path = Path(args.method_dir) / f"{model}.jsonl"
        if not path.exists():
            continue
        rows = read(path)
        stats[model] = {
            "n": len(rows),
            "rounds_mean": sum(r["rounds"] for r in rows) / len(rows),
            "added_tokens_mean": sum(r["added_tokens"] for r in rows) / len(rows),
            "blocked_mean": sum(r["blocked"] for r in rows) / len(rows),
            "triggered": sum(1 for r in rows if r["rounds"] > 0),
        }
    passing = [r["model"] for r in results if r["passes"]]
    payload = {"results": results, "supplement_stats": stats,
               "small_models_passing": len(passing), "gate_passes": len(passing) >= 2}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("small models passing:", passing, "gate:", payload["gate_passes"])


if __name__ == "__main__":
    main()
