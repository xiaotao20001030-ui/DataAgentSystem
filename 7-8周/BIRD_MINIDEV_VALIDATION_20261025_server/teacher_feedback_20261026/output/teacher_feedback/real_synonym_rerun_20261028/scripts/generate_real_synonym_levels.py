#!/usr/bin/env python3
"""Generate real-schema-only BIRD Mini-Dev synonym distractor variants.

Candidates are drawn from each question's actual database schema, ranked by
column-name similarity to gold columns, then verified against SQLite PRAGMA.
No database is modified and no synthetic column names are introduced.
"""

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path


MIN_SIMILARITY = 0.25
DEFAULT_LEVELS = (5, 10, 50)


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
    sequence_score = SequenceMatcher(None, left.lower(), right.lower()).ratio()
    return max(token_score, sequence_score)


def quote_ident(value):
    return '"' + value.replace('"', '""') + '"'


def physical_schema(db_path):
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = {
            row[0].lower(): row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        columns = {}
        for lower_table, table in tables.items():
            columns[lower_table] = {
                row[1].lower(): row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({quote_ident(table)})"
                )
            }
        return connection, tables, columns
    except Exception:
        connection.close()
        raise


def build_schema(meta):
    table_names = meta["table_names_original"]
    primary_keys = set()
    for primary_key in meta["primary_keys"]:
        if isinstance(primary_key, (list, tuple)):
            primary_keys.update(primary_key)
        else:
            primary_keys.add(primary_key)

    result = []
    for index, (table_index, column_name) in enumerate(
        meta["column_names_original"]
    ):
        if table_index < 0:
            continue
        table = table_names[table_index]
        result.append(
            {
                "id": f"{table}.{column_name}",
                "table": table,
                "column": column_name,
                "type": meta["column_types"][index] or "TEXT",
                "primary_key": index in primary_keys,
            }
        )
    return result


