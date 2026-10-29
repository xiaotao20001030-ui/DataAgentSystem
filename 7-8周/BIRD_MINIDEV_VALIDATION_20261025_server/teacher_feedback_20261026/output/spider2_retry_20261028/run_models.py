#!/usr/bin/env python3
"""Run one BIRD model-matrix entry on paired Spider SQLite schema variants."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace


def read_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def load_generator(source):
    spec = importlib.util.spec_from_file_location("bird_generator", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def messages_for(row, documents):
    prompt = "SQLite schema:\n" + row["schema_text"] + "\n\nQuestion:\n" + row["question"]
    name = row.get("external_knowledge")
    if name:
        doc = documents / name
        if doc.is_file():
            prompt += "\n\nExternal knowledge:\n" + doc.read_text(encoding="utf-8")
    prompt += "\n\nReturn one SQLite query."
    return [{"role": "system", "content": "You generate SQLite SQL. Return one SQL query only."},
            {"role": "user", "content": prompt}]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variants", type=Path, required=True)
    p.add_argument("--documents", type=Path, required=True)
    p.add_argument("--model-eval-root", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--model-key", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--device", default="auto")
    p.add_argument("--dtype", default="auto")
    p.add_argument("--max-new-tokens", type=int, default=512)
    p.add_argument("--seed", type=int, default=20261028)
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    p.add_argument("--limit", type=int)
    args = p.parse_args()
    variants = read_jsonl(args.variants)
    if args.limit is not None:
        variants = variants[:args.limit]
    configs = read_jsonl(args.config) if args.config.suffix == ".jsonl" else json.loads(args.config.read_text())
    config = next(x for x in configs if x["key"] == args.model_key)
    original = load_generator(args.model_eval_root / "generate_predictions.py")
    params = SimpleNamespace(seed=args.seed, device=args.device, dtype=args.dtype,
                             local_files_only=True, max_new_tokens=args.max_new_tokens,
                             api_base=None, api_key_env=args.api_key_env,
                             temperature=0, retries=args.retries)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{args.model_key}.jsonl"
    previous = {row["variant_id"]: row for row in read_jsonl(output_path)} if output_path.exists() else {}
    generator = None
    with output_path.open("a", encoding="utf-8") as output:
        for row in variants:
            vid = row["variant_id"]
            if vid in previous and previous[vid].get("error") is None:
                continue
            if generator is None:
                generator = original.create_generator(config, params)
            try:
                raw = generator.generate(messages_for(row, args.documents))
                sql = original.extract_sql(raw)
                error = None
            except Exception as exc:
                raw, sql = "", ""
                error = f"{type(exc).__name__}: {exc}"
            output.write(json.dumps({"variant_id": vid, "instance_id": row["instance_id"],
                 "condition": row["condition"], "model_key": args.model_key,
                 "predicted_sql": sql, "raw_response": raw, "error": error},
                 ensure_ascii=False) + "\n")
            output.flush()
            print(f"{args.model_key} {vid} {'ok' if error is None else 'error'}", flush=True)


if __name__ == "__main__":
    main()
