#!/usr/bin/env python3
"""Preserve the initial run and prepare only variants with omitted table names."""
import json
import shutil
from pathlib import Path

from generate_silver import read_jsonl

ROOT = Path(__file__).resolve().parent
labels = {x["instance_id"]: x for x in read_jsonl(ROOT / "labels/schema_labels.jsonl") if x.get("eligible")}
path = ROOT / "variants/variants.jsonl"
rows = read_jsonl(path)
changed_qids = set()
for row in rows:
    represented = {c.split(".", 1)[0].casefold() for c in row["schema_columns"]}
    missing = [t for t in labels[row["instance_id"]]["tables"] if t.casefold() not in represented]
    additions = [f"table {t};" for t in missing if f"table {t};" not in row["schema_text"].splitlines()]
    if additions:
        row["schema_text"] = "\n".join(additions) + "\n" + row["schema_text"]
        changed_qids.add(row["instance_id"])
if not changed_qids:
    raise SystemExit("No missing table prompts found; correction was already prepared")
provenance = ROOT / "provenance/before_table_schema_fix"
provenance.mkdir(parents=True, exist_ok=True)
shutil.copy2(path, provenance / "variants.jsonl")
for name in ("predictions", "scores", "reports"):
    shutil.copytree(ROOT / name, provenance / name, dirs_exist_ok=True)
if (ROOT / "COMPLETE").exists():
    shutil.move(str(ROOT / "COMPLETE"), str(provenance / "COMPLETE"))
(ROOT / "QUALITY_RECHECK_PENDING").write_text("Correct required table names in prompt for: " + ",".join(sorted(changed_qids)) + "\n")
def write_jsonl(target, entries):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in entries))
write_jsonl(path, rows)
write_jsonl(ROOT / "schema_correction/variants.jsonl", [x for x in rows if x["instance_id"] in changed_qids])
print(json.dumps({"corrected_questions": sorted(changed_qids), "correction_variants": sum(x["instance_id"] in changed_qids for x in rows)}))
