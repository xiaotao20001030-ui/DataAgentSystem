#!/usr/bin/env python3
"""Produce the data checks requested in the experiment feedback.

This script is deliberately read-only with respect to the source experiment:
it audits the existing perturbation JSONL, model scores and SQLite databases,
then writes an auditable revision bundle to ``--output-dir``.
"""

import argparse
import csv
import json
import os
import random
import re
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path(os.environ.get("BIRD_EXPERIMENT_ROOT", str(PROJECT_ROOT.parent))).expanduser()
DEFAULT_DATA_ROOT = Path(os.environ.get(
    "BIRD_DATA_ROOT", str(DEFAULT_ROOT.parent / "BIRD_MINIDEV_VALIDATION_20261013_server_old" / "data")
)).expanduser()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-dir", type=Path,
                        default=PROJECT_ROOT / "output" / "teacher_feedback" / "construction")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--sample-size", type=int, default=0,
                        help="Optional new draw; the reviewed fixed 30 cases are in sibling synonym20/.")
    parser.add_argument("--seed", type=int, default=20261026)
    return parser.parse_args()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def visible_schema_columns(record):
    return {f"{table['table']}.{column['name']}".lower()
            for table in record["schema"] for column in table["columns"]}


def audit_synonyms(variants, physical_columns):
    rows = [r for r in variants if r["perturbation"]["family"] == "add_synonym"
            and r["perturbation"]["level"] == 20]
    relation_counts = Counter()
    generated = 0
    duplicate_names = 0
    existing_physical = 0
    for row in rows:
        added = row["perturbation"]["added"]
        relation_counts.update(item.get("relation", "missing") for item in added)
        generated += sum(bool(item.get("generated")) for item in added)
        existing_physical += sum(item['id'].lower() in physical_columns[row['db_id']] for item in added)
        names = [item["column"].lower() for item in added]
        duplicate_names += len(names) - len(set(names))
    return {
        "question_count": len(rows),
        "added_columns": sum(len(r["perturbation"]["added"]) for r in rows),
        "relation_counts": dict(sorted(relation_counts.items())),
        "generated_column_count": generated,
        "sqlite_modified_by_generator": False,
        "added_name_entries_matching_existing_physical_columns": existing_physical,
        "added_name_entries_absent_from_physical_columns": sum(len(r['perturbation']['added']) for r in rows)-existing_physical,
        "explanation": (
            "The perturbation generator only adds generated column metadata to the "
            "prompt schema. It neither alters SQLite nor supplies values for those "
            "new columns. Some generated names happen to coincide with real "
            "columns already in SQLite; generated=True is not proof of physical absence."
        ),
        "duplicate_added_names_within_question": duplicate_names,
    }


def score_maps(scores):
    result = {}
    for record in scores:
        if record.get("evaluation_status") == "evaluation_error":
            continue
        result.setdefault(record["family"], {})[record["question_id"]] = bool(record["correct"])
    return result


def relative_drop(base, perturbed):
    if base == 0:
        return None
    return (base - perturbed) / base


def audit_relative_drops(score_dir):
    maps = {path.stem: score_maps(read_jsonl(path)) for path in sorted(score_dir.glob("*.jsonl"))}
    control = maps["api_control"]
    output = {}
    for name, model in maps.items():
        rows = {}
        for family in ("add_random_20", "add_synonym_20"):
            common = sorted(set(model.get("base", {})) & set(model.get(family, {}))
                            & set(control.get("base", {})) & set(control.get(family, {})))
            if not common:
                continue
            def accuracy(data, condition):
                return sum(data[condition][qid] for qid in common) / len(common)
            base, perturbed = accuracy(model, "base"), accuracy(model, family)
            api_base, api_perturbed = accuracy(control, "base"), accuracy(control, family)
            rows[family] = {
                "n": len(common),
                "baseline_accuracy": base,
                "perturbed_accuracy": perturbed,
                "absolute_drop_percentage_points": (base - perturbed) * 100,
                "relative_drop_percent": relative_drop(base, perturbed) * 100 if base else None,
                "api_baseline_accuracy": api_base,
                "api_perturbed_accuracy": api_perturbed,
                "api_absolute_drop_percentage_points": (api_base - api_perturbed) * 100,
                "api_relative_drop_percent": relative_drop(api_base, api_perturbed) * 100 if api_base else None,
            }
            small_relative = rows[family]['relative_drop_percent']
            api_relative = rows[family]['api_relative_drop_percent']
            rows[family]["relative_drop_difference_vs_api_percentage_points"] = (
                small_relative-api_relative if small_relative is not None and api_relative is not None else None)
        output[name] = rows
    return output


