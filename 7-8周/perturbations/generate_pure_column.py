#!/usr/bin/env python3
"""Generate within-table column perturbations for BIRD Mini-Dev.

The original `add_random_*` conditions add real columns from other tables,
which also adds those tables to the prompt. This script builds a stricter
"pure column" condition: every added column belongs to a table that is
already in the gold schema, so the number of visible tables is unchanged.

It can also build a pure lexical-synonym condition that excludes the
`same_name` distractors used by the original `add_synonym_*` family.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_perturbations as gp


DEFAULT_LEVELS = (20,)
FAMILY_PURE_COLUMN = "add_pure_column"
FAMILY_PURE_SYNONYM = "add_pure_synonym"


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
        default=project_root / "perturbations" / "output" / "pure_column",
    )
    parser.add_argument(
        "--levels",
        default=",".join(str(level) for level in DEFAULT_LEVELS),
        help="Comma-separated column counts, e.g. 5,10,20,50.",
    )
    parser.add_argument("--seed", type=int, default=gp.DEFAULT_SEED)
    parser.add_argument(
        "--include-pure-synonym",
        action="store_true",
        help="Also write an add_pure_synonym family (no same_name columns).",
    )
    return parser.parse_args()


def parse_levels(value):
    levels = tuple(sorted({int(item) for item in value.split(",") if item.strip()}))
    if not levels or any(level <= 0 for level in levels):
        raise SystemExit("--levels must contain positive integers")
    return levels


def table_key(name):
    return name.lower()


def column_ids(columns):
    return {column["id"].lower() for column in columns}


def within_table_pool(schema_index, base_columns, base_tables):
    base_ids = column_ids(base_columns)
    base_lookup = {table_key(table) for table in base_tables}
    return [
        dict(column, generated=False, relation="within_table_random")
        for column in schema_index["columns"]
        if table_key(column["table"]) in base_lookup
        and column["id"].lower() not in base_ids
    ]


def synthetic_filler(base_columns, base_tables, amount, relation):
    existing = column_ids(base_columns)
    extras = []
    counter = 1
    while len(extras) < amount:
        table = base_tables[(counter - 1) % len(base_tables)]
        name = f"auxiliary_field_{counter:02d}"
        column_id = gp.as_column_id(table, name)
        counter += 1
        if column_id.lower() in existing:
            continue
        extras.append(
            {
                "id": column_id,
                "table": table,
                "column": name,
                "type": "TEXT",
                "primary_key": False,
                "generated": True,
                "relation": relation,
            }
        )
        existing.add(column_id.lower())
    return extras


def build_pure_synonym_extras(base_columns, base_tables, amount, rng):
    extras = []
    existing = column_ids(base_columns)
    table_cycle = list(base_tables)
    table_index = 0

    def add(seed, name, relation):
        nonlocal table_index
        normalized = name.strip().lower()
        if not normalized or normalized == seed["column"].lower():
            return False
        for _ in range(len(table_cycle)):
            table = table_cycle[table_index % len(table_cycle)]
            table_index += 1
            column_id = gp.as_column_id(table, normalized)
            if column_id.lower() in existing:
                continue
            extras.append(
                {
                    "id": column_id,
                    "table": table,
                    "column": normalized,
                    "type": seed.get("type", "TEXT"),
                    "primary_key": False,
                    "generated": True,
                    "relation": relation,
                    "seed_column": seed["id"],
                }
            )
            existing.add(column_id.lower())
            return True
        return False

    seeds = list(base_columns)
    rng.shuffle(seeds)
    for seed in seeds:
        for name in gp.synonym_names(seed["column"]):
            add(seed, name, "synonym")
            if len(extras) >= amount:
                return extras[:amount]

    seed_index = 0
    counter = 1
    while len(extras) < amount:
        seed = seeds[seed_index % len(seeds)]
        add(seed, f"related_{seed['column']}_{counter:02d}", "synonym")
        seed_index += 1
        counter += 1
        if counter > amount * 20:
            raise RuntimeError("Unable to build enough pure-synonym columns")
    return extras[:amount]


def build_variants(
    questions,
    schema_by_db,
    levels,
    seed,
    include_pure_synonym,
):
    records = []
    for question_index, item in enumerate(questions):
        schema_index = schema_by_db[item["db_id"]]
        structure = gp.analyze_question(item, None, schema_index)
        base_columns = structure["columns"]
        base_tables = structure["tables"]
        if not base_tables:
            raise RuntimeError(f"No gold tables for {item['question_id']}")

        column_rng = gp.stable_rng(seed, item["question_id"], FAMILY_PURE_COLUMN)
        column_pool = within_table_pool(schema_index, base_columns, base_tables)
        column_rng.shuffle(column_pool)
        max_level = max(levels)
        column_extras = column_pool[:max_level]
        if len(column_extras) < max_level:
            column_extras.extend(
                synthetic_filler(
                    base_columns + column_extras,
                    base_tables,
                    max_level - len(column_extras),
                    relation="within_table_filler",
                )
            )

        synonym_rng = gp.stable_rng(seed, item["question_id"], FAMILY_PURE_SYNONYM)
        synonym_extras = (
            build_pure_synonym_extras(
                base_columns,
                base_tables,
                max_level,
                synonym_rng,
            )
            if include_pure_synonym
            else []
        )

        records.append(
            gp.variant_record(
                item=item,
                question_index=question_index,
                family="base",
                level=None,
                added=[],
                removed=[],
                schema_columns=base_columns,
                structure=structure,
            )
        )

        for level in levels:
            added = column_extras[:level]
            records.append(
                gp.variant_record(
                    item=item,
                    question_index=question_index,
                    family=FAMILY_PURE_COLUMN,
                    level=level,
                    added=added,
                    removed=[],
                    schema_columns=base_columns + added,
                    structure=structure,
                )
            )
            if include_pure_synonym:
                added = synonym_extras[:level]
                records.append(
                    gp.variant_record(
                        item=item,
                        question_index=question_index,
                        family=FAMILY_PURE_SYNONYM,
                        level=level,
                        added=added,
                        removed=[],
                        schema_columns=base_columns + added,
                        structure=structure,
                    )
                )
    return records


def validate(records, levels, include_pure_synonym):
    expected_families = [FAMILY_PURE_COLUMN]
    if include_pure_synonym:
        expected_families.append(FAMILY_PURE_SYNONYM)

    by_question = Counter()
    for record in records:
        by_question[(record["question_id"], record["perturbation"]["family"])] += 1
    for question_id in {record["question_id"] for record in records}:
        if by_question[(question_id, "base")] != 1:
            raise AssertionError(f"{question_id} has incomplete base variants")
        for family in expected_families:
            if by_question[(question_id, family)] != len(levels):
                raise AssertionError(
                    f"{question_id} has incomplete {family} variants"
                )

    for record in records:
        perturbation = record["perturbation"]
        if perturbation["family"] == "base":
            continue
        base_tables = {table_key(table) for table in record["gold_tables"]}
        added_tables = {
            table_key(column["table"]) for column in perturbation["added"]
        }
        if not added_tables <= base_tables:
            raise AssertionError(
                f"{record['variant_id']} added a table outside the gold schema"
            )
        if len(perturbation["added"]) != perturbation["level"]:
            raise AssertionError(
                f"{record['variant_id']} has the wrong number of added columns"
            )
        if perturbation["family"] == FAMILY_PURE_SYNONYM:
            if any(
                column["relation"] == "same_name"
                for column in perturbation["added"]
            ):
                raise AssertionError(
                    f"{record['variant_id']} contains a same_name column"
                )

    variant_ids = [record["variant_id"] for record in records]
    if len(variant_ids) != len(set(variant_ids)):
        raise AssertionError("Duplicate variant IDs")


def main():
    args = parse_args()
    levels = parse_levels(args.levels)
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
    records = build_variants(
        questions=questions,
        schema_by_db=schema_by_db,
        levels=levels,
        seed=args.seed,
        include_pure_synonym=args.include_pure_synonym,
    )
    validate(records, levels, args.include_pure_synonym)

    variants_path = output_dir / "mini_dev_pure_column.jsonl"
    with variants_path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            )
            output.write("\n")

    added_breakdown = Counter()
    for record in records:
        perturbation = record["perturbation"]
        for column in perturbation["added"]:
            added_breakdown[
                (
                    perturbation["family"],
                    perturbation["level"],
                    column.get("relation", "unknown"),
                    bool(column.get("generated")),
                )
            ] += 1

    summary = {
        "dataset": "BIRD Mini-Dev SQLite",
        "question_count": len(questions),
        "levels": list(levels),
        "seed": args.seed,
        "families": sorted(
            {
                record["perturbation"]["family"]
                for record in records
            }
        ),
        "variant_count": len(records),
        "base_variant_count": sum(
            record["perturbation"]["family"] == "base" for record in records
        ),
        "table_scope": "gold tables only; no new tables",
        "added_column_breakdown": {
            f"{family}_{level}:{relation}:generated={str(generated).lower()}": count
            for (family, level, relation, generated), count in sorted(
                added_breakdown.items()
            )
        },
        "sha256": hashlib.sha256(variants_path.read_bytes()).hexdigest(),
        "output": variants_path.name,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Pure-column perturbation validation",
        "",
        f"- questions: {len(questions)}",
        f"- levels: {', '.join(str(level) for level in levels)}",
        f"- families: {', '.join(summary['families'])}",
        f"- variants: {len(records)}",
        "- all added columns belong to gold tables: yes",
        f"- sha256: `{summary['sha256']}`",
        "",
        "## Added columns",
        "",
        "| family | level | relation | generated | count |",
        "| --- | ---: | --- | --- | ---: |",
    ]
    for (family, level, relation, generated), count in sorted(
        added_breakdown.items()
    ):
        lines.append(
            f"| {family} | {level} | {relation} | "
            f"{str(generated).lower()} | {count} |"
        )
    (output_dir / "validation_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
