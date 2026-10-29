#!/usr/bin/env python3
"""Recompute the headline numbers from raw score files and compare them with the
published summaries. Any mismatch is printed with the expected/actual values."""

import json
from collections import defaultdict
from pathlib import Path

BASE = Path("/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025")
SPIDER = Path("/root/fsas/home/xiaotao/xiaotao/Spider2-Lite/spider2_retry_20261028")
MODELS = ("qwen3_0_6b", "qwen3_1_7b", "qwen3_4b", "qwen2_5_coder_1_5b", "api_control")
issues = []


def read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def check(label, expected, actual, tol=1e-9):
    ok = expected is not None and abs(expected - actual) <= tol
    if not ok:
        issues.append((label, expected, actual))
    return ok


def bird_ok(row):
    return row.get("evaluation_status") != "evaluation_error"


def audit_fixed():
    run = BASE / "fixed_k_fk_20261029"
    published = json.loads((run / "reports/results.json").read_text())["models"]
    for model in MODELS:
        rows = read(run / f"scores/{model}.jsonl")
        by_family = defaultdict(dict)
        for row in rows:
            by_family[row["family"]][row["question_id"]] = row
        for target in ("130", "200"):
            plain = {q: r for q, r in by_family[f"plain_fixed_{target}"].items() if bird_ok(r)}
            fk = {q: r for q, r in by_family[f"fk1_fixed_{target}"].items() if bird_ok(r)}
            paired = set(plain) & set(fk)
            plain_acc = sum(plain[q]["correct"] for q in paired) / len(paired)
            fk_acc = sum(fk[q]["correct"] for q in paired) / len(paired)
            ref = published[model][target]
            check(f"fixed {model} {target} n", ref["paired_n"], len(paired))
            check(f"fixed {model} {target} plain", ref["plain_accuracy"], plain_acc)
            check(f"fixed {model} {target} fk", ref["fk1_accuracy"], fk_acc)
    print("fixed_k checked")


def audit_equal():
    run = BASE / "equal_budget_fk_20261028"
    published = json.loads((run / "reports/equal_budget_execution_summary.json").read_text())["models"]
    for model in MODELS:
        rows = read(run / f"scores/{model}.jsonl")
        by_family = defaultdict(dict)
        for row in rows:
            by_family[row["family"]][row["question_id"]] = row
        for target in ("110", "130", "200"):
            plain = {q: r for q, r in by_family[f"plain_budget_{target}"].items() if bird_ok(r)}
            fk = {q: r for q, r in by_family[f"fk1_budget_{target}"].items() if bird_ok(r)}
            paired = set(plain) & set(fk)
            plain_acc = sum(plain[q]["correct"] for q in paired) / len(paired)
            fk_acc = sum(fk[q]["correct"] for q in paired) / len(paired)
            ref = published[model][target]
            check(f"budget {model} {target} n", ref["paired_n"], len(paired))
            check(f"budget {model} {target} plain", ref["plain_accuracy"], plain_acc)
            check(f"budget {model} {target} fk", ref["fk1_accuracy"], fk_acc)
    print("equal_budget checked")


def audit_synonym():
    run = BASE / "synonym_real_rerun_20261028"
    published = json.loads((run / "reports/real_synonym_rerun_summary.json").read_text())["paired_results"]
    for model in MODELS:
        rows = read(run / f"scores/{model}.jsonl")
        by_family = defaultdict(dict)
        for row in rows:
            by_family[row["family"]][row["question_id"]] = row
        base = {q: r for q, r in by_family["base"].items() if bird_ok(r)}
        for level in ("5", "10", "20", "50"):
            pert = {q: r for q, r in by_family[f"add_real_synonym_{level}"].items() if bird_ok(r)}
            paired = set(base) & set(pert)
            base_acc = sum(base[q]["correct"] for q in paired) / len(paired)
            pert_acc = sum(pert[q]["correct"] for q in paired) / len(paired)
            ref = published[model][level]
            check(f"synonym {model} {level} n", ref["paired_n"], len(paired))
            check(f"synonym {model} {level} base", ref["baseline_accuracy"], base_acc)
            check(f"synonym {model} {level} pert", ref["perturbed_accuracy"], pert_acc)
    print("synonym checked")


def audit_strict():
    run = BASE / "bridge_strict_20261029"
    published = json.loads((run / "strict_all/strict_summary.json").read_text())["families"]
    for model in MODELS:
        rows = read(run / f"strict_all/strict_{model}.jsonl")
        for family in ("missing_bridge_table", "missing_fk_column"):
            sub = [r for r in rows if r["family"] == family and r["status"] != "gold_unscoreable"]
            ref = published[family][model]
            check(f"strict {model} {family} n", ref["n_scoreable"], len(sub))
            check(f"strict {model} {family} strict", ref["strict_correct"], sum(r["strict_correct"] for r in sub))
            check(f"strict {model} {family} perm",
                  ref["permissive_correct"], sum(r["permissive_correct"] for r in sub))
    print("strict checked")


def audit_spider():
    published = json.loads((SPIDER / "reports/results.json").read_text())
    ref = {(row["condition"], row["model"]): row for row in published["rows"] if row["stratum"] == "all"}
    scores = {}
    for model in MODELS:
        for row in read(SPIDER / f"scores/{model}.jsonl"):
            scores[(model, row["condition"], row["instance_id"])] = row
    common = None
    for model in MODELS:
        for condition in ("base", "random20", "synonym20"):
            ids = {iid for (m, c, iid), row in scores.items() if m == model and c == condition and row["scorable"]}
            common = ids if common is None else common & ids
    check("spider common n", published["common_scored_n"], len(common))
    for model in MODELS:
        for condition in ("random20", "synonym20"):
            pert = [scores[(model, condition, i)] for i in common]
            base = [scores[(model, "base", i)] for i in common]
            check(f"spider {model} {condition} base", ref[(condition, model)]["base_accuracy"],
                  sum(r["correct"] for r in base) / len(common))
            check(f"spider {model} {condition} pert", ref[(condition, model)]["perturbed_accuracy"],
                  sum(r["correct"] for r in pert) / len(common))
    print("spider checked")


if __name__ == "__main__":
    audit_fixed()
    audit_equal()
    audit_synonym()
    audit_strict()
    audit_spider()
    print(f"\nissues: {len(issues)}")
    for label, expected, actual in issues[:30]:
        print(f"  {label}: published={expected} recomputed={actual}")
    Path("/root/fsas/home/xiaotao/xiaotao/BIRD_MINIDEV_VALIDATION_20261025/number_audit.json").write_text(
        json.dumps({"issues": [{"label": l, "published": e, "recomputed": a} for l, e, a in issues]},
                   ensure_ascii=False, indent=1), encoding="utf-8")
