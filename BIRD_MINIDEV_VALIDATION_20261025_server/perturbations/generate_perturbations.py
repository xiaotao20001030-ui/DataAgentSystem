#!/usr/bin/env python3
"""Generate controlled schema perturbations for BIRD Mini-Dev.

The baseline schema contains only tables and columns referenced by the gold
SQL. Variants add irrelevant columns or remove bridge/join-key columns.
"""

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from sqlglot import exp, parse_one
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope


ADD_LEVELS = (5, 10, 20, 50)
DEFAULT_SEED = 20261019
MAX_EXTRA_COLUMNS = max(ADD_LEVELS)

TOKEN_SYNONYMS = {
    "account": ("client", "ledger"),
    "amount": ("value", "total"),
    "budget": ("allocation", "fund"),
    "category": ("class", "group"),
    "code": ("identifier", "key"),
    "count": ("number", "frequency"),
    "customer": ("client", "account_holder"),
    "date": ("day", "timestamp"),
    "day": ("date", "calendar_day"),
    "event": ("activity", "occasion"),
    "expense": ("cost", "spending"),
    "id": ("identifier", "key", "ref"),
    "identifier": ("id", "key"),
    "member": ("participant", "user"),
    "name": ("title", "label"),
    "number": ("count", "num"),
    "product": ("item", "goods"),
    "score": ("result", "rating"),
    "station": ("outlet", "site"),
    "status": ("state", "condition"),
    "time": ("timestamp", "moment"),
    "total": ("sum", "aggregate"),
    "type": ("category", "kind"),
    "value": ("amount", "measure"),
    "year": ("calendar_year", "yr"),
}


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=project_root / "mini_dev_data",
        help="Directory containing mini_dev_sqlite.json and dev_tables.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "perturbations" / "output",
        help="Directory for JSONL variants and reports.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