def schema_groups(columns):
    grouped = {}
    order = []
    for column in columns:
        table = column["table"]
        if table not in grouped:
            grouped[table] = []
            order.append(table)
        grouped[table].append(
            {
                "name": column["column"],
                "type": column.get("type", "TEXT"),
                "primary_key": bool(column.get("primary_key", False)),
            }
        )
    return [{"table": table, "columns": grouped[table]} for table in order]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--source-variants", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--levels", default=",".join(map(str, DEFAULT_LEVELS)))
    args = parser.parse_args()
    levels = tuple(sorted({int(value) for value in args.levels.split(",")}))
    if not levels or any(level <= 0 for level in levels):
        raise ValueError("levels must contain positive integers")

    metadata = {
        item["db_id"]: item
        for item in json.loads(
            (args.data_root / "dev_tables.json").read_text(encoding="utf-8")
        )
    }
    schema_by_db = {db_id: build_schema(meta) for db_id, meta in metadata.items()}
    records = [
        json.loads(line)
        for line in args.source_variants.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    bases = [
        row for row in records
        if row["perturbation"]["family"] == "base"
    ]
    if len(bases) != 500:
        raise ValueError(f"Expected 500 base questions, found {len(bases)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    by_level = {level: [] for level in levels}
    excluded = {level: [] for level in levels}
    physical_checks = Counter()
    physical_cache = {}
    try:
        for base in bases:
            db_id = base["db_id"]
            db_path = args.data_root / base["database_path"]
            if db_id not in physical_cache:
                physical_cache[db_id] = physical_schema(db_path)
            connection, actual_tables, actual_columns = physical_cache[db_id]

            gold_ids = {item.lower() for item in base["gold_columns"]}
            base_objects = []
            base_lookup = {}
            for table in base["schema"]:
                for column in table["columns"]:
                    column_id = f"{table['table']}.{column['name']}"
                    base_lookup[column_id.lower()] = {
                        "id": column_id,
                        "table": table["table"],
                        "column": column["name"],
                        "type": column["type"],
                        "primary_key": column["primary_key"],
                    }
            for column_id in base["gold_columns"]:
                if column_id.lower() not in base_lookup:
                    raise ValueError(
                        f"Gold column missing from base schema: {column_id}"
                    )
                base_objects.append(base_lookup[column_id.lower()])

            for column in base_objects:
                if (
                    column["table"].lower() not in actual_tables
                    or column["column"].lower()
                    not in actual_columns.get(column["table"].lower(), {})
                ):
                    raise ValueError(
                        f"Gold schema is not physically present: {db_id} "
                        f"{column['id']}"
                    )

            candidates = []
            for candidate in schema_by_db[db_id]:
                candidate_id = candidate["id"].lower()
                if candidate_id in gold_ids:
                    continue
                table_key = candidate["table"].lower()
                column_key = candidate["column"].lower()
                if (
                    table_key not in actual_tables
                    or column_key not in actual_columns.get(table_key, {})
                ):
                    continue

                best_seed = None
                best_score = -1.0
                for seed in base_objects:
                    score = name_similarity(
                        candidate["column"], seed["column"]
                    )
                    if score > best_score:
                        best_seed = seed
                        best_score = score
                if best_seed is None or best_score < MIN_SIMILARITY:
                    continue
                candidates.append(
                    {
                        **candidate,
                        "generated": False,
                        "relation": "real_synonym",
                        "seed_column": best_seed["id"],
                        "similarity_score": round(best_score, 6),
                        "same_type_as_seed": (
                            candidate["type"] == best_seed["type"]
                        ),
                    }
                )
                physical_checks["verified_candidate_columns"] += 1

            candidates.sort(
                key=lambda column: (
                    -(
                        column["similarity_score"]
                        + (0.03 if column["same_type_as_seed"] else 0)
                    ),
                    column["id"].lower(),
                )
            )

            # Compile the unchanged gold query against the same read-only DB.
            # This verifies that the clean perturbation keeps gold executable.
            connection.execute("EXPLAIN QUERY PLAN " + base["gold_sql"])

            for level in levels:
                if len(candidates) < level:
                    excluded[level].append(
                        {
                            "question_id": base["question_id"],
                            "eligible_real_near_name_columns": len(candidates),
                        }
                    )
                    continue
                extras = candidates[:level]
                variant_id = (
                    f"q{base['question_index']:04d}__add_real_synonym_{level}"
                )
                variant = {
                    **{key: value for key, value in base.items() if key not in {"perturbation", "schema", "schema_columns"}},
                    "variant_id": variant_id,
                    "perturbation": {
                        "variant_id": variant_id,
                        "family": "add_real_synonym",
                        "level": level,
                        "added": extras,
                        "removed": [],
                    },
                    "schema_columns": base["gold_columns"]
                    + [column["id"] for column in extras],
                    "schema": schema_groups(base_objects + extras),
                }
                assert set(base["gold_columns"]).issubset(
                    set(variant["schema_columns"])
                )
                assert len(extras) == level
                assert all(not item.get("generated", False) for item in extras)
                by_level[level].append(variant)
    finally:
        for connection, _, _ in physical_cache.values():
            connection.close()

    summary = {
        "definition": (
            "unused real SQLite columns whose names have token-Jaccard or "
            "character-sequence similarity >= 0.25 to a gold column; "
            "ranked by name similarity with a same-type tie preference"
        ),
        "source_questions": len(bases),
        "similarity_threshold": MIN_SIMILARITY,
        "levels": {},
        "physical_schema_checks": dict(physical_checks),
    }
    for level, variants in by_level.items():
        out = args.output_dir / f"mini_dev_add_real_synonym_{level}.jsonl"
        out.write_text(
            "".join(
                json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                + "\n"
                for item in variants
            ),
            encoding="utf-8",
        )
        summary["levels"][str(level)] = {
            "generated": len(variants),
            "excluded": len(excluded[level]),
            "excluded_questions": excluded[level],
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
