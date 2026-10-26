#!/usr/bin/env python3
"""Build a 20-column synonym distractor set using only real schema columns."""

import argparse
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


MIN_SIMILARITY = 0.25
TARGET_COUNT = 20


def tokens(name):
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return {
        token.lower()
        for token in re.split(r"[^A-Za-z0-9]+", expanded)
        if token
    }


def name_similarity(left, right):
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / len(union) if union else 0
    sequence_score = SequenceMatcher(
        None,
        left.lower(),
        right.lower(),
    ).ratio()
    return max(token_score, sequence_score)


def schema_groups(columns):
    grouped = {}
    order = []
    for column in columns:
        if column["table"] not in grouped:
            grouped[column["table"]] = []
            order.append(column["table"])
        grouped[column["table"]].append(
            {
                "name": column["column"],
                "type": column.get("type", "TEXT"),
                "primary_key": bool(column.get("primary_key", False)),
            }
        )
    return [
        {"table": table, "columns": grouped[table]}
        for table in order
    ]


def build_schema(meta):
    table_names = meta["table_names_original"]
    primary_keys = set()
    for primary_key in meta["primary_keys"]:
        if isinstance(primary_key, (list, tuple)):
            primary_keys.update(primary_key)
        else:
            primary_keys.add(primary_key)

    columns = []
    for index, (table_index, column_name) in enumerate(
        meta["column_names_original"]
    ):
        if table_index < 0:
            continue
        table = table_names[table_index]
        columns.append(
            {
                "id": f"{table}.{column_name}",
                "table": table,
                "column": column_name,
                "type": meta["column_types"][index] or "TEXT",
                "primary_key": index in primary_keys,
            }
        )
    return columns


def build_record(base, schema_columns):
    base_ids = set(base["gold_columns"])
    base_objects = []
    base_lookup = {}
    for table in base["schema"]:
        for column in table["columns"]:
            column_id = f"{table['table']}.{column['name']}"
            base_lookup[column_id] = {
                "id": column_id,
                "table": table["table"],
                "column": column["name"],
                "type": column["type"],
                "primary_key": column["primary_key"],
            }
    for column_id in base["gold_columns"]:
        if column_id in base_lookup:
            base_objects.append(base_lookup[column_id])

    candidates = []
    seen = set(base_ids)
    for candidate in schema_columns:
        if candidate["id"] in seen:
            continue

        best_seed = None
        best_score = -1.0
        for seed in base_objects:
            similarity = name_similarity(
                candidate["column"],
                seed["column"],
            )
            if similarity > best_score:
                best_score = similarity
                best_seed = seed

        if best_seed is None or best_score < MIN_SIMILARITY:
            continue
        candidates.append(
            {
                **candidate,
                "generated": False,
                "relation": "real_synonym",
                "seed_column": best_seed["id"],
                "similarity_score": round(best_score, 6),
                "same_type_as_seed": candidate["type"] == best_seed["type"],
            }
        )

    candidates.sort(
        key=lambda column: (
            -(
                column["similarity_score"]
                + (0.03 if column["same_type_as_seed"] else 0)
            ),
            column["id"].lower(),
        )
    )
    extras = candidates[:TARGET_COUNT]
    if len(extras) != TARGET_COUNT:
        return None, len(candidates)

    variant = {
        "variant_id": (
            f"q{base['question_index']:04d}__add_real_synonym_20"
        ),
        "question_index": base["question_index"],
        "question_id": base["question_id"],
        "db_id": base["db_id"],
        "question": base["question"],
        "evidence": base["evidence"],
        "gold_sql": base["gold_sql"],
        "difficulty": base["difficulty"],
        "database_path": base["database_path"],
        "perturbation": {
            "variant_id": (
                f"q{base['question_index']:04d}__add_real_synonym_20"
            ),
            "family": "add_real_synonym",
            "level": TARGET_COUNT,
            "added": extras,
            "removed": [],
        },
        "gold_tables": base["gold_tables"],
        "gold_columns": base["gold_columns"],
        "schema_columns": base["gold_columns"]
        + [column["id"] for column in extras],
        "schema": schema_groups(base_objects + extras),
        "join_edges": base["join_edges"],
        "bridge_tables": base["bridge_tables"],
    }
    return variant, len(candidates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    data_root = project_root / "mini_dev_data"
    source = (
        project_root / "perturbations" / "output"
        / "mini_dev_perturbations.jsonl"
    )
    output_dir = (
        project_root / "perturbations" / "output"
        / "real_synonym_sensitivity"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        item["db_id"]: item
        for item in json.loads(
            (data_root / "dev_tables.json").read_text(encoding="utf-8")
        )
    }
    schema_by_db = {
        db_id: build_schema(item)
        for db_id, item in metadata.items()
    }
    rows = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    bases = [
        row for row in rows
        if row["perturbation"]["family"] == "base"
    ]

    variants = []
    eligible_candidate_counts = []
    excluded = []
    for base in bases:
        variant, candidate_count = build_record(
            base,
            schema_by_db[base["db_id"]],
        )
        eligible_candidate_counts.append(candidate_count)
        if variant is None:
            excluded.append(
                {
                    "question_id": base["question_id"],
                    "eligible_candidates": candidate_count,
                }
            )
        else:
            variants.append(variant)

    output_path = output_dir / "mini_dev_add_real_synonym_20.jsonl"
    output_path.write_text(
        "".join(
            json.dumps(variant, ensure_ascii=False, separators=(",", ":"))
            + "\n"
            for variant in variants
        ),
        encoding="utf-8",
    )
    summary = {
        "definition": (
            "20 unused real schema columns with name similarity >= 0.25 "
            "to at least one gold column; no synthetic columns"
        ),
        "source_questions": len(bases),
        "generated_variants": len(variants),
        "excluded_questions": len(excluded),
        "minimum_candidates": min(eligible_candidate_counts),
        "maximum_candidates": max(eligible_candidate_counts),
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "excluded": excluded,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
