#!/usr/bin/env python3
"""Build 500-question fixed-k BIRD comparisons; calibrate 200 using tokens only.

The 130 label is a target, not a cap: plain top-12 versus top-10 plus one-hop
FK. The 200 pair is chosen once for the whole cohort before model generation.
"""

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from urllib.parse import quote


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def build_catalog(metadata):
    """Same catalog/text and undirected FK endpoints as generate_budget_variants."""
    docs_by_db, edges_by_db = {}, {}
    for database in metadata:
        names = database["table_names_original"]
        primary = set()
        for item in database["primary_keys"]:
            primary.update(item if isinstance(item, (list, tuple)) else [item])
        by_index, docs, edges = {}, {}, defaultdict(set)
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
            docs[column_id] = {"id": column_id, "table": table, "column": column,
                               "type": column_type, "primary_key": index in primary, "text": text}
        for left, right in database["foreign_keys"]:
            if left in by_index and right in by_index:
                edges[by_index[left]].add(by_index[right])
                edges[by_index[right]].add(by_index[left])
        docs_by_db[database["db_id"]] = docs
        edges_by_db[database["db_id"]] = edges
    return docs_by_db, edges_by_db


def verify_catalog(db_path, docs):
    connection = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
    try:
        physical = {}
        for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            identifier = '"' + table.replace('"', '""') + '"'
            physical[table.lower()] = {row[1].lower() for row in connection.execute(f"PRAGMA table_info({identifier})")}
        missing = [item["id"] for item in docs.values()
                   if item["table"].lower() not in physical
                   or item["column"].lower() not in physical[item["table"].lower()]]
        if missing:
            raise ValueError(f"Metadata columns absent from {db_path}: {missing[:10]}")
    finally:
        connection.close()


def grouped_schema(selected, docs):
    grouped = {}
    for column_id in sorted(selected, key=str.lower):
        item = docs[column_id]
        grouped.setdefault(item["table"], []).append({"name": item["column"], "type": item["type"], "primary_key": item["primary_key"]})
    return [{"table": table, "columns": columns} for table, columns in grouped.items()]


def select_columns(ranked, edges, method, k):
    seed = set(ranked[:k])
    selected = set(seed)
    if method == "fk1":
        for column in seed:  # Deliberately never recurse through newly added columns.
            selected.update(edges.get(column, ()))
    return selected


def render(selected, docs, tokenizer):
    ordered = tuple(sorted(selected, key=str.lower))
    text = "\n".join(docs[column]["text"] for column in ordered)
    return text, len(tokenizer.encode(text, add_special_tokens=False)), ordered


def distribution(values):
    values = sorted(values)
    def quantile(p):
        index = (len(values) - 1) * p
        lower = int(index)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (index - lower)
    return {"mean": mean(values), "min": min(values), "p05": quantile(.05), "p25": quantile(.25),
            "median": median(values), "p75": quantile(.75), "p95": quantile(.95), "max": max(values)}


