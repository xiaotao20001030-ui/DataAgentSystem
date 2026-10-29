#!/usr/bin/env python3
"""Build BIRD Mini-Dev plain and one-hop-FK schemas under equal token caps.

The BGE ranking is fixed before variant construction. Gold columns are kept
only for scoring; they are never consulted by either selector.
"""

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import mean, median
from urllib.parse import quote


DEFAULT_BUDGETS = (110, 130, 200)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quote_id(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def build_catalog(metadata):
    docs_by_db = {}
    edges_by_db = {}
    for database in metadata:
        db_id = database["db_id"]
        names = database["table_names_original"]
        primary = set()
        for item in database["primary_keys"]:
            primary.update(item if isinstance(item, (list, tuple)) else [item])
        by_index = {}
        docs = {}
        edges = defaultdict(set)
        for index, (table_index, column) in enumerate(database["column_names_original"]):
            if table_index < 0:
                continue
            table = names[table_index]
            column_id = f"{table}.{column}"
            by_index[index] = column_id
            column_type = database["column_types"][index] or "TEXT"
            text = f"table {table}; column {column}; type {column_type};"
            if index in primary:
                text += " primary key"
            docs[column_id] = {
                "id": column_id,
                "table": table,
                "column": column,
                "type": column_type,
                "primary_key": index in primary,
                "text": text,
            }
        for left, right in database["foreign_keys"]:
            if left in by_index and right in by_index:
                edges[by_index[left]].add(by_index[right])
                edges[by_index[right]].add(by_index[left])
        docs_by_db[db_id] = docs
        edges_by_db[db_id] = edges
    return docs_by_db, edges_by_db


def verify_catalog(db_path, docs):
    connection = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
    try:
        physical = {}
        for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            physical[table.lower()] = {
                row[1].lower()
                for row in connection.execute(f"PRAGMA table_info({quote_id(table)})")
            }
        missing = [
            item["id"] for item in docs.values()
            if item["table"].lower() not in physical
            or item["column"].lower() not in physical[item["table"].lower()]
        ]
        if missing:
            raise ValueError(f"Metadata columns absent from {db_path}: {missing[:10]}")
    finally:
        connection.close()


def grouped_schema(selected, docs):
    grouped = {}
    for column_id in sorted(selected, key=str.lower):
        item = docs[column_id]
        grouped.setdefault(item["table"], []).append({
            "name": item["column"], "type": item["type"],
            "primary_key": item["primary_key"],
        })
    return [{"table": table, "columns": columns} for table, columns in grouped.items()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rankings", type=Path, required=True)
    parser.add_argument("--base-variants", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--budgets", default=",".join(map(str, DEFAULT_BUDGETS)))
    args = parser.parse_args()
    budgets = tuple(sorted({int(x) for x in args.budgets.split(",")}))
    if not budgets or min(budgets) <= 0:
        raise ValueError("Budgets must be positive")

    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), local_files_only=True)
    rankings = read_jsonl(args.rankings)
    bases = [row for row in read_jsonl(args.base_variants) if row["perturbation"]["family"] == "base"]
    if len(bases) != 500 or len(rankings) != 500:
        raise ValueError(f"Expected 500 base questions and rankings, got {len(bases)} and {len(rankings)}")
    ranks_by_qid = {row["question_id"]: row for row in rankings}
    if len(ranks_by_qid) != 500 or {r["question_id"] for r in bases} != set(ranks_by_qid):
        raise ValueError("Base and BGE ranking question IDs differ")
    docs_by_db, edges_by_db = build_catalog(json.loads(args.metadata.read_text(encoding="utf-8")))
    db_paths = {row["db_id"]: args.data_root / row["database_path"] for row in bases}
    for db_id, path in db_paths.items():
        verify_catalog(path, docs_by_db[db_id])

    variants = []
    selection_rows = []
    for base in bases:
        qid, db_id = base["question_id"], base["db_id"]
        docs, edges = docs_by_db[db_id], edges_by_db[db_id]
        ranking = ranks_by_qid[qid]
        if ranking["db_id"] != db_id:
            raise ValueError(f"Database mismatch for question {qid}")
        ranked = ranking["top_columns"]
        if len(ranked) != len(set(ranked)) or any(column not in docs for column in ranked):
            raise ValueError(f"Duplicate or unknown ranked column for question {qid}")

        @lru_cache(maxsize=None)
        def render(column_ids):
            ordered = tuple(sorted(column_ids, key=str.lower))
            text = "\n".join(docs[column]["text"] for column in ordered)
            count = len(tokenizer.encode(text, add_special_tokens=False))
            return text, count, ordered

        choices = {"plain": [], "fk1": []}
        for k in range(1, len(ranked) + 1):
            seed = set(ranked[:k])
            choices["plain"].append((k, seed, *render(frozenset(seed))))
            expanded = set(seed)
            for column in seed:
                expanded.update(edges[column])
            choices["fk1"].append((k, expanded, *render(frozenset(expanded))))

        for budget in budgets:
            for method in ("plain", "fk1"):
                fitting = [choice for choice in choices[method] if choice[3] <= budget]
                if not fitting:
                    raise ValueError(f"No column fits {budget} tokens for question {qid}, {method}")
                k, selected, schema_text, token_count, ordered = fitting[-1]
                family = f"{method}_budget"
                variant_id = f"q{base['question_index']:04d}__{family}_{budget}"
                variant = {
                    **{key: value for key, value in base.items()
                       if key not in {"variant_id", "perturbation", "schema", "schema_columns"}},
                    "variant_id": variant_id,
                    "perturbation": {"variant_id": variant_id, "family": family, "level": budget,
                                     "added": [], "removed": []},
                    "schema": grouped_schema(selected, docs),
                    "schema_columns": list(ordered),
                    "schema_text": schema_text,
                    "schema_token_budget": budget,
                    "schema_token_count": token_count,
                    "retrieval_k": k,
                    "retrieval_method": method,
                    "retrieval_model": "BAAI/bge-base-en-v1.5",
                }
                if variant["schema_token_count"] > budget:
                    raise AssertionError("Budget exceeded")
                variants.append(variant)
                target = set(ranking["bridge_columns"]) | set(ranking["fk_columns"])
                selection_rows.append({
                    "question_id": qid, "db_id": db_id, "family": f"{family}_{budget}",
                    "token_budget": budget, "token_count": token_count,
                    "retrieval_k": k, "selected_column_count": len(selected),
                    "gold_column_hits": len(set(base["gold_columns"]) & selected),
                    "gold_column_total": len(set(base["gold_columns"])),
                    "bridge_fk_hits": len(target & selected),
                    "bridge_fk_total": len(target),
                })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / "budget_variants.jsonl"
    out.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in variants), encoding="utf-8")
    (args.output_dir / "selection_metrics.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in selection_rows), encoding="utf-8"
    )
    by_family = {}
    for family in sorted({row["family"] for row in selection_rows}):
        rows = [row for row in selection_rows if row["family"] == family]
        hits = sum(row["gold_column_hits"] for row in rows)
        total = sum(row["gold_column_total"] for row in rows)
        bridge_hits = sum(row["bridge_fk_hits"] for row in rows)
        bridge_total = sum(row["bridge_fk_total"] for row in rows)
        by_family[family] = {
            "questions": len(rows),
            "mean_schema_tokens": mean(row["token_count"] for row in rows),
            "median_schema_tokens": median(row["token_count"] for row in rows),
            "mean_seed_k": mean(row["retrieval_k"] for row in rows),
            "mean_selected_columns": mean(row["selected_column_count"] for row in rows),
            "gold_column_recall": hits / total if total else None,
            "bridge_fk_recall": bridge_hits / bridge_total if bridge_total else None,
        }
    summary = {
        "definition": "Same exact schema-text token cap for BGE plain top-k and one-hop FK expansion; largest fitting seed k per question; no gold-guided selection",
        "budgets": budgets,
        "question_count": len(bases),
        "variant_count": len(variants),
        "retriever": "BAAI/bge-base-en-v1.5",
        "tokenizer": str(args.tokenizer),
        "rankings_sha256": sha256(args.rankings),
        "base_variants_sha256": sha256(args.base_variants),
        "metadata_sha256": sha256(args.metadata),
        "variants_sha256": sha256(out),
        "by_family": by_family,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"variant_count": len(variants), "by_family": by_family}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
