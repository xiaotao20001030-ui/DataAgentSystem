#!/usr/bin/env python3
"""Re-analyze BIRD Mini-Dev execution scores without re-running models.

This script is intended to run where the original score files live. It
produces the analyses that the first report was missing:

1. A qid-aligned execution gate (the original script computed common ids but
   then bootstrapped unaligned lists).
2. Transition matrices for every perturbation level.
3. Baseline-correct extra-failure estimates with question-clustered bootstrap.
4. Stratification of add_synonym by same_name vs lexical synonym columns.
5. Stratification of add_random by whether the perturbation added new tables.
6. The same table-placement stratification for the real-schema synonym set.

It does not need model inference and does not modify the original score files.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


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
        "--real-variants",
        type=Path,
        default=project_root / "perturbations" / "output"
        / "real_synonym_sensitivity"
        / "mini_dev_add_real_synonym_20.jsonl",
    )
    parser.add_argument("--control", default="api_control")
    parser.add_argument(
        "--gate-families",
        default="add_random_20,add_synonym_20",
        help="Comma-separated families for the execution gate.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "analysis" / "reanalysis",
    )
    parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261019)
    return parser.parse_args()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def dedupe_by_variant(records):
    by_variant = {}
    duplicates = 0
    for record in records:
        if record["variant_id"] in by_variant:
            duplicates += 1
        by_variant[record["variant_id"]] = record
    return by_variant, duplicates


def family_name(variant):
    perturbation = variant["perturbation"]
    if perturbation["level"] is None:
        return perturbation["family"]
    return f"{perturbation['family']}_{perturbation['level']}"


def table_set(record):
    return {table["table"].lower() for table in record["schema"]}


def gold_table_set(record):
    return {table.lower() for table in record["gold_tables"]}


def variant_metadata(variant):
    perturbation = variant["perturbation"]
    added = perturbation["added"]
    new_tables = table_set(variant) - gold_table_set(variant)
    return {
        "variant_id": variant["variant_id"],
        "question_id": variant["question_id"],
        "family": family_name(variant),
        "base_family": perturbation["family"],
        "level": perturbation["level"],
        "added_count": len(added),
        "generated_count": sum(bool(column.get("generated")) for column in added),
        "same_name_count": sum(
            column.get("relation") == "same_name" for column in added
        ),
        "synonym_count": sum(
            column.get("relation") == "synonym" for column in added
        ),
        "new_table_count": len(new_tables),
        "new_table_columns": sum(
            column["table"].lower() in new_tables for column in added
        ),
        "removed": perturbation.get("removed", []),
    }


def accuracy(records):
    if not records:
        return None
    return sum(record["correct"] for record in records) / len(records)


def bootstrap_mean(values, iterations, seed):
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return None
    rng = np.random.default_rng(seed)
    draws = np.empty(iterations)
    for index in range(iterations):
        sample = rng.integers(0, len(values), len(values))
        draws[index] = values[sample].mean()
    return {
        "n": int(len(values)),
        "mean": float(values.mean()),
        "ci95": [
            float(np.quantile(draws, 0.025)),
            float(np.quantile(draws, 0.975)),
        ],
    }


def paired_gate(small, control, family, iterations, seed):
    small_base = small["base"]
    small_noise = small["families"].get(family, {})
    control_base = control["base"]
    control_noise = control["families"].get(family, {})
    common = sorted(
        set(small_base)
        & set(small_noise)
        & set(control_base)
        & set(control_noise)
    )
    if not common:
        return None
    small_drop = np.array(
        [int(small_base[qid]) - int(small_noise[qid]) for qid in common],
        dtype=float,
    )
    control_drop = np.array(
        [int(control_base[qid]) - int(control_noise[qid]) for qid in common],
        dtype=float,
    )
    diff = small_drop - control_drop
    rng = np.random.default_rng(seed)
    draws = np.empty(iterations)
    for index in range(iterations):
        sample = rng.integers(0, len(diff), len(diff))
        draws[index] = diff[sample].mean()
    low, high = np.quantile(draws, [0.025, 0.975])
    return {
        "n_questions": len(common),
        "small_drop": float(small_drop.mean()),
        "control_drop": float(control_drop.mean()),
        "difference": float(diff.mean()),
        "ci95": [float(low), float(high)],
        "p_one_sided": float(
            (np.count_nonzero(draws <= 0) + 1) / (iterations + 1)
        ),
        "p_one_sided_10pp": float(
            (np.count_nonzero(draws <= 0.10) + 1) / (iterations + 1)
        ),
        "excludes_10pp": bool(high < 0.10),
        "strict_ci_lower_10pp": bool(low >= 0.10),
    }


def transition(small, family):
    base = small["base"]
    noise = small["families"].get(family, {})
    common = sorted(set(base) & set(noise))
    counts = Counter()
    for qid in common:
        counts[(bool(base[qid]), bool(noise[qid]))] += 1
    total = len(common)
    if not total:
        return None
    return {
        "n": total,
        "base_correct_perturbed_correct": counts[(True, True)],
        "base_correct_perturbed_wrong": counts[(True, False)],
        "base_wrong_perturbed_correct": counts[(False, True)],
        "base_wrong_perturbed_wrong": counts[(False, False)],
        "net_accuracy_change": (
            counts[(False, True)] - counts[(True, False)]
        ) / total,
    }


def baseline_correct_gap(small, control, family, iterations, seed):
    small_base = small["base"]
    small_noise = small["families"].get(family, {})
    control_base = control["base"]
    control_noise = control["families"].get(family, {})
    common = sorted(
        qid
        for qid in set(small_base) & set(small_noise) & set(control_base) & set(control_noise)
        if small_base[qid] and control_base[qid]
    )
    if not common:
        return None
    values = np.array(
        [
            int(small_noise[qid]) - int(control_noise[qid])
            for qid in common
        ],
        dtype=float,
    )
    # extra failure = control retention - small retention
    extra_failure = -values
    result = bootstrap_mean(extra_failure, iterations, seed)
    result["definition"] = (
        "DeepSeek retention minus small-model retention on questions both "
        "answered correctly at baseline"
    )
    return result


def stratified_accuracy(records, bucket_fn, label):
    groups = defaultdict(list)
    for record in records:
        groups[bucket_fn(record["meta"])].append(record)
    rows = []
    for bucket in sorted(groups, key=str):
        group = groups[bucket]
        rows.append(
            {
                "bucket": bucket,
                "n": len(group),
                "accuracy": accuracy(group),
            }
        )
    return {"label": label, "rows": rows}


def load_model_scores(path):
    records = read_jsonl(path)
    deduped, duplicates = dedupe_by_variant(records)
    base = {}
    families = defaultdict(dict)
    for variant_id, record in deduped.items():
        if record["family"] == "base":
            base[record["question_id"]] = bool(record["correct"])
        else:
            families[record["family"]][record["question_id"]] = bool(
                record["correct"]
            )
    return {
        "path": str(path),
        "duplicates": duplicates,
        "base": base,
        "families": dict(families),
        "records": list(deduped.values()),
    }


def retrieved_vs_base(model, iterations, seed):
    base = model["base"]
    retrieved_families = [
        family
        for family in model["families"]
        if family.startswith("retrieved_schema")
    ]
    if not retrieved_families:
        return None
    family = sorted(retrieved_families)[0]
    retrieved = model["families"][family]
    common = sorted(set(base) & set(retrieved))
    if not common:
        return None
    # Positive means the retrieved schema lowered accuracy.
    drop = np.array(
        [int(base[qid]) - int(retrieved[qid]) for qid in common],
        dtype=float,
    )
    result = bootstrap_mean(drop, iterations, seed)
    result["family"] = family
    result["base_accuracy"] = float(
        np.mean([base[qid] for qid in common])
    )
    result["retrieved_accuracy"] = float(
        np.mean([retrieved[qid] for qid in common])
    )
    return result


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    variant_by_id = {
        record["variant_id"]: record for record in read_jsonl(args.variants)
    }
    if args.real_variants.exists():
        for record in read_jsonl(args.real_variants):
            variant_by_id[record["variant_id"]] = record
    meta_by_variant = {
        variant_id: variant_metadata(record)
        for variant_id, record in variant_by_id.items()
    }

    score_paths = sorted(args.scores_dir.glob("*.jsonl"))
    if not score_paths:
        raise SystemExit(f"No score files found in {args.scores_dir}")
    models = {
        path.stem: load_model_scores(path)
        for path in score_paths
        if not path.name.endswith(".summary.json")
    }
    if args.control not in models:
        raise SystemExit(
            f"Control model {args.control!r} not found; have {sorted(models)}"
        )
    control = models[args.control]

    report = {
        "control_model": args.control,
        "models": sorted(models),
        "scores_dir": str(args.scores_dir),
        "gate": {},
        "transitions": {},
        "baseline_correct": {},
        "strata": {},
        "retrieved_vs_base": {},
    }

    gate_families = [
        item.strip()
        for item in args.gate_families.split(",")
        if item.strip()
    ]
    for model_key, model in sorted(models.items()):
        if model_key == args.control:
            continue
        report["gate"][model_key] = {}
        report["baseline_correct"][model_key] = {}
        for family in gate_families:
            report["gate"][model_key][family] = paired_gate(
                model,
                control,
                family,
                args.bootstrap,
                args.seed,
            )
            report["baseline_correct"][model_key][family] = (
                baseline_correct_gap(
                    model,
                    control,
                    family,
                    args.bootstrap,
                    args.seed,
                )
            )

        report["transitions"][model_key] = {}
        for family in sorted(model["families"]):
            if family.startswith("missing_"):
                continue
            report["transitions"][model_key][family] = transition(
                model,
                family,
            )
        report["retrieved_vs_base"][model_key] = retrieved_vs_base(
            model,
            args.bootstrap,
            args.seed,
        )

    # Attach metadata to score records once per model.
    for model in models.values():
        for record in model["records"]:
            record["meta"] = meta_by_variant.get(
                record["variant_id"],
                {},
            )

    # Synonym / random / real-synonym strata for each model.
    for model_key, model in sorted(models.items()):
        records = model["records"]
        synonym_records = [
            record
            for record in records
            if record["family"].startswith("add_synonym_")
        ]
        random_records = [
            record
            for record in records
            if record["family"].startswith("add_random_")
        ]
        real_records = [
            record
            for record in records
            if record["family"].startswith("add_real_synonym")
        ]
        report["strata"][model_key] = {
            "synonym_by_same_name_count": stratified_accuracy(
                synonym_records,
                lambda meta: min(meta.get("same_name_count", 0), 5),
                "same_name_count (capped at 5)",
            ),
            "random_by_new_table_count": stratified_accuracy(
                random_records,
                lambda meta: min(meta.get("new_table_count", 0), 5),
                "new_table_count (capped at 5)",
            ),
            "real_synonym_by_new_table": stratified_accuracy(
                real_records,
                lambda meta: "new_table"
                if meta.get("new_table_count", 0) > 0
                else "gold_tables_only",
                "real synonym table placement",
            ),
        }

    output_path = args.output_dir / "reanalysis.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# BIRD Mini-Dev re-analysis",
        "",
        f"- control model: `{args.control}`",
        f"- models: {', '.join(sorted(models))}",
        f"- score files: `{args.scores_dir}`",
        "",
        "## Gate (qid-aligned)",
        "",
        "| model | family | n | small drop | control drop | diff | 95% CI | excludes +10pp |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for model_key, families in sorted(report["gate"].items()):
        for family, result in sorted(families.items()):
            if result is None:
                lines.append(
                    f"| {model_key} | {family} | 0 | - | - | - | - | - |"
                )
                continue
            lines.append(
                f"| {model_key} | {family} | {result['n_questions']} | "
                f"{result['small_drop'] * 100:.2f} | "
                f"{result['control_drop'] * 100:.2f} | "
                f"{result['difference'] * 100:.2f} | "
                f"[{result['ci95'][0] * 100:.2f}, "
                f"{result['ci95'][1] * 100:.2f}] | "
                f"{result['excludes_10pp']} |"
            )

    lines.extend(
        [
            "",
            "## Baseline-correct extra failure",
            "",
            "| model | family | n | extra failure | 95% CI |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for model_key, families in sorted(report["baseline_correct"].items()):
        for family, result in sorted(families.items()):
            if result is None:
                lines.append(f"| {model_key} | {family} | 0 | - | - |")
                continue
            lines.append(
                f"| {model_key} | {family} | {result['n']} | "
                f"{result['mean'] * 100:.2f} | "
                f"[{result['ci95'][0] * 100:.2f}, "
                f"{result['ci95'][1] * 100:.2f}] |"
            )

    lines.extend(
        [
            "",
            "## Synonym stratification: same_name count",
            "",
            "| model | bucket | n | accuracy |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for model_key, strata in sorted(report["strata"].items()):
        for row in strata["synonym_by_same_name_count"]["rows"]:
            lines.append(
                f"| {model_key} | {row['bucket']} | {row['n']} | "
                f"{row['accuracy'] * 100:.2f} |"
            )

    lines.extend(
        [
            "",
            "## Random stratification: new table count",
            "",
            "| model | bucket | n | accuracy |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for model_key, strata in sorted(report["strata"].items()):
        for row in strata["random_by_new_table_count"]["rows"]:
            lines.append(
                f"| {model_key} | {row['bucket']} | {row['n']} | "
                f"{row['accuracy'] * 100:.2f} |"
            )

    lines.extend(
        [
            "",
            "## Real-synonym stratification: table placement",
            "",
            "| model | bucket | n | accuracy |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for model_key, strata in sorted(report["strata"].items()):
        for row in strata["real_synonym_by_new_table"]["rows"]:
            lines.append(
                f"| {model_key} | {row['bucket']} | {row['n']} | "
                f"{row['accuracy'] * 100:.2f} |"
            )

    lines.extend(
        [
            "",
            "## Retrieved schema vs base",
            "",
            "| model | family | n | base acc | retrieved acc | drop | 95% CI |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for model_key, result in sorted(report["retrieved_vs_base"].items()):
        if result is None:
            lines.append(f"| {model_key} | - | 0 | - | - | - | - |")
            continue
        lines.append(
            f"| {model_key} | {result['family']} | {result['n']} | "
            f"{result['base_accuracy'] * 100:.2f} | "
            f"{result['retrieved_accuracy'] * 100:.2f} | "
            f"{result['mean'] * 100:.2f} | "
            f"[{result['ci95'][0] * 100:.2f}, "
            f"{result['ci95'][1] * 100:.2f}] |"
        )

    markdown_path = args.output_dir / "reanalysis.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(output_path), "markdown": str(markdown_path)}, indent=2))


if __name__ == "__main__":
    main()
