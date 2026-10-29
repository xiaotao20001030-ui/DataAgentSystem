#!/usr/bin/env python3
"""Improved sqlglot reference extractor + validation against authorizer truth.

1) On plain top-k predictions: how often does generated SQL reference objects
   outside the prompt schema (after resolving aliases, CTEs and subqueries)?
2) On hidden-schema variants: does the extractor recover the same objects that
   the SQLite authorizer actually denied?
"""

import json
import sys
from collections import Counter
from pathlib import Path

import sqlglot
from sqlglot import exp

BASE = Path("/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025")
STAGES = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b", "api_control")


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def extract(sql):
    """Return (tables, qualified_columns, unqualified_columns, derived_aliases)."""
    tree = sqlglot.parse_one(sql, read="sqlite")
    derived = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for sub in tree.find_all(exp.Subquery):
        if sub.alias:
            derived.add(sub.alias.lower())
    aliases, tables = {}, set()
    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name:
            continue
        if table.alias:
            aliases[table.alias.lower()] = name
        if name not in derived:
            tables.add(name)
    qualified, unqualified = set(), set()
    for column in tree.find_all(exp.Column):
        table = (column.table or "").lower()
        name = (column.name or "").lower()
        if not name:
            continue
        if table:
            table = aliases.get(table, table)
            if table in derived:
                continue
            qualified.add(f"{table}.{name}")
        else:
            unqualified.add(name)
    return tables, qualified, unqualified, derived


def missing_refs(sql, visible_columns):
    tables, qualified, unqualified, derived = extract(sql)
    visible_tables = {c.split(".")[0] for c in visible_columns}
    visible_cols = set(visible_columns)
    missing_tables = tables - visible_tables - derived
    missing_cols = set()
    for ref in qualified:
        table, _, column = ref.partition(".")
        if table in visible_tables and ref not in visible_cols:
            missing_cols.add(ref)
    # an unqualified name that matches no visible column but matches exactly one
    # table's column set is reported separately by the caller, never as missing.
    return missing_tables, missing_cols, unqualified


def validate_plain():
    run = BASE / "fixed_k_fk_20261029"
    variants = {v["variant_id"]: v for v in read(run / "variants/fixed_variants.jsonl")}
    stats = {}
    for model in STAGES:
        rows = [p for p in read(run / f"predictions/{model}.jsonl") if p["family"] == "plain_fixed_130"]
        parsed = failed = outside = 0
        miss_t = miss_c = 0
        for pred in rows:
            variant = variants[pred["variant_id"]]
            try:
                mt, mc, _ = missing_refs(pred["predicted_sql"], variant["schema_columns"])
                parsed += 1
            except Exception:
                failed += 1
                continue
            miss_t += len(mt)
            miss_c += len(mc)
            if mt or mc:
                outside += 1
        stats[model] = {"n": len(rows), "parsed": parsed, "parse_failed": failed,
                        "outside": outside, "outside_rate": round(outside / len(rows), 4),
                        "missing_tables": miss_t, "missing_columns": miss_c}
    print(json.dumps(stats, ensure_ascii=False, indent=1))


def validate_hidden(model):
    run = BASE / "bridge_strict_20261029"
    pert = {v["variant_id"]: v for v in read(BASE / "perturbations/output/mini_dev_perturbations.jsonl")}
    preds = {p["variant_id"]: p for p in read(BASE / "model_eval/predictions" / f"{model}.jsonl")}
    rows = [r for r in read(run / f"strict_all/strict_{model}.jsonl")
            if r["status"] == "denied_hidden_access"]
    found = covered = 0
    partial = 0
    for row in rows:
        variant = pert[row["variant_id"]]
        sql = preds[row["variant_id"]]["predicted_sql"]
        try:
            mt, mc, _ = missing_refs(sql, variant["schema_columns"])
        except Exception:
            continue
        detected = {f"{t}" for t in mt} | mc
        denied = {x.strip().lower() for x in row.get("denied_refs", "").split(";") if x.strip()}
        hit = denied & detected
        if hit:
            found += 1
            if hit == denied:
                covered += 1
            else:
                partial += 1
    print(json.dumps({"model": model, "denied_rows": len(rows), "detected_any": found,
                      "detected_all": covered, "partial": partial,
                      "recall_any": round(found / len(rows), 4) if rows else None}, ensure_ascii=False))


if __name__ == "__main__":
    validate_plain()
    for m in ("api_control", "qwen3_4b"):
        validate_hidden(m)
