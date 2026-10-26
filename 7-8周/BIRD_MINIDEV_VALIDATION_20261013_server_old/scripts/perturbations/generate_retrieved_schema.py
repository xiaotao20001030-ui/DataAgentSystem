#!/usr/bin/env python3
"""Build a retrieved-schema execution condition for BIRD Mini-Dev.

For each question, retrieve the top-k columns from its database with the same
question-only MiniLM setup used by the retrieval analysis, then expose only
those columns (grouped by table) to the SQL generator. This condition links
retrieval misses to execution failures; it is separate from the oracle-schema
execution experiments in the main report.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_perturbations as gp


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
        default=project_root / "perturbations" / "output" / "retrieved_schema",
    )
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
    )
    parser.add_argument(
        "--query",
        choices=("question", "question_evidence"),
        default="question",
    )
    parser.add_argument("--seed", type=int, default=gp.DEFAULT_SEED)
    return parser.parse_args()


def column_document(column):
    return f"{column['table']}.{column['column']}"


def main():
    args = parse_args()
    from sentence_transformers import SentenceTransformer, util

    data_root = args.data_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    questions = json.loads(
        (data_root / "mini_dev_sqlite.json").read_text(encoding="utf-8")
    )[:500]
    metadata = json.loads(
        (data_root / "dev_tables.json").read_text(encoding="utf-8")
    )
    if len(questions) != 500:
        raise SystemExit(f"Expected 500 questions, found {len(questions)}")

    schema_by_db = {
        item["db_id"]: gp.build_schema_index(item) for item in metadata
    }
    corpus = {
        db_id: [column_document(column) for column in index["columns"]]
        for db_id, index in schema_by_db.items()
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

    records = []
    recalls = []
    retrieved_table_counts = []
    retrieved_column_counts = []
    for index, question in enumerate(questions):
        schema_index = schema_by_db[question["db_id"]]
        structure = gp.analyze_question(question, None, schema_index)
        documents = corpus[question["db_id"]]
        scores = util.cos_sim(
            query_embeddings[index],
            column_embeddings[question["db_id"]],
        )[0].cpu().numpy()
        order = np.argsort(-scores)[: args.k]
        retrieved = [
            schema_index["columns"][int(position)] for position in order
        ]
        retrieved_ids = [column["id"] for column in retrieved]
        gold_ids = [column["id"] for column in structure["columns"]]
        recalled = sum(column in set(retrieved_ids) for column in gold_ids)
        recalls.append(recalled / len(gold_ids) if gold_ids else None)
        retrieved_table_counts.append(
            len({column["table"] for column in retrieved})
        )
        retrieved_column_counts.append(len(retrieved))
        perturbation = {
            "variant_id": f"q{index:04d}__retrieved_k{args.k}",
            "family": "retrieved_schema",
            "level": args.k,
            "added": [],
            "removed": [],
            "retrieved_columns": retrieved_ids,
            "retrieval_query": args.query,
            "retrieval_model": args.model,
            "gold_column_recall": recalled / len(gold_ids) if gold_ids else None,
        }
        records.append(
            gp.variant_record(
                item=question,
                question_index=index,
                family="base",
                level=None,
                added=[],
                removed=[],
                schema_columns=structure["columns"],
                structure=structure,
            )
        )
        records.append(
            gp.make_record(
                item=question,
                question_index=index,
                perturbation=perturbation,
                gold_tables=structure["tables"],
                gold_columns=structure["columns"],
                join_edges=structure["join_edges"],
                bridge_tables=structure["bridge_tables"],
                schema_columns=retrieved,
            )
        )

    path = output_dir / "mini_dev_retrieved_schema.jsonl"
    with path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            )
            output.write("\n")

    summary = {
        "dataset": "BIRD Mini-Dev SQLite",
        "question_count": len(records) // 2,
        "base_variant_count": sum(
            record["perturbation"]["family"] == "base" for record in records
        ),
        "k": args.k,
        "query": args.query,
        "model": args.model,
        "retrieved_column_counts": dict(
            Counter(retrieved_column_counts).most_common()
        ),
        "retrieved_table_count_mean": sum(retrieved_table_counts)
        / len(retrieved_table_counts),
        "gold_column_recall_mean": (
            sum(recall for recall in recalls if recall is not None)
            / sum(recall is not None for recall in recalls)
        ),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "output": path.name,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
