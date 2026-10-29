#!/usr/bin/env python3
"""Prototype: parse generated SQL with sqlglot and list references outside the prompt schema."""

import json
import sqlglot
from sqlglot import exp
from collections import Counter
from pathlib import Path

RUN = Path("/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025/fixed_k_fk_20261029")
MODEL = "qwen3_4b"
FAMILY = "plain_fixed_130"


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def refs(sql):
    tree = sqlglot.parse_one(sql, read="sqlite")
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    aliases = {}
    tables = set()
    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name or name in cte_names:
            continue
        if table.alias:
            aliases[table.alias.lower()] = name
        tables.add(name)
    columns = set()
    for column in tree.find_all(exp.Column):
        table = (column.table or "").lower()
        name = (column.name or "").lower()
        if table:
            table = aliases.get(table, table)
            if table in cte_names:
                continue
            columns.add(f"{table}.{name}")
        else:
            columns.add(name)
    return tables, columns


def main():
    variants = {v["variant_id"]: v for v in read(RUN / "variants/fixed_variants.jsonl")}
    preds = [p for p in read(RUN / f"predictions/{MODEL}.jsonl") if p["family"] == FAMILY]
    parsed = failed = 0
    missing_tables = missing_cols = outside = 0
    examples = []
    for pred in preds:
        variant = variants[pred["variant_id"]]
        visible_tables = {c.split(".")[0].lower() for c in variant["schema_columns"]}
        visible_cols = {c.lower() for c in variant["schema_columns"]}
        try:
            tables, cols = refs(pred["predicted_sql"])
            parsed += 1
        except Exception:
            failed += 1
            continue
        mt = {t for t in tables if t not in visible_tables}
        mc = {c for c in cols if "." in c and c not in visible_cols}
        missing_tables += len(mt)
        missing_cols += len(mc)
        if mt or mc:
            outside += 1
            if len(examples) < 8:
                examples.append((pred["variant_id"], sorted(mt)[:4], sorted(mc)[:4]))
    print(json.dumps({"predictions": len(preds), "parsed": parsed, "parse_failed": failed,
                      "with_missing": outside, "missing_tables": missing_tables,
                      "missing_columns": missing_cols}, ensure_ascii=False))
    for row in examples:
        print(row)


if __name__ == "__main__":
    main()