def bridge_presence(variants, data_root):
    rows = [r for r in variants if r["perturbation"]["family"] == "missing_bridge_table"]
    present = 0
    details = []
    tables_by_database = {}
    for row in rows:
        removed = row["perturbation"]["removed"]
        tables = [item["id"] for item in removed if item["kind"] == "table"]
        db_path = data_root / row["database_path"]
        if db_path not in tables_by_database:
            # immutable avoids SQLite looking for shared WAL/shm state; the source
            # databases are treated as read-only audit fixtures.
            connection = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro&immutable=1", uri=True)
            try:
                tables_by_database[db_path] = {name.lower() for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
            finally:
                connection.close()
        actual = tables_by_database[db_path]
        found = [table for table in tables if table.lower() in actual]
        present += len(found) == len(tables)
        details.append({"question_id": row["question_id"], "db_id": row["db_id"],
                        "removed_tables": tables, "still_in_sqlite": found})
    return {"variant_count": len(rows), "variants_with_removed_table_still_in_sqlite": present,
            "all_removed_tables_still_accessible": present == len(rows), "details": details}


def sample_api_errors(variants_by_id, api_scores, size, seed):
    failures = [score for score in api_scores if score["family"] == "add_synonym_20"
                and not score["correct"] and not score.get("gold_unscorable")
                and score.get("evaluation_status") != "evaluation_error"
                and not (score.get("error") or "").startswith("GoldUnscorable")]
    rng = random.Random(seed)
    selected = rng.sample(failures, min(size, len(failures)))
    rows = []
    for score in sorted(selected, key=lambda item: str(item["question_id"])):
        variant = variants_by_id[score["variant_id"]]
        rows.append({
            "question_id": score["question_id"], "db_id": score["db_id"],
            "question": variant["question"], "gold_sql": score["gold_sql"],
            "predicted_sql": score.get("predicted_sql", ""), "error": score.get("error", ""),
            "added_columns": "; ".join(item["id"] for item in variant["perturbation"]["added"]),
            "added_relations": "; ".join(item.get("relation", "") for item in variant["perturbation"]["added"]),
        })
    return rows


def main():
    args = parse_args()
    root = args.experiment_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    variants = read_jsonl(root / "perturbations/output/mini_dev_perturbations.jsonl")
    variants_by_id = {record["variant_id"]: record for record in variants}
    api_scores = read_jsonl(root / "model_eval/scores/api_control.jsonl")
    data_root = args.data_root
    if not data_root.is_dir():
        raise SystemExit(f"Cannot locate SQLite data root: {data_root}; use --data-root or BIRD_DATA_ROOT")
    physical_columns = {}
    for db_id in sorted({record['db_id'] for record in variants}):
        path = data_root / 'dev_databases' / db_id / 'sqlite' / f'{db_id}.sqlite'
        connection = sqlite3.connect(f'file:{quote(str(path))}?mode=ro&immutable=1', uri=True)
        try:
            columns = set()
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                columns.update(f'{table}.{column[1]}'.lower() for column in connection.execute(f'PRAGMA table_info({quoted})'))
            physical_columns[db_id] = columns
        finally:
            connection.close()
    summary = {
        "synonym20": audit_synonyms(variants, physical_columns),
        "relative_drops": audit_relative_drops(root / "model_eval/scores"),
        "bridge_table_sqlite_presence": bridge_presence(variants, data_root),
    }
    samples = sample_api_errors(variants_by_id, api_scores, args.sample_size, args.seed)
    (output / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if samples:
        with (output / "api_synonym20_failures_sample.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(samples[0]))
            writer.writeheader()
            writer.writerows(samples)
    lines = ["# Teacher-feedback audit", "", "## Synonym20 construction", "",
             json.dumps(summary["synonym20"], ensure_ascii=False, indent=2), "",
             "## Bridge-table physical availability", "",
             json.dumps({key: value for key, value in summary["bridge_table_sqlite_presence"].items() if key != "details"}, ensure_ascii=False, indent=2),
             "", "## Relative accuracy drops", ""]
    for model, values in summary["relative_drops"].items():
        lines.extend([f"### {model}", "", "| condition | relative drop | API relative drop | difference |", "| --- | ---: | ---: | ---: |"])
        for family, value in values.items():
            small = 'undefined (zero baseline)' if value['relative_drop_percent'] is None else f"{value['relative_drop_percent']:.2f}%"
            api = 'undefined (zero baseline)' if value['api_relative_drop_percent'] is None else f"{value['api_relative_drop_percent']:.2f}%"
            difference = value['relative_drop_difference_vs_api_percentage_points']
            difference = 'undefined' if difference is None else f'{difference:+.2f} pp'
            lines.append(f'| {family} | {small} | {api} | {difference} |')
        lines.append("")
    lines.extend(["## Review sample", "", "The completed fixed 30-case model-assisted SQL review is in sibling `synonym20/`; a human has not signed off its ambiguous semantic judgments.", ""])
    (output / "audit_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