def stable_rng(seed, question_id, family):
    digest = hashlib.sha256(f"{seed}:{question_id}:{family}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def as_column_id(table, column):
    return f"{table}.{column}"


def build_schema_index(meta):
    table_names = meta["table_names_original"]
    table_lookup = {name.lower(): name for name in table_names}
    primary_keys = set()
    for primary_key in meta["primary_keys"]:
        if isinstance(primary_key, (list, tuple)):
            primary_keys.update(primary_key)
        else:
            primary_keys.add(primary_key)
    columns = []
    by_index = {}
    by_id = {}

    for index, (table_index, column_name) in enumerate(meta["column_names_original"]):
        if table_index < 0:
            continue
        table_name = table_names[table_index]
        column = {
            "id": as_column_id(table_name, column_name),
            "table": table_name,
            "column": column_name,
            "type": meta["column_types"][index] or "TEXT",
            "primary_key": index in primary_keys,
        }
        columns.append(column)
        by_index[index] = column
        by_id[column["id"].lower()] = column

    fk_pairs = []
    for left_index, right_index in meta["foreign_keys"]:
        left = by_index.get(left_index)
        right = by_index.get(right_index)
        if left and right and left["table"].lower() != right["table"].lower():
            fk_pairs.append((left, right))

    return {
        "table_names": table_names,
        "table_lookup": table_lookup,
        "columns": columns,
        "by_index": by_index,
        "by_id": by_id,
        "fk_pairs": fk_pairs,
    }


def schema_for_qualify(schema_index):
    schema = {table: {} for table in schema_index["table_names"]}
    for column in schema_index["columns"]:
        schema[column["table"]][column["column"]] = column["type"]
    return schema


def resolve_column(column, scope, schema_index):
    if not isinstance(column, exp.Column):
        return None
    table_token = (column.table or "").lower()
    column_name = column.name.lower()
    source = scope.sources.get(table_token)

    if isinstance(source, exp.Table):
        table_name = schema_index["table_lookup"].get(source.name.lower())
        if table_name:
            candidate = schema_index["by_id"].get(as_column_id(table_name, column_name).lower())
            if candidate:
                return candidate

    if not table_token:
        matches = []
        for source_item in scope.sources.values():
            if isinstance(source_item, exp.Table):
                table_name = schema_index["table_lookup"].get(source_item.name.lower())
                if table_name:
                    candidate = schema_index["by_id"].get(
                        as_column_id(table_name, column_name).lower()
                    )
                    if candidate:
                        matches.append(candidate)
        if len(matches) == 1:
            return matches[0]
    return None


def analyze_question(item, meta, schema_index):
    qualified = qualify(
        parse_one(item["SQL"], read="sqlite"),
        schema=schema_for_qualify(schema_index),
        dialect="sqlite",
    )
    scopes = {scope.expression: scope for scope in traverse_scope(qualified)}

    tables = {}
    columns = {}
    for table in qualified.find_all(exp.Table):
        table_name = schema_index["table_lookup"].get(table.name.lower())
        if table_name:
            tables[table_name.lower()] = table_name

    for scope in scopes.values():
        for column_node in scope.columns:
            column = resolve_column(column_node, scope, schema_index)
            if column:
                columns[column["id"].lower()] = column
                tables[column["table"].lower()] = column["table"]

    edges = {}
    for equality in qualified.find_all(exp.EQ):
        select = equality.find_ancestor(exp.Select)
        scope = scopes.get(select)
        if not scope:
            continue
        left = resolve_column(equality.left, scope, schema_index)
        right = resolve_column(equality.right, scope, schema_index)
        if not left or not right or left["table"].lower() == right["table"].lower():
            continue
        endpoints = tuple(sorted((left["id"], right["id"]), key=str.lower))
        normalized_edge_key = tuple(endpoint.lower() for endpoint in endpoints)
        edges[normalized_edge_key] = {
            "columns": list(endpoints),
            "tables": sorted(
                [left["table"], right["table"]], key=lambda value: value.lower()
            ),
        }
        columns[left["id"].lower()] = left
        columns[right["id"].lower()] = right

    gold_tables = sorted(tables.values(), key=lambda value: value.lower())
    gold_columns = sorted(columns.values(), key=lambda col: col["id"].lower())
    if not gold_columns:
        for table_name in gold_tables:
            for column in schema_index["columns"]:
                if column["table"].lower() == table_name.lower():
                    gold_columns.append(column)
        gold_columns.sort(key=lambda col: col["id"].lower())

    edge_list = sorted(edges.values(), key=lambda edge: tuple(x.lower() for x in edge["columns"]))
    fk_index = index_foreign_keys(schema_index)
    for edge in edge_list:
        edge["declared_foreign_keys"] = fk_index.get(edge_key(edge), [])

    bridges = find_bridge_tables(gold_tables, edge_list)
    fk_variants = build_fk_variants(gold_tables, edge_list, bridges, fk_index)
    return {
        "tables": gold_tables,
        "columns": gold_columns,
        "join_edges": edge_list,
        "bridge_tables": bridges,
        "fk_variants": fk_variants,
    }


def edge_key(edge):
    return tuple(column.lower() for column in edge["columns"])


def index_foreign_keys(schema_index):
    result = defaultdict(list)
    for fk_column, parent_column in schema_index["fk_pairs"]:
        key = tuple(
            sorted(
                [fk_column["id"].lower(), parent_column["id"].lower()],
            )
        )
        result[key].append(
            {
                "fk_column": fk_column["id"],
                "referenced_column": parent_column["id"],
            }
        )
    return result


def component_count(vertices, edges):
    adjacency = {vertex.lower(): set() for vertex in vertices}
    for edge in edges:
        left, right = edge["tables"]
        adjacency.setdefault(left.lower(), set()).add(right.lower())
        adjacency.setdefault(right.lower(), set()).add(left.lower())

    seen = set()
    count = 0
    for vertex in adjacency:
        if vertex in seen:
            continue
        count += 1
        stack = [vertex]
        seen.add(vertex)
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
    return count


def find_bridge_tables(tables, edges):
    if len(tables) < 3 or component_count(tables, edges) != 1:
        return []
    bridges = []
    for table in tables:
        remaining_tables = [item for item in tables if item != table]
        remaining_edges = [
            edge
            for edge in edges
            if table.lower() not in {name.lower() for name in edge["tables"]}
        ]
        if component_count(remaining_tables, remaining_edges) > 1:
            bridges.append(table)
    return sorted(bridges, key=lambda value: value.lower())


def build_fk_variants(tables, edges, bridges, fk_index):
    if len(tables) < 2 or component_count(tables, edges) != 1:
        return []

    variants = []
    bridge_lookup = {table.lower() for table in bridges}
    for edge in edges:
        remaining = [candidate for candidate in edges if candidate is not edge]
        if component_count(tables, remaining) == 1:
            continue

        declared = fk_index.get(edge_key(edge), [])
        selected_id = None
        declared_column = False
        if declared:
            candidates = [entry["fk_column"] for entry in declared]
            selected_id = choose_bridge_endpoint(candidates, bridge_lookup)
            declared_column = True
        if not selected_id:
            selected_id = choose_bridge_endpoint(edge["columns"], bridge_lookup)

        variants.append(
            {
                "removed_column": selected_id,
                "join_columns": edge["columns"],
                "declared_foreign_key": declared_column,
                "foreign_key_matches": declared,
            }
        )
    return variants


def choose_bridge_endpoint(column_ids, bridge_lookup):
    bridge_matches = [
        column_id
        for column_id in column_ids
        if column_id.split(".", 1)[0].lower() in bridge_lookup
    ]
    if bridge_matches:
        return sorted(bridge_matches, key=str.lower)[0]
    if column_ids:
        return sorted(column_ids, key=str.lower)[0]
    return None


def schema_groups(columns):
    grouped = defaultdict(list)
    order = []
    for column in columns:
        if column["table"] not in grouped:
            order.append(column["table"])
        grouped[column["table"]].append(
            {
                "name": column["column"],
                "type": column.get("type", "TEXT"),
                "primary_key": bool(column.get("primary_key", False)),
            }
        )
    return [
        {"table": table_name, "columns": grouped[table_name]}
        for table_name in order
    ]


def make_record(
    item,
    question_index,
    perturbation,
    gold_tables,
    gold_columns,
    join_edges,
    bridge_tables,
    schema_columns,
):
    schema_ids = [column["id"] for column in schema_columns]
    return {
        "variant_id": perturbation["variant_id"],
        "question_index": question_index,
        "question_id": item["question_id"],
        "db_id": item["db_id"],
        "question": item["question"],
        "evidence": item["evidence"],
        "gold_sql": item["SQL"],
        "difficulty": item["difficulty"],
        "database_path": (
            f"dev_databases/{item['db_id']}/sqlite/{item['db_id']}.sqlite"
        ),
        "perturbation": perturbation,
        "gold_tables": gold_tables,
        "gold_columns": [column["id"] for column in gold_columns],
        "schema_columns": schema_ids,
        "schema": schema_groups(schema_columns),
        "join_edges": join_edges,
        "bridge_tables": bridge_tables,
    }


def split_identifier(identifier):
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    tokens = [token.lower() for token in re.split(r"[^A-Za-z0-9]+", expanded) if token]
    if len(tokens) == 1 and tokens[0].endswith("id") and len(tokens[0]) > 3:
        tokens = [tokens[0][:-2], "id"]
    return tokens


def synonym_names(column_name):
    tokens = split_identifier(column_name) or [column_name.lower()]
    base = "_".join(tokens)
    substituted = []
    for token in tokens:
        options = TOKEN_SYNONYMS.get(token)
        substituted.append(options[0] if options else token)
    alternate = "_".join(substituted)

    suffix_options = (
        ("ref", "key", "identifier", "value")
        if "id" in tokens or any(token.endswith("id") for token in tokens)
        else ("label", "value", "detail", "record")
    )
    names = [
        alternate,
        *[f"{alternate}_{suffix}" for suffix in suffix_options],
        f"related_{base}",
        f"{base}_related",
        f"{base}_alt",
    ]
    expanded = []
    for name in names:
        normalized = re.sub(r"_+", "_", name).strip("_")
        if normalized and normalized not in expanded:
            expanded.append(normalized)
    return expanded


def build_random_extras(schema_index, base_columns, tables, rng, amount):
    base_ids = {column["id"].lower() for column in base_columns}
    pool = [
        dict(column, generated=False, relation="random")
        for column in schema_index["columns"]
        if column["id"].lower() not in base_ids
    ]
    rng.shuffle(pool)
    extras = pool[:amount]

    existing = {column["id"].lower() for column in base_columns}
    existing.update(column["id"].lower() for column in extras)
    anchor_table = tables[0]
    counter = 1
    while len(extras) < amount:
        column_name = f"auxiliary_field_{counter:02d}"
        column_id = as_column_id(anchor_table, column_name)
        counter += 1
        if column_id.lower() in existing:
            continue
        extras.append(
            {
                "id": column_id,
                "table": anchor_table,
                "column": column_name,
                "type": "TEXT",
                "primary_key": False,
                "generated": True,
                "relation": "random",
            }
        )
        existing.add(column_id.lower())
    return extras


def build_synonym_extras(base_columns, tables, amount):
    extras = []
    existing = {column["id"].lower() for column in base_columns}
    table_cycle = list(tables)
    table_cycle_index = 0

    def add(seed, name, relation):
        nonlocal table_cycle_index
        attempts = 0
        while attempts < len(table_cycle):
            table = table_cycle[table_cycle_index % len(table_cycle)]
            table_cycle_index += 1
            column_id = as_column_id(table, name)
            if column_id.lower() not in existing:
                extra = {
                    "id": column_id,
                    "table": table,
                    "column": name,
                    "type": seed.get("type", "TEXT"),
                    "primary_key": False,
                    "generated": True,
                    "relation": relation,
                    "seed_column": seed["id"],
                }
                extras.append(extra)
                existing.add(column_id.lower())
                return True
            attempts += 1
        return False

    for seed in base_columns:
        for other_table in sorted(tables, key=lambda value: value.lower()):
            if other_table.lower() != seed["table"].lower():
                add(seed, seed["column"], "same_name")
                if len(extras) >= amount:
                    return extras[:amount]

    for seed in base_columns:
        for name in synonym_names(seed["column"]):
            add(seed, name, "synonym")
            if len(extras) >= amount:
                return extras[:amount]

    seed_index = 0
    counter = 1
    while len(extras) < amount:
        seed = base_columns[seed_index % len(base_columns)]
        add(seed, f"related_{seed['column']}_{counter:02d}", "synonym")
        seed_index += 1
        counter += 1
    return extras


def variant_record(
    item,
    question_index,
    family,
    level,
    added,
    removed,
    schema_columns,
    structure,
    extra_metadata=None,
    id_detail=None,
):
    suffix = family
    if level is not None:
        suffix += f"_{level}"
    if removed:
        suffix += "__" + "__".join(
            entry["id"].replace(".", "_") for entry in removed
        )
    if id_detail:
        suffix += "__" + id_detail
    perturbation = {
        "variant_id": f"q{question_index:04d}__{suffix}",
        "family": family,
        "level": level,
        "added": added,
        "removed": removed,
    }
    if extra_metadata:
        perturbation.update(extra_metadata)
    return make_record(
        item=item,
        question_index=question_index,
        perturbation=perturbation,
        gold_tables=structure["tables"],
        gold_columns=structure["columns"],
        join_edges=structure["join_edges"],
        bridge_tables=structure["bridge_tables"],
        schema_columns=schema_columns,
    )


def generate(questions, schema_by_db, seed):
    records = []
    structures = []
    parse_failures = []

    for question_index, item in enumerate(questions):
        try:
            structure = analyze_question(item, None, schema_by_db[item["db_id"]])
        except Exception as error:
            parse_failures.append(
                {
                    "question_id": item["question_id"],
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            raise

        schema_index = schema_by_db[item["db_id"]]
        base_columns = structure["columns"]
        base_ids = {column["id"].lower() for column in base_columns}

        records.append(
            variant_record(
                item,
                question_index,
                "base",
                None,
                [],
                [],
                base_columns,
                structure,
            )
        )
        structures.append(
            {
                "question_index": question_index,
                "question_id": item["question_id"],
                "db_id": item["db_id"],
                "question_type": "single" if len(structure["tables"]) == 1 else "multi",
                "gold_tables": structure["tables"],
                "gold_columns": [column["id"] for column in base_columns],
                "join_edges": structure["join_edges"],
                "join_graph_connected": (
                    len(structure["tables"]) > 1
                    and component_count(
                        structure["tables"],
                        structure["join_edges"],
                    ) == 1
                ),
                "bridge_tables": structure["bridge_tables"],
                "fk_variant_count": len(structure["fk_variants"]),
            }
        )

        random_rng = stable_rng(seed, item["question_id"], "add_random")
        random_pool = build_random_extras(
            schema_index,
            base_columns,
            structure["tables"],
            random_rng,
            MAX_EXTRA_COLUMNS,
        )
        synonym_pool = build_synonym_extras(
            base_columns,
            structure["tables"],
            MAX_EXTRA_COLUMNS,
        )

        for level in ADD_LEVELS:
            added = random_pool[:level]
            records.append(
                variant_record(
                    item,
                    question_index,
                    "add_random",
                    level,
                    added,
                    [],
                    base_columns + added,
                    structure,
                )
            )
            added = synonym_pool[:level]
            records.append(
                variant_record(
                    item,
                    question_index,
                    "add_synonym",
                    level,
                    added,
                    [],
                    base_columns + added,
                    structure,
                )
            )

        for bridge_table in structure["bridge_tables"]:
            removed_columns = [
                column for column in base_columns
                if column["table"].lower() == bridge_table.lower()
            ]
            kept_columns = [
                column for column in base_columns
                if column["table"].lower() != bridge_table.lower()
            ]
            records.append(
                variant_record(
                    item,
                    question_index,
                    "missing_bridge_table",
                    None,
                    [],
                    [
                        {
                            "kind": "table",
                            "id": bridge_table,
                            "columns": [column["id"] for column in removed_columns],
                        }
                    ],
                    kept_columns,
                    structure,
                    {"candidate_removed": True},
                )
            )

        for fk_variant in structure["fk_variants"]:
            removed_id = fk_variant["removed_column"]
            removed_column = schema_index["by_id"].get(removed_id.lower())
            if not removed_column:
                continue
            kept_columns = [
                column for column in base_columns
                if column["id"].lower() != removed_id.lower()
            ]
            other_endpoint = next(
                (
                    column_id
                    for column_id in fk_variant["join_columns"]
                    if column_id.lower() != removed_id.lower()
                ),
                "unknown",
            )
            records.append(
                variant_record(
                    item,
                    question_index,
                    "missing_fk_column",
                    None,
                    [],
                    [
                        {
                            "kind": "column",
                            "id": removed_id,
                            "join_columns": fk_variant["join_columns"],
                        }
                    ],
                    kept_columns,
                    structure,
                    {
                        "declared_foreign_key": fk_variant["declared_foreign_key"],
                        "foreign_key_matches": fk_variant["foreign_key_matches"],
                    },
                    id_detail="edge_to_" + other_endpoint.replace(".", "_"),
                )
            )

    return records, structures, parse_failures


def validate_variant(record):
    base = set(record["gold_columns"])
    schema = set(record["schema_columns"])
    perturbation = record["perturbation"]

    if not base.issubset(schema) and perturbation["family"] not in {
        "missing_bridge_table",
        "missing_fk_column",
    }:
        raise AssertionError(f"Gold columns missing from {record['variant_id']}")

    if perturbation["family"].startswith("add_"):
        expected = len(base) + perturbation["level"]
        if len(schema) != expected:
            raise AssertionError(
                f"{record['variant_id']}: expected {expected} columns, got {len(schema)}"
            )

    if perturbation["family"] == "missing_bridge_table":
        removed_table = perturbation["removed"][0]["id"].lower()
        if any(
            column_id.split(".", 1)[0].lower() == removed_table
            for column_id in schema
        ):
            raise AssertionError(f"Bridge table still present in {record['variant_id']}")

    if perturbation["family"] == "missing_fk_column":
        removed_column = perturbation["removed"][0]["id"]
        if removed_column in schema:
            raise AssertionError(f"FK column still present in {record['variant_id']}")
        if len(record["gold_tables"]) < 2:
            raise AssertionError(f"FK perturbation on single-table question {record['variant_id']}")


def validate_dataset_contract(records, structures):
    variant_ids = [record["variant_id"] for record in records]
    if len(variant_ids) != len(set(variant_ids)):
        duplicate_ids = [
            variant_id
            for variant_id, count in Counter(variant_ids).items()
            if count > 1
        ]
        raise AssertionError(f"Duplicate variant IDs: {duplicate_ids}")

    families_by_question = defaultdict(Counter)
    for record in records:
        families_by_question[record["question_id"]][record["perturbation"]["family"]] += 1
    if len(families_by_question) != 500:
        raise AssertionError(f"Expected 500 questions, found {len(families_by_question)}")
    for question_id, families in families_by_question.items():
        if families["base"] != 1:
            raise AssertionError(f"Question {question_id} does not have exactly one baseline")
        if families["add_random"] != len(ADD_LEVELS):
            raise AssertionError(f"Question {question_id} has incomplete random variants")
        if families["add_synonym"] != len(ADD_LEVELS):
            raise AssertionError(f"Question {question_id} has incomplete synonym variants")

    if len(structures) != 500:
        raise AssertionError(f"Expected 500 structures, found {len(structures)}")


def validate_baseline_qualification(records):
    bases = [
        record
        for record in records
        if record["perturbation"]["family"] == "base"
    ]
    for record in bases:
        schema = {
            table["table"]: {
                column["name"]: column["type"]
                for column in table["columns"]
            }
            for table in record["schema"]
        }
        qualify(
            parse_one(record["gold_sql"], read="sqlite"),
            schema=schema,
            dialect="sqlite",
        )
    return len(bases)


def main():
    args = parse_args()
    data_root = args.data_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    questions = json.loads((data_root / "mini_dev_sqlite.json").read_text(encoding="utf-8"))
    metadata = json.loads((data_root / "dev_tables.json").read_text(encoding="utf-8"))
    questions = questions[:500]
    if len(questions) != 500:
        raise SystemExit(f"Expected first 500 questions, found {len(questions)}")

    schema_by_db = {
        item["db_id"]: build_schema_index(item)
        for item in metadata
    }
    records, structures, parse_failures = generate(questions, schema_by_db, args.seed)
    for record in records:
        validate_variant(record)
    validate_dataset_contract(records, structures)
    qualified_baselines = validate_baseline_qualification(records)

    variants_path = output_dir / "mini_dev_perturbations.jsonl"
    with variants_path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            output.write("\n")

    structures_path = output_dir / "question_structures.jsonl"
    with structures_path.open("w", encoding="utf-8") as output:
        for structure in structures:
            output.write(json.dumps(structure, ensure_ascii=False, separators=(",", ":")))
            output.write("\n")

    family_counts = Counter(record["perturbation"]["family"] for record in records)
    level_counts = Counter(
        (record["perturbation"]["family"], record["perturbation"]["level"])
        for record in records
        if record["perturbation"]["level"] is not None
    )
    question_types = Counter(structure["question_type"] for structure in structures)
    bridge_questions = sum(bool(structure["bridge_tables"]) for structure in structures)
    fk_questions = sum(structure["fk_variant_count"] > 0 for structure in structures)
    connected_multi_questions = sum(
        structure["question_type"] == "multi" and structure["join_graph_connected"]
        for structure in structures
    )
    declared_fk_variants = sum(
        bool(record["perturbation"].get("declared_foreign_key"))
        for record in records
        if record["perturbation"]["family"] == "missing_fk_column"
    )
    added_column_breakdown = Counter()
    for record in records:
        perturbation = record["perturbation"]
        if not perturbation["family"].startswith("add_"):
            continue
        for column in perturbation["added"]:
            added_column_breakdown[
                (
                    perturbation["family"],
                    perturbation["level"],
                    column.get("relation", "unknown"),
                    bool(column.get("generated")),
                )
            ] += 1

    variants_sha256 = hashlib.sha256(variants_path.read_bytes()).hexdigest()
    summary = {
        "dataset": "BIRD Mini-Dev SQLite",
        "question_count": len(questions),
        "database_count": len({item["db_id"] for item in questions}),
        "seed": args.seed,
        "question_types": dict(question_types),
        "connected_multi_table_questions": connected_multi_questions,
        "difficulty_counts": dict(
            sorted(Counter(item["difficulty"] for item in questions).items())
        ),
        "parse_failures": parse_failures,
        "baseline_schema_qualification_passed": qualified_baselines,
        "eligible_questions": {
            "bridge_table": bridge_questions,
            "foreign_key_column": fk_questions,
        },
        "variant_counts": {
            "by_family": dict(sorted(family_counts.items())),
            "by_family_and_level": {
                f"{family}_{level}": count
                for (family, level), count in sorted(level_counts.items())
            },
            "total": len(records),
            "declared_foreign_key_column_variants": declared_fk_variants,
            "fallback_join_key_column_variants": (
                family_counts["missing_fk_column"] - declared_fk_variants
            ),
        },
        "added_column_breakdown": {
            f"{family}_{level}:{relation}:generated={str(generated).lower()}": count
            for (family, level, relation, generated), count
            in sorted(added_column_breakdown.items())
        },
        "outputs": {
            "variants": variants_path.name,
            "variants_sha256": variants_sha256,
            "question_structures": structures_path.name,
            "validation_report": "validation_report.md",
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report_lines = [
        "# BIRD Mini-Dev Schema 扰动检查报告",
        "",
        f"- 题目数：{len(questions)}",
        f"- 数据库数：{summary['database_count']}",
        f"- 单表题：{question_types['single']}",
        f"- 多表题：{question_types['multi']}",
        f"- 可生成桥接表扰动：{bridge_questions} 题",
        f"- 可生成外键/连接键扰动：{fk_questions} 题",
        f"- 生成变体：{len(records)} 条",
        f"- 变体 ID 唯一：是",
        f"- 基线 schema qualification：{qualified_baselines}/{len(questions)}",
        f"- 固定随机种子：{args.seed}",
        f"- JSONL SHA-256：`{variants_sha256}`",
        "",
        "## 变体数量",
        "",
        "| family | 数量 |",
        "| --- | ---: |",
    ]
    for family, count in sorted(family_counts.items()):
        report_lines.append(f"| {family} | {count} |")
    report_lines.extend(
        [
            "",
            "## 缺失成分覆盖",
            "",
            f"- 414 道多表题中，{connected_multi_questions} 道具有完整连接图。",
            f"- {bridge_questions} 道题的连接图存在桥接表。",
            f"- {fk_questions} 道题存在关键外键/连接键列。",
            f"- `missing_fk_column` 共 {family_counts['missing_fk_column']} 条，"
            f"其中 {declared_fk_variants} 条来自显式外键定义，"
            f"{family_counts['missing_fk_column'] - declared_fk_variants} 条为 gold join 回退。",
            "",
            "## 输出文件",
            "",
            f"- `{variants_path.name}`",
            f"- `{structures_path.name}`",
            "- `summary.json`",
            "- `validation_report.md`",
        ]
    )
    (output_dir / "validation_report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
