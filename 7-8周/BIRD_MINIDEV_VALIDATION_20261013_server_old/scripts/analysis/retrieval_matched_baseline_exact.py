#!/usr/bin/env python3
"""Exact retrieval re-analysis with a matched multi-table baseline.

Run this on the BIRD server where the original evaluate_retrieval_bias.py
lives. It reuses that script's document construction and label sets, so the
original category counts are preserved, and adds the missing comparison:

    multi_nonbridge = gold columns in multi-table questions minus
                      bridge-table columns minus FK/join columns

The paired bootstrap below is within question, so it removes the
single-table vs multi-table confounding in the original gate.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/root/fsas/home/xiaotao/xiaotao/MINIDEV"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "/root/fsas/home/xiaotao/xiaotao/MINIDEV/BIRD_RESULTS/analysis"
        ),
    )
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--include-evidence", action="store_true")
    parser.add_argument("--k", default="5,10,20,50")
    parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261019)
    return parser.parse_args()


def parse_ks(value):
    return tuple(sorted({int(item) for item in value.split(",") if item.strip()}))


def aggregate(events):
    # events are (missed, total) pairs
    misses = sum(event[0] for event in events)
    total = sum(event[1] for event in events)
    hits = total - misses
    return {
        "hits": hits,
        "total": total,
        "misses": misses,
        "miss_rate": misses / total if total else None,
        "miss_rate_pct": 100 * misses / total if total else None,
    }


def bootstrap_paired(rows, left, right, k, iterations, seed):
    pairs = [
        (row[(left, k)], row[(right, k)])
        for row in rows
        if row[(left, k)][1] > 0 and row[(right, k)][1] > 0
    ]
    if not pairs:
        return None
    differences = np.array(
        [
            left_miss / left_total - right_miss / right_total
            for (left_miss, left_total), (right_miss, right_total) in pairs
        ],
        dtype=float,
    )
    rng = np.random.default_rng(seed)
    draws = np.empty(iterations)
    for index in range(iterations):
        sample = rng.integers(0, len(differences), len(differences))
        draws[index] = differences[sample].mean()
    return {
        "n_questions": len(pairs),
        "difference": float(differences.mean()),
        "difference_pp": float(differences.mean() * 100),
        "ci95": [
            float(np.quantile(draws, 0.025)),
            float(np.quantile(draws, 0.975)),
        ],
        "ci95_pp": [
            float(np.quantile(draws, 0.025) * 100),
            float(np.quantile(draws, 0.975) * 100),
        ],
    }


def main():
    args = parse_args()
    root = args.root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    scripts_dir = root / "BIRD_RESULTS" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import evaluate_retrieval_bias as original

    from sentence_transformers import SentenceTransformer

    ks = parse_ks(args.k)
    data_root = root
    perturbation_root = root / "perturbations" / "output"

    questions = json.loads(
        (data_root / "mini_dev_sqlite.json").read_text(encoding="utf-8")
    )[:500]
    metadata = json.loads(
        (data_root / "dev_tables.json").read_text(encoding="utf-8")
    )
    structures = original.read_jsonl(
        perturbation_root / "question_structures.jsonl"
    )
    perturbations = original.read_jsonl(
        perturbation_root / "mini_dev_perturbations.jsonl"
    )
    structure_by_id = {item["question_id"]: item for item in structures}
    labels = original.build_label_sets(perturbations)
    documents_by_db = original.build_schema_documents(metadata)

    model = SentenceTransformer(
        args.model,
        device=args.device,
        local_files_only=True,
    )
    document_embeddings = {
        db_id: model.encode(
            [document["text"] for document in documents],
            batch_size=args.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        for db_id, documents in documents_by_db.items()
    }

    query_texts = []
    for item in questions:
        query = item["question"]
        if args.include_evidence and item.get("evidence"):
            query = f"{query}\nEvidence: {item['evidence']}"
        query_texts.append(query)
    query_embeddings = model.encode(
        query_texts,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    categories = [
        "single",
        "multi_all",
        "multi_nonbridge",
        "bridge_cols",
        "fk_cols",
        "union",
        "bridge_tables",
    ]
    aggregate_counts = {
        k: {category: [0, 0] for category in categories} for k in ks
    }
    rows = []

    for item, query_embedding in zip(questions, query_embeddings):
        documents = documents_by_db[item["db_id"]]
        scores = document_embeddings[item["db_id"]] @ query_embedding
        top_indices = np.argsort(-scores)[: max(ks)]
        structure = structure_by_id[item["question_id"]]
        label = labels[item["question_id"]]
        gold = set(structure["gold_columns"])
        bridge_cols = set(label["bridge_table_columns"])
        fk_cols = set(label["fk_columns"])
        is_multi = structure["question_type"] == "multi"
        multi_nonbridge = (
            gold - bridge_cols - fk_cols if is_multi else set()
        )
        single = gold if not is_multi else set()
        union = bridge_cols | fk_cols
        bridge_tables = set(label["bridge_tables"])

        row = {}
        for k in ks:
            top_columns = {
                documents[index]["column_id"] for index in top_indices[:k]
            }
            top_tables = {
                column.split(".", 1)[0] for column in top_columns
            }
            values = {
                "single": single,
                "multi_all": gold if is_multi else set(),
                "multi_nonbridge": multi_nonbridge,
                "bridge_cols": bridge_cols,
                "fk_cols": fk_cols,
                "union": union,
            }
            for category, columns in values.items():
                missed = sum(column not in top_columns for column in columns)
                aggregate_counts[k][category][0] += missed
                aggregate_counts[k][category][1] += len(columns)
                row[(category, k)] = (missed, len(columns))
            # Table-level bridge coverage: hit if any column of the table is
            # in top-k. This is not directly comparable with column-level
            # categories; it is reported for continuity with the original.
            table_hits = sum(
                1 for table in bridge_tables if table in top_tables
            )
            aggregate_counts[k]["bridge_tables"][0] += (
                len(bridge_tables) - table_hits
            )
            aggregate_counts[k]["bridge_tables"][1] += len(bridge_tables)
            row[("bridge_tables", k)] = (
                len(bridge_tables) - table_hits,
                len(bridge_tables),
            )
        rows.append(row)

    paired = {}
    for k in ks:
        paired[k] = {}
        for left, right in (
            ("bridge_cols", "multi_nonbridge"),
            ("fk_cols", "multi_nonbridge"),
            ("union", "multi_nonbridge"),
            ("bridge_cols", "fk_cols"),
        ):
            paired[k][f"{left}_minus_{right}"] = bootstrap_paired(
                rows,
                left,
                right,
                k,
                args.bootstrap,
                args.seed,
            )

    report = {
        "model": args.model,
        "query_mode": "question+evidence"
        if args.include_evidence
        else "question",
        "question_count": len(questions),
        "k_values": list(ks),
        "results": {
            str(k): {
                category: aggregate(
                    [
                        (
                            row[(category, k)][0],
                            row[(category, k)][1],
                        )
                        for row in rows
                        if row[(category, k)][1] > 0
                    ]
                )
                for category in categories
            }
            for k in ks
        },
        "paired_by_question": {
            str(k): values for k, values in paired.items()
        },
    }
    (output_dir / "retrieval_matched_exact.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Retrieval matched-baseline re-analysis (exact original setup)",
        "",
        f"- model: `{args.model}`",
        f"- query: `{report['query_mode']}`",
        f"- questions: {len(questions)}",
        "",
        "## Miss rates",
        "",
        "| k | " + " | ".join(categories) + " |",
        "| ---: | " + " | ".join("---:" for _ in categories) + " |",
    ]
    for k in ks:
        values = []
        for category in categories:
            value = report["results"][str(k)][category]["miss_rate_pct"]
            values.append(f"{value:.2f}%" if value is not None else "-")
        lines.append(f"| {k} | " + " | ".join(values) + " |")

    lines.extend(
        [
            "",
            "## Paired within-question differences",
            "",
            "| k | comparison | n questions | diff | 95% CI |",
            "| ---: | --- | ---: | ---: | --- |",
        ]
    )
    for k in ks:
        for comparison, result in paired[k].items():
            if result is None:
                lines.append(f"| {k} | {comparison} | 0 | - | - |")
                continue
            lines.append(
                f"| {k} | {comparison} | {result['n_questions']} | "
                f"{result['difference_pp']:.2f} pp | "
                f"[{result['ci95_pp'][0]:.2f}, "
                f"{result['ci95_pp'][1]:.2f}] pp |"
            )
    (output_dir / "retrieval_matched_exact.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "json": str(output_dir / "retrieval_matched_exact.json"),
                "markdown": str(output_dir / "retrieval_matched_exact.md"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
