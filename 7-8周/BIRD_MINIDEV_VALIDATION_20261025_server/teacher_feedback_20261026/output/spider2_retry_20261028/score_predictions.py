#!/usr/bin/env python3
"""Score Spider model SQL with the pinned official result comparator."""

import argparse
import hashlib
import json
from pathlib import Path

from generate_silver import (execute_readonly, official_functions, read_jsonl,
                             safe_select, score_result)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variants", type=Path, required=True)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--evaluator-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    files = args.data_root / "files"
    standards = {x["instance_id"]: x for x in read_jsonl(files / "tasks/spider2lite_eval.jsonl")}
    scorer = official_functions(args.evaluator_root)
    gold_dir = files / "gold/exec_result/lite"
    variants = {x["variant_id"]: x for x in read_jsonl(args.variants)}
    predictions = {x["variant_id"]: x for x in read_jsonl(args.predictions)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    previous = {x["variant_id"]: x for x in read_jsonl(args.output)} if args.output.exists() else {}
    with args.output.open("a", encoding="utf-8") as output:
        for vid, variant in variants.items():
            if vid not in predictions:
                continue
            prediction = predictions[vid]
            fingerprint = hashlib.sha256(json.dumps(prediction, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if previous.get(vid, {}).get("prediction_sha256") == fingerprint:
                continue
            result = {"variant_id": vid, "instance_id": variant["instance_id"],
                      "condition": variant["condition"], "model_key": prediction["model_key"],
                      "label_source": variant["label_source"], "correct": False,
                      "scorable": True, "error": None, "prediction_sha256": fingerprint}
            try:
                if prediction.get("error"):
                    raise ValueError("Model generation error")
                sql = prediction.get("predicted_sql") or ""
                safe_select(sql)
                frame = execute_readonly(Path(variant["database_path"]), sql)
            except Exception as exc:
                result["error"] = f"prediction:{type(exc).__name__}: {exc}"
            else:
                try:
                    result["correct"] = score_result(variant["instance_id"], frame,
                                                     standards, gold_dir, scorer)
                except Exception as exc:
                    result["scorable"] = False
                    result["error"] = f"evaluator:{type(exc).__name__}: {exc}"
            output.write(json.dumps(result, ensure_ascii=False) + "\n")
            output.flush()
            print(f"{vid} correct={int(result['correct'])} scorable={int(result['scorable'])}", flush=True)


if __name__ == "__main__":
    main()
