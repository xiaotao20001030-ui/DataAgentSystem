#!/usr/bin/env python3
"""Audit missing-schema compliance with SQLite's authorizer.

The original missing-schema report used a compliance check that may count
every column read by `SELECT *` as a removed-column read. This script makes
that behavior explicit and reports strict compliance, non-star compliance,
removed-item usage, and evidence leakage separately.
"""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scores-dir",
        type=Path,
        default=project_root / "mini_dev_data" / "model_eval" / "scores",
    )
    parser.add_argument(
        "--variants",
        type=Path,
        default=project_root / "perturbations" / "output"
        / "mini_dev_perturbations.jsonl",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=project_root / "mini_dev_data",
    )
    parser.add_argument(
        "--base-scores-dir",
        type=Path,
        default=None,
        help="Optional flat directory with <model>.jsonl base scores.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "analysis" / "missing_compliance",
    )
    return parser.parse_args()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def reads_for_sql(db_path, sql):
    connection = sqlite3.connect(
        f"file:{quote(str(db_path))}?mode=ro",
        uri=True,
    )
    reads = set()
    rejected = []

    def authorizer(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_READ:
            reads.add(
                (
                    (arg1 or "").lower(),
                    (arg2 or "").lower(),
                )
            )
        if action in (sqlite3.SQLITE_DENY, sqlite3.SQLITE_IGNORE):
            rejected.append((action, arg1, arg2))
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorizer)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("EXPLAIN " + sql)
    except Exception as error:
        return None, str(error)
    finally:
        connection.close()
    return reads, None


def name_in_text(name, text):
    if not name:
        return False
    return bool(
        re.search(
            r"(?<![a-z0-9_])" + re.escape(name.lower()) + r"(?![a-z0-9_])",
            (text or "").lower(),
        )
    )


def select_star(sql):
    return bool(re.search(r"\bselect\s+(?:distinct\s+)?\*", sql, re.I))


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    variants = {
        record["variant_id"]: record for record in read_jsonl(args.variants)
    }

    external_base = {}
    if args.base_scores_dir is not None:
        for score_path in sorted(args.base_scores_dir.glob("*.jsonl")):
            records = read_jsonl(score_path)
            if not records:
                continue
            model_key = records[0].get("model_key", score_path.stem)
            external_base[model_key] = {
                record["variant_id"].split("__", 1)[0]: bool(
                    record["correct"]
                )
                for record in records
                if record["family"] == "base"
            }

    report = {}
    for score_path in sorted(args.scores_dir.glob("*.jsonl")):
        records = read_jsonl(score_path)
        if not records:
            continue
        model_key = records[0].get("model_key", score_path.stem)
        base_correct = {
            record["variant_id"].split("__", 1)[0]: bool(record["correct"])
            for record in records
            if record["family"] == "base"
        }
        if not base_correct:
            base_correct = external_base.get(model_key, {})
        missing = [
            record
            for record in records
            if record["family"] in ("missing_bridge_table", "missing_fk_column")
        ]
        if not missing:
            continue

        by_family = defaultdict(list)
        for record in missing:
            variant = variants.get(record["variant_id"])
            if variant is None:
                continue
            db_path = args.data_root / variant["database_path"]
            predicted_sql = record.get("predicted_sql") or ""
            reads, error = (
                reads_for_sql(db_path, predicted_sql)
                if predicted_sql and not record.get("error")
                else (None, record.get("error") or "empty prediction")
            )
            removed_tables = set()
            removed_columns = set()
            for item in variant["perturbation"].get("removed", []):
                if item["kind"] == "table":
                    removed_tables.add(item["id"].lower())
                    for column in item.get("columns", []):
                        removed_columns.add(column.lower())
                else:
                    removed_columns.add(item["id"].lower())

            used_removed_table = False
            used_removed_column = False
            if reads is not None:
                used_removed_table = any(
                    table in removed_tables for table, _ in reads
                )
                used_removed_column = any(
                    f"{table}.{column}" in removed_columns
                    for table, column in reads
                )

            evidence = variant.get("evidence") or ""
            removed_names = {
                item["id"].lower() for item in variant["perturbation"].get("removed", [])
            }
            evidence_leak = any(
                name_in_text(name.split(".", 1)[-1], evidence)
                for name in removed_names
            )
            star = select_star(predicted_sql)
            correct = bool(record["correct"])
            compliance_unknown = correct and reads is None
            compliant = (
                correct
                and reads is not None
                and not used_removed_table
                and not used_removed_column
            )

            by_family[record["family"]].append(
                {
                    "correct": correct,
                    "compliant": compliant,
                    "compliance_unknown": compliance_unknown,
                    "select_star": star,
                    "used_removed_table": used_removed_table,
                    "used_removed_column": used_removed_column,
                    "evidence_leak": evidence_leak,
                    "authorizer_error": error,
                    "base_correct": base_correct.get(
                        record["variant_id"].split("__", 1)[0]
                    ),
                }
            )

        model_report = {}
        for family, rows in sorted(by_family.items()):
            total = len(rows)
            correct = sum(row["correct"] for row in rows)
            compliant = sum(row["compliant"] for row in rows)
            non_star = [row for row in rows if not row["select_star"]]
            base_correct_rows = [
                row for row in rows if row["base_correct"]
            ]
            model_report[family] = {
                "n": total,
                "ordinary_correct": correct,
                "ordinary_accuracy": correct / total if total else None,
                "strict_compliant_correct": compliant,
                "strict_compliance_rate": compliant / total if total else None,
                "non_star_n": len(non_star),
                "non_star_compliant_correct": sum(
                    row["compliant"] for row in non_star
                ),
                "non_star_compliance_rate": (
                    sum(row["compliant"] for row in non_star) / len(non_star)
                    if non_star
                    else None
                ),
                "select_star_count": sum(row["select_star"] for row in rows),
                "compliance_unknown_correct": sum(
                    row["compliance_unknown"] for row in rows
                ),
                "removed_table_usage": sum(
                    row["used_removed_table"] for row in rows
                ),
                "removed_column_usage": sum(
                    row["used_removed_column"] for row in rows
                ),
                "removed_table_usage_correct": sum(
                    row["correct"] and row["used_removed_table"]
                    for row in rows
                ),
                "removed_column_usage_correct": sum(
                    row["correct"] and row["used_removed_column"]
                    for row in rows
                ),
                "evidence_leak_count": sum(
                    row["evidence_leak"] for row in rows
                ),
                "evidence_leak_correct": sum(
                    row["correct"] and row["evidence_leak"] for row in rows
                ),
                "authorizer_errors": sum(
                    bool(row["authorizer_error"]) for row in rows
                ),
                "base_correct_n": len(base_correct_rows),
                "base_correct_strict_compliant": sum(
                    row["compliant"] for row in base_correct_rows
                ),
                "base_correct_compliance_rate": (
                    sum(row["compliant"] for row in base_correct_rows)
                    / len(base_correct_rows)
                    if base_correct_rows
                    else None
                ),
            }
        report[model_key] = model_report

    (args.output_dir / "missing_compliance_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Missing-schema compliance audit",
        "",
        "| model | family | n | correct | strict compliant | select * | evidence leak | authorizer errors |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model_key, families in sorted(report.items()):
        for family, values in sorted(families.items()):
            lines.append(
                f"| {model_key} | {family} | {values['n']} | "
                f"{values['ordinary_correct']} | "
                f"{values['strict_compliant_correct']} | "
                f"{values['select_star_count']} | "
                f"{values['evidence_leak_count']} | "
                f"{values['authorizer_errors']} |"
            )
    (args.output_dir / "missing_compliance_audit.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
