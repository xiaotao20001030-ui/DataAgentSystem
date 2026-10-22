#!/usr/bin/env python3
"""Recompute retrieval miss rates with a matched multi-table baseline.

The original report compared bridge/join columns (which only occur in
multi-table questions) against target columns from single-table questions.
That comparison mixes column role with question type. This script keeps the
same retrieval setup but adds a within-question baseline:

  - multi_nonbridge: gold columns in multi-table questions that are neither
    bridge-table columns nor join/FK columns
  - bridge_cols: gold columns that belong to a bridge table
  - fk_cols: columns that appear in a gold join edge

It reports aggregate miss rates and question-clustered paired differences
between bridge/FK columns and the matched multi-table baseline.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=project_root / "mini_dev_data",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "analysis" / "retrieval_matched",
    )
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
    )
    parser.add_argument(
        "--text-format",
        choices=("qualified", "name"),
        default="qualified",
        help="Column document text: 'table.column' or the bare column name.",
    )
    parser.add_argument(
        "--query",
        choices=("question", "question_evidence"),
        default="question",
    )
    parser.add_argument(
        "--top-k",
        default="5,10,20,50",
        help="Comma-separated k values.",
    )
    parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--max-questions", type=int, default=None)
    return parser.parse_args()


def parse_ks(value):
    return tuple(sorted({int(item) for item in value.split(",") if item.strip()}))


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def column_document(column, text_format):
    if text_format == "name":
        return column["column"]
    return f"{column['table']}.{column['column']}"


def corpus_by_database(metadata, text_format):
    corpus = {}
    for item in metadata:
        corpus[item["db_id"]] = [
            column_document(column, text_format)
            for column in item["columns"]
        ]
    return corpus


def target_keys(columns, text_format):
    if text_format == "name":
        return {column.split(".", 1)[1] for column in columns}
    return set(columns)


def build_categories(structure):
    gold = [column["id"] for column in structure["columns"]]
    bridge_tables = {table.lower() for table in structure["bridge_tables"]}
    bridge_cols = {
        column
        for column in gold
        if column.split(".", 1)[0].lower() in bridge_tables
    }
    fk_cols = {
        column for edge in structure["join_edges"] for column in edge["columns"]
    }
    multi = len(structure["tables"]) > 1
    multi_nonbridge = (
        set(gold) - bridge_cols - fk_cols if multi else set()
    )
    single = set(gold) if not multi else set()
    return {
        "single": single,
        "multi_all": set(gold) if multi else set(),
        "multi_nonbridge": multi_nonbridge,
        "bridge_cols": bridge_cols,
        "fk_cols": fk_cols,
        "union": bridge_cols | fk_cols,
    }


def bootstrap_mean(values, iterations, seed):
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return None
    rng = np.random.default_rng(seed)
    draws = np.empty(iterations)
    for index in range(iterations):
        sample = rng.integers(0, len(values), len(values))
        draws[index] = values[sample].mean()
    return {
        "n_questions": int(len(values)),
        "mean": float(values.mean()),
        "ci95": [
            float(np.quantile(draws, 0.025)),
            float(np.quantile(draws, 0.975)),
        ],
    }


def paired_miss_difference(rows, left, right, level, iterations, seed):
    pairs = [
        (row[(left, level)], row[(right, level)])
        for row in rows
        if row[(left, level)][1] > 0 and row[(right, level)][1] > 0
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
    return bootstrap_mean(differences, iterations, seed)


def main():
    args = parse_args()
    script_dir = Path(__file__).resolve().parents[1] / "perturbations"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import generate_perturbations as gp

    from sentence_transformers import SentenceTransformer, util

    ks = parse_ks(args.top_k)
    data_root = args.data_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    questions = json.loads(
        (data_root / "mini_dev_sqlite.json").read_text(encoding="utf-8")
    )[:500]
    metadata = json.loads(
        (data_root / "dev_tables.json").read_text(encoding="utf-8")
    )
    if args.max_questions is not None:
        questions = questions[: args.max_questions]

    schema_by_db = {
        item["db_id"]: gp.build_schema_index(item) for item in metadata
    }
    corpus = {
        db_id: [
            column_document(column, args.text_format)
            for column in schema_index["columns"]
        ]
        for db_id, schema_index in schema_by_db.items()
    }
    model = SentenceTransformer(args.model)
    column_embeddings = {
        db_id: model.encode(
            documents,
            convert_to_tensor=True,
            normalize_embeddings=True,
        )
        for db_id, documents in corpus.items()
    }

    query_texts = [
        question["question"]
        + (
            "\n" + question.get("evidence", "")
            if args.query == "question_evidence"
            and question.get("evidence")
            else ""
        )
        for question in questions
    ]
    query_embeddings = model.encode(
        query_texts,
        convert_to_tensor=True,
        normalize_embeddings=True,
    )

    categories = ["single", "multi_all", "multi_nonbridge", "bridge_cols", "fk_cols", "union"]
    per_k = {
        k: {
            category: {"missed": 0, "total": 0}
            for category in categories
        }
        for k in ks
    }
    rows_for_paired = []
    per_question_rates = {
        k: {category: [] for category in categories} for k in ks
    }

    for index, question in enumerate(questions):
        structure = gp.analyze_question(
            question,
            None,
            schema_by_db[question["db_id"]],
        )
        category_sets = build_categories(structure)
        documents = corpus[question["db_id"]]
        scores = util.cos_sim(
            query_embeddings[index],
            column_embeddings[question["db_id"]],
        )[0].cpu().numpy()
        order = np.argsort(-scores)
        row = {}
        for k in ks:
            top = {documents[position] for position in order[:k]}
            for category in categories:
                keys = target_keys(category_sets[category], args.text_format)
                missed = sum(column not in top for column in keys)
                per_k[k][category]["missed"] += missed
                per_k[k][category]["total"] += len(keys)
                if len(keys):
                    per_question_rates[k][category].append(
                        missed / len(keys)
                    )
                if category in (
                    "multi_nonbridge",
                    "bridge_cols",
                    "fk_cols",
                    "union",
                ):
                    row[(category, k)] = (missed, len(keys))
        rows_for_paired.append(row)

    paired = {}
    for k in ks:
        paired[k] = {}
        for left, right in (
            ("bridge_cols", "multi_nonbridge"),
            ("fk_cols", "multi_nonbridge"),
            ("union", "multi_nonbridge"),
            ("bridge_cols", "fk_cols"),
        ):
            paired[k][f"{left}_minus_{right}"] = paired_miss_difference(
                rows_for_paired,
                left,
                right,
                k,
                args.bootstrap,
                args.seed,
            )

    def summarize(category, k):
        values = per_k[k][category]
        total = values["total"]
        rates = per_question_rates[k][category]
        return {
            "missed": values["missed"],
            "total": total,
            "miss_rate": (values["missed"] / total) if total else None,
            "miss_rate_pct": (100 * values["missed"] / total) if total else None,
            "macro_miss_rate": (sum(rates) / len(rates)) if rates else None,
            "macro_miss_rate_pct": (
                100 * sum(rates) / len(rates) if rates else None
            ),
            "n_questions": len(rates),
        }

    report = {
        "model": args.model,
        "text_format": args.text_format,
        "query": args.query,
        "question_count": len(questions),
        "results": {
            str(k): {
                category: summarize(category, k) for category in categories
            }
            for k in ks
        },
        "paired_by_question": {
            str(k): values for k, values in paired.items()
        },
    }
    (output_dir / "retrieval_matched.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Retrieval matched-baseline re-analysis",
        "",
        f"- model: `{args.model}`",
        f"- column text: `{args.text_format}`",
        f"- query: `{args.query}`",
        f"- questions: {len(questions)}",
        "",
        "## Miss rates",
        "",
        "| k | " + " | ".join(categories) + " |",
        "| ---: | " + " | ".join("---:" for _ in categories) + " |",
    ]
    for k in ks:
        values = [
            f"{report['results'][str(k)][category]['miss_rate_pct']:.2f}%"
            if report["results"][str(k)][category]["miss_rate_pct"] is not None
            else "-"
            for category in categories
        ]
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
                f"{result['mean'] * 100:.2f} pp | "
                f"[{result['ci95'][0] * 100:.2f}, "
                f"{result['ci95'][1] * 100:.2f}] pp |"
            )
    (output_dir / "retrieval_matched.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"json": str(output_dir / "retrieval_matched.json"), "markdown": str(output_dir / "retrieval_matched.md")}, indent=2))


if __name__ == "__main__":
    main()