def choose_200(token_means):
    """This function accepts token statistics only, never gold or model outputs."""
    candidates = []
    for plain_k, plain_mean in token_means["plain"].items():
        for fk_k, fk_mean in token_means["fk1"].items():
            target_distance = abs(plain_mean - 200) + abs(fk_mean - 200)
            imbalance = abs(fk_mean - plain_mean)
            candidates.append({"plain_k": plain_k, "fk1_k": fk_k,
                               "plain_mean_schema_tokens": plain_mean, "fk1_mean_schema_tokens": fk_mean,
                               "target_distance": target_distance, "pair_imbalance": imbalance,
                               "objective": target_distance + imbalance})
    candidates.sort(key=lambda c: (c["objective"], c["target_distance"], c["pair_imbalance"], c["plain_k"], c["fk1_k"]))
    return candidates[0], candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rankings", "base-variants", "metadata", "data-root", "tokenizer", "output-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), local_files_only=True)
    rankings = read_jsonl(args.rankings)
    bases = [row for row in read_jsonl(args.base_variants) if row["perturbation"]["family"] == "base"]
    ranks_by_qid = {row["question_id"]: row for row in rankings}
    qids = [base["question_id"] for base in bases]
    if len(bases) != 500 or len(rankings) != 500 or len(set(qids)) != 500 or len(ranks_by_qid) != 500 or set(qids) != set(ranks_by_qid):
        raise ValueError("Expected the same 500 unique base question IDs and BGE rankings")
    if len({base["question_index"] for base in bases}) != 500:
        raise ValueError("Base question_index values must be unique")
    docs_by_db, edges_by_db = build_catalog(json.loads(args.metadata.read_text(encoding="utf-8")))
    for db_id, path in {row["db_id"]: args.data_root / row["database_path"] for row in bases}.items():
        verify_catalog(path, docs_by_db[db_id])
    # Project away all gold/bridge/outcome fields for calibration and selection.
    retrieval_inputs = []
    for base in bases:
        ranking = ranks_by_qid[base["question_id"]]
        ranked = ranking["top_columns"]
        if ranking["db_id"] != base["db_id"] or len(ranked) != len(set(ranked)) or any(column not in docs_by_db[base["db_id"]] for column in ranked):
            raise ValueError(f"Invalid ranking/database for question {base['question_id']}")
        retrieval_inputs.append({"question_id": base["question_id"], "db_id": base["db_id"], "ranked": ranked})
    max_k = max(len(row["ranked"]) for row in retrieval_inputs)
    if any(not row["ranked"] for row in retrieval_inputs):
        raise ValueError("Every question must have at least one ranked column")
    token_counts = {method: {k: [] for k in range(1, max_k + 1)} for method in ("plain", "fk1")}
    for row in retrieval_inputs:
        docs, edges = docs_by_db[row["db_id"]], edges_by_db[row["db_id"]]
        for method in token_counts:
            for k in token_counts[method]:
                selected = select_columns(row["ranked"], edges, method, k)
                token_counts[method][k].append(render(selected, docs, tokenizer)[1])
    token_means = {method: {k: mean(values) for k, values in counts.items()} for method, counts in token_counts.items()}
    chosen, candidates = choose_200(token_means)
    fixed_ks = {"130": {"plain": 12, "fk1": 10}, "200": {"plain": chosen["plain_k"], "fk1": chosen["fk1_k"]}}
    # All k values are now frozen; gold fields below are diagnostic only.
    variants, selection_rows = [], []
    excluded_base_fields = {"variant_id", "perturbation", "schema", "schema_columns", "schema_text", "schema_token_budget"}
    for base, retrieval in zip(bases, retrieval_inputs):
        qid, db_id = base["question_id"], base["db_id"]
        docs, edges = docs_by_db[db_id], edges_by_db[db_id]
        ranking = ranks_by_qid[qid]
        for target, methods in fixed_ks.items():
            for method, k in methods.items():
                selected = select_columns(retrieval["ranked"], edges, method, k)
                schema_text, token_count, ordered = render(selected, docs, tokenizer)
                family = f"{method}_fixed"
                variant_id = f"q{base['question_index']:04d}__{family}_{target}"
                variants.append({
                    **{key: value for key, value in base.items() if key not in excluded_base_fields},
                    "variant_id": variant_id,
                    "perturbation": {"variant_id": variant_id, "family": family, "level": int(target), "added": [], "removed": []},
                    "schema": grouped_schema(selected, docs), "schema_columns": list(ordered), "schema_text": schema_text,
                    "schema_token_target": int(target), "schema_token_count": token_count,
                    "retrieval_k": k, "fixed_seed_k": k, "retrieval_method": method,
                    "retrieval_model": "BAAI/bge-base-en-v1.5", "selection_protocol": "fixed_k_no_per_question_token_cap",
                })
                gold = set(base["gold_columns"])
                bridge_fk = set(ranking["bridge_columns"]) | set(ranking["fk_columns"])
                selection_rows.append({
                    "variant_id": variant_id, "question_id": qid, "db_id": db_id, "family": f"{family}_{target}",
                    "token_target": int(target), "token_count": token_count, "retrieval_k": k,
                    "actual_seed_count": min(k, len(retrieval["ranked"])),
                    "selected_column_count": len(selected), "fk_added_column_count": len(selected) - min(k, len(retrieval["ranked"])),
                    "gold_column_hits": len(gold & selected), "gold_column_total": len(gold),
                    "bridge_fk_hits": len(bridge_fk & selected), "bridge_fk_total": len(bridge_fk),
                })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / "fixed_variants.jsonl"
    write_jsonl(out, variants)
    metrics_path = args.output_dir / "selection_metrics.jsonl"
    write_jsonl(metrics_path, selection_rows)
    by_family = {}
    for target, methods in fixed_ks.items():
        for method, k in methods.items():
            family = f"{method}_fixed_{target}"
            rows = [row for row in selection_rows if row["family"] == family]
            totals = {key: sum(row[key] for row in rows) for key in ("gold_column_hits", "gold_column_total", "bridge_fk_hits", "bridge_fk_total")}
            tokens = distribution([row["token_count"] for row in rows])
            by_family[family] = {
                "questions": len(rows), "fixed_seed_k": k, "mean_seed_k": mean(row["actual_seed_count"] for row in rows),
                "questions_with_fewer_than_k_candidates": sum(row["actual_seed_count"] < k for row in rows),
                "mean_schema_tokens": tokens["mean"], "median_schema_tokens": tokens["median"], "schema_tokens": tokens,
                "mean_selected_columns": mean(row["selected_column_count"] for row in rows),
                "mean_fk_added_columns": mean(row["fk_added_column_count"] for row in rows),
                "gold_column_recall": totals["gold_column_hits"] / totals["gold_column_total"] if totals["gold_column_total"] else None,
                "bridge_fk_recall": totals["bridge_fk_hits"] / totals["bridge_fk_total"] if totals["bridge_fk_total"] else None,
            }
    selection_index = {(r["question_id"], r["family"]): r for r in selection_rows}
    differences = {target: distribution([selection_index[(qid, f"fk1_fixed_{target}")]["token_count"] - selection_index[(qid, f"plain_fixed_{target}")]["token_count"] for qid in qids]) for target in fixed_ks}
    tokenizer_files = {str(path.relative_to(args.tokenizer)): sha256(path) for path in sorted(args.tokenizer.glob("*")) if path.is_file() and ("token" in path.name or path.name in {"vocab.json", "merges.txt", "special_tokens_map.json", "config.json"})}
    summary = {
        "definition": "Fixed k over all 500 questions; target labels 130/200 are nominal mean-token targets, not per-question caps or exact token matching",
        "question_count": 500, "variant_count": len(variants), "targets": [130, 200], "fixed_ks": fixed_ks,
        "retriever": "BAAI/bge-base-en-v1.5", "tokenizer": str(args.tokenizer),
        "token_counting": "Exact schema_text encoded with add_special_tokens=False; excludes prompt/question/evidence",
        "fk_definition": "Undirected declared FK endpoints, one hop from the original seed columns only; deduplicate; alphabetical column rendering",
        "protocol": {"130": "Teacher-prespecified plain top-12 versus top-10 plus one-hop FK",
                     "200": "One cohort-wide fixed integer pair chosen using schema token counts only before model outcomes",
                     "gold_usage": "Gold SQL/columns and bridge/FK diagnostic labels never influence selection or calibration; recall computed only after k is frozen",
                     "outcome_usage": "No model outputs, scores, server calls or model/API generation are read or performed",
                     "candidate_k_domain": [1, max_k],
                     "small_catalog_rule": "Standard top-k returns min(k, number of ranked candidates); retain all 500 questions and report saturation counts",
                     "calibration_cohort": "Same fixed 500 questions; calibration is descriptive input-length matching, not held-out performance tuning",
                     "criterion": "abs(mean_plain-200) + abs(mean_fk1-200) + abs(mean_fk1-mean_plain)",
                     "tie_break": ["objective", "target_distance", "pair_imbalance", "plain_k", "fk1_k"],
                     "chosen_200": chosen, "candidate_token_means": token_means, "candidate_pairs": candidates},
        "provenance": {"generator_sha256": sha256(Path(__file__)), "tokenizer_files_sha256": tokenizer_files,
                       "rankings_path": str(args.rankings), "base_variants_path": str(args.base_variants), "metadata_path": str(args.metadata)},
        "rankings_sha256": sha256(args.rankings), "base_variants_sha256": sha256(args.base_variants),
        "metadata_sha256": sha256(args.metadata), "variants_sha256": sha256(out),
        "selection_metrics_sha256": sha256(metrics_path), "by_family": by_family,
        "fk1_minus_plain_token_distribution": differences,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"variant_count": len(variants), "fixed_ks": fixed_ks, "by_family": by_family}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
