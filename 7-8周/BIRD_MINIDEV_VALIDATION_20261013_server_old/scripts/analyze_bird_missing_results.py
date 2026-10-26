#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote


MODELS = (
    "qwen3_0_6b",
    "qwen3_1_7b",
    "qwen3_4b",
    "qwen2_5_coder_1_5b",
    "api_control",
)
FAMILIES = ("missing_bridge_table", "missing_fk_column")
SEED = 20261020
BOOTSTRAP_REPLICATES = 10_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/root/fsas/home/xiaotao/xiaotao/MINIDEV"),
    )
    parser.add_argument(
        "--scores-dir",
        type=Path,
        default=None,
        help="Directory containing the five missing-condition score JSONL files.",
    )
    parser.add_argument(
        "--base-scores-dir",
        type=Path,
        default=None,
        help="Directory containing the five base-condition score JSONL files.",
    )
    parser.add_argument(
        "--variants",
        type=Path,
        default=None,
        help="Perturbation JSONL file.",
    )
    parser.add_argument(
        "--output-prefix",
        default="missing_schema",
        help="Prefix for analysis and summary output files.",
    )
    parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def bootstrap_rng(model_key: str, family: str) -> random.Random:
    digest = hashlib.sha256(f"{SEED}:{model_key}:{family}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def schema_reads(db_path: Path, sql: str) -> tuple[set[tuple[str, str]], str | None]:
    reads: set[tuple[str, str]] = set()
    connection = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)

    def authorizer(
        action: int,
        arg1: str | None,
        arg2: str | None,
        database: str | None,
        trigger: str | None,
    ) -> int:
        del database, trigger
        if action == sqlite3.SQLITE_READ and arg1 and arg2:
            reads.add((arg1.casefold(), arg2.casefold()))
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorizer)
    error = None
    try:
        connection.execute("EXPLAIN " + sql).fetchall()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        connection.close()
    return reads, error


def removed_schema_items(variant: dict) -> list[dict]:
    return variant["perturbation"].get("removed", [])


def uses_removed_schema_item(reads: set[tuple[str, str]], removed: list[dict]) -> bool:
    for item in removed:
        kind = item.get("kind")
        identifier = item.get("id", "")
        if kind == "table":
            table = identifier.casefold()
            if any(read_table == table for read_table, _ in reads):
                return True
        elif kind == "column" and "." in identifier:
            table, column = identifier.split(".", 1)
            if (table.casefold(), column.casefold()) in reads:
                return True
    return False


def safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize_records(records: list[dict]) -> dict:
    evaluated = [record for record in records if record["evaluation_status"] != "evaluation_error"]
    base_correct = [record for record in evaluated if record["base_correct"]]
    compliance_evaluated = [
        record for record in evaluated if record["compliance_analysis_error"] is None
    ]
    base_correct_compliance = [
        record for record in compliance_evaluated if record["base_correct"]
    ]
    raw_correct = sum(record["correct"] for record in evaluated)
    retained = sum(record["correct"] for record in base_correct)
    compliant_correct = sum(record["compliant_correct"] for record in compliance_evaluated)
    compliant_retained = sum(
        record["compliant_correct"] for record in base_correct_compliance
    )
    return {
        "count": len(records),
        "evaluated": len(evaluated),
        "evaluation_errors": len(records) - len(evaluated),
        "correct": raw_correct,
        "accuracy": safe_rate(raw_correct, len(evaluated)),
        "base_correct": len(base_correct),
        "base_accuracy": safe_rate(len(base_correct), len(evaluated)),
        "retained_base_correct": retained,
        "retention_on_base_correct": safe_rate(retained, len(base_correct)),
        "matched_absolute_drop_pp": (
            100 * (safe_rate(raw_correct, len(evaluated)) - safe_rate(len(base_correct), len(evaluated)))
            if evaluated
            else None
        ),
        "removed_item_reads": sum(
            record["uses_removed_schema_item"] for record in evaluated
        ),
        "removed_item_read_rate": safe_rate(
            sum(record["uses_removed_schema_item"] for record in evaluated),
            len(evaluated),
        ),
        "correct_using_removed_item": sum(
            record["correct"] and record["uses_removed_schema_item"]
            for record in evaluated
        ),
        "correct_without_removed_item": sum(
            record["correct"] and not record["uses_removed_schema_item"]
            for record in evaluated
        ),
        "compliance_evaluated": len(compliance_evaluated),
        "compliance_analysis_errors": len(evaluated) - len(compliance_evaluated),
        "compliant_correct": compliant_correct,
        "compliant_accuracy": safe_rate(compliant_correct, len(compliance_evaluated)),
        "compliant_retained_base_correct": compliant_retained,
        "compliant_retention_on_base_correct": safe_rate(
            compliant_retained, len(base_correct_compliance)
        ),
    }


def clustered_bootstrap(
    records: list[dict],
    replicates: int,
    rng: random.Random,
) -> dict:
    by_question: dict[object, list[dict]] = defaultdict(list)
    for record in records:
        by_question[record["question_id"]].append(record)
    question_ids = list(by_question)
    if not question_ids:
        return {}

    metrics: dict[str, list[float]] = {
        "accuracy": [],
        "retention_on_base_correct": [],
        "compliant_accuracy": [],
        "compliant_retention_on_base_correct": [],
    }
    for _ in range(replicates):
        sampled = [rng.choice(question_ids) for _ in question_ids]
        rows = [record for question_id in sampled for record in by_question[question_id]]
        evaluated = [
            record for record in rows if record["evaluation_status"] != "evaluation_error"
        ]
        base_correct = [record for record in evaluated if record["base_correct"]]
        compliance_evaluated = [
            record for record in evaluated if record["compliance_analysis_error"] is None
        ]
        base_correct_compliance = [
            record for record in compliance_evaluated if record["base_correct"]
        ]

        candidates = {
            "accuracy": safe_rate(
                sum(record["correct"] for record in evaluated), len(evaluated)
            ),
            "retention_on_base_correct": safe_rate(
                sum(record["correct"] for record in base_correct), len(base_correct)
            ),
            "compliant_accuracy": safe_rate(
                sum(record["compliant_correct"] for record in compliance_evaluated),
                len(compliance_evaluated),
            ),
            "compliant_retention_on_base_correct": safe_rate(
                sum(record["compliant_correct"] for record in base_correct_compliance),
                len(base_correct_compliance),
            ),
        }
        for metric, value in candidates.items():
            if value is not None:
                metrics[metric].append(value)

    intervals = {}
    for metric, values in metrics.items():
        intervals[metric] = {
            "lower_95": percentile(values, 0.025) if values else None,
            "upper_95": percentile(values, 0.975) if values else None,
        }
    return {
        "replicates": replicates,
        "questions": len(question_ids),
        "intervals": intervals,
    }


def model_family_records(
    model_key: str,
    missing_scores: list[dict],
    variants_by_id: dict[str, dict],
    base_by_question: dict[object, dict],
    data_root: Path,
) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {family: [] for family in FAMILIES}
    for score in missing_scores:
        variant = variants_by_id[score["variant_id"]]
        family = score["family"]
        sql = score.get("predicted_sql", "") or ""
        reads, analysis_error = schema_reads(
            data_root / variant["database_path"],
            sql,
        ) if sql and not score.get("prediction_error") else (set(), None)
        base = base_by_question.get(score["question_id"])
        base_correct = bool(base and base.get("correct"))
        uses_removed = uses_removed_schema_item(reads, removed_schema_items(variant))
        result[family].append(
            {
                **score,
                "base_correct": base_correct,
                "uses_removed_schema_item": uses_removed,
                "compliant_correct": bool(score.get("correct") and not uses_removed),
                "compliance_analysis_error": analysis_error,
            }
        )
    return result


def common_base_comparison(
    model_records: list[dict],
    api_records: list[dict],
    replicates: int,
    rng: random.Random,
) -> dict:
    model_by_id = {record["variant_id"]: record for record in model_records}
    api_by_id = {record["variant_id"]: record for record in api_records}
    common_ids = [
        variant_id
        for variant_id in model_by_id.keys() & api_by_id.keys()
        if model_by_id[variant_id]["base_correct"]
        and api_by_id[variant_id]["base_correct"]
        and model_by_id[variant_id]["evaluation_status"] != "evaluation_error"
        and api_by_id[variant_id]["evaluation_status"] != "evaluation_error"
    ]
    if not common_ids:
        return {
            "common_base_correct_variants": 0,
            "common_base_correct_questions": 0,
            "gap_pp": None,
            "compliant_gap_pp": None,
            "bootstrap": {},
        }

    model_correct = sum(model_by_id[variant_id]["correct"] for variant_id in common_ids)
    api_correct = sum(api_by_id[variant_id]["correct"] for variant_id in common_ids)
    gap_pp = 100 * (api_correct - model_correct) / len(common_ids)

    by_question: dict[object, list[str]] = defaultdict(list)
    for variant_id in common_ids:
        by_question[model_by_id[variant_id]["question_id"]].append(variant_id)
    question_ids = list(by_question)
    gaps = []
    compliant_common_ids = [
        variant_id
        for variant_id in common_ids
        if model_by_id[variant_id]["compliance_analysis_error"] is None
        and api_by_id[variant_id]["compliance_analysis_error"] is None
    ]
    model_compliant_correct = sum(
        model_by_id[variant_id]["compliant_correct"]
        for variant_id in compliant_common_ids
    )
    api_compliant_correct = sum(
        api_by_id[variant_id]["compliant_correct"]
        for variant_id in compliant_common_ids
    )
    compliant_gap_pp = (
        100 * (api_compliant_correct - model_compliant_correct) / len(compliant_common_ids)
        if compliant_common_ids
        else None
    )
    compliant_by_question: dict[object, list[str]] = defaultdict(list)
    for variant_id in compliant_common_ids:
        compliant_by_question[model_by_id[variant_id]["question_id"]].append(variant_id)
    compliant_question_ids = list(compliant_by_question)
    compliant_gaps = []
    for _ in range(replicates):
        sampled = [rng.choice(question_ids) for _ in question_ids]
        ids = [variant_id for question_id in sampled for variant_id in by_question[question_id]]
        model_value = sum(model_by_id[variant_id]["correct"] for variant_id in ids)
        api_value = sum(api_by_id[variant_id]["correct"] for variant_id in ids)
        gaps.append(100 * (api_value - model_value) / len(ids))
        if compliant_question_ids:
            compliant_sampled = [
                rng.choice(compliant_question_ids)
                for _ in compliant_question_ids
            ]
            compliant_ids = [
                variant_id
                for question_id in compliant_sampled
                for variant_id in compliant_by_question[question_id]
            ]
            model_compliant_value = sum(
                model_by_id[variant_id]["compliant_correct"]
                for variant_id in compliant_ids
            )
            api_compliant_value = sum(
                api_by_id[variant_id]["compliant_correct"]
                for variant_id in compliant_ids
            )
            compliant_gaps.append(
                100
                * (api_compliant_value - model_compliant_value)
                / len(compliant_ids)
            )

    return {
        "common_base_correct_variants": len(common_ids),
        "common_base_correct_questions": len(question_ids),
        "model_retention": model_correct / len(common_ids),
        "api_retention": api_correct / len(common_ids),
        "gap_pp": gap_pp,
        "compliant_common_variants": len(compliant_common_ids),
        "compliant_common_questions": len(compliant_question_ids),
        "model_compliant_retention": (
            model_compliant_correct / len(compliant_common_ids)
            if compliant_common_ids
            else None
        ),
        "api_compliant_retention": (
            api_compliant_correct / len(compliant_common_ids)
            if compliant_common_ids
            else None
        ),
        "compliant_gap_pp": compliant_gap_pp,
        "bootstrap": {
            "replicates": replicates,
            "lower_95_pp": percentile(gaps, 0.025),
            "upper_95_pp": percentile(gaps, 0.975),
            "compliant_lower_95_pp": (
                percentile(compliant_gaps, 0.025)
                if compliant_gaps
                else None
            ),
            "compliant_upper_95_pp": (
                percentile(compliant_gaps, 0.975)
                if compliant_gaps
                else None
            ),
        },
    }


def format_percent(value: float | None) -> str:
    return "NA" if value is None else f"{100 * value:.2f}%"


def format_pp(value: float | None) -> str:
    return "NA" if value is None else f"{value:+.2f} pp"


def build_markdown(result: dict) -> str:
    lines = [
        "# BIRD Missing-Schema Perturbation Results",
        "",
        "This analysis evaluates the two missing-schema conditions required by the",
        "validation experiment. Reported accuracy is execution accuracy. Compliant",
        "accuracy additionally requires that the predicted SQL does not read any",
        "table or column removed from the supplied schema.",
        "",
        "## Raw and compliant results",
        "",
        "| Model | Family | Correct | Accuracy | Base-correct retention | Compliant correct | Compliant accuracy |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for model_key in MODELS:
        for family in FAMILIES:
            summary = result["models"][model_key]["families"][family]["summary"]
            lines.append(
                "| {model} | {family} | {correct}/{evaluated} | {accuracy} | "
                "{retention} | {compliant_correct}/{compliant_evaluated} | "
                "{compliant_accuracy} |".format(
                    model=model_key,
                    family=family,
                    correct=summary["correct"],
                    evaluated=summary["evaluated"],
                    accuracy=format_percent(summary["accuracy"]),
                    retention=format_percent(summary["retention_on_base_correct"]),
                    compliant_correct=summary["compliant_correct"],
                    compliant_evaluated=summary["compliance_evaluated"],
                    compliant_accuracy=format_percent(summary["compliant_accuracy"]),
                )
            )

    lines.extend(
        [
            "",
            "## Correct predictions that still read removed schema items",
            "",
            "| Model | Bridge table | Foreign-key column |",
            "|---|---:|---:|",
        ]
    )
    for model_key in MODELS:
        bridge = result["models"][model_key]["families"]["missing_bridge_table"]["summary"]
        foreign_key = result["models"][model_key]["families"]["missing_fk_column"]["summary"]
        lines.append(
            f"| {model_key} | {bridge['correct_using_removed_item']}/"
            f"{bridge['correct']} | {foreign_key['correct_using_removed_item']}/"
            f"{foreign_key['correct']} |"
        )

    lines.extend(
        [
            "",
            "## Gap relative to DeepSeek on common base-correct variants",
            "",
            "A positive gap means DeepSeek retains more base-correct cases.",
            "",
            "| Model | Family | Common variants | Common questions | Raw gap | Raw 95% CI | Compliant gap | Compliant 95% CI |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model_key in MODELS:
        if model_key == "api_control":
            continue
        for family in FAMILIES:
            comparison = result["models"][model_key]["families"][family][
                "comparison_to_api"
            ]
            ci = comparison["bootstrap"]
            interval = (
                "NA"
                if not ci
                else f"[{ci['lower_95_pp']:.2f}, {ci['upper_95_pp']:.2f}] pp"
            )
            compliant_interval = (
                "NA"
                if not ci or ci.get("compliant_lower_95_pp") is None
                else f"[{ci['compliant_lower_95_pp']:.2f}, "
                f"{ci['compliant_upper_95_pp']:.2f}] pp"
            )
            lines.append(
                f"| {model_key} | {family} | "
                f"{comparison['common_base_correct_variants']} | "
                f"{comparison['common_base_correct_questions']} | "
                f"{format_pp(comparison['gap_pp'])} | {interval} | "
                f"{format_pp(comparison['compliant_gap_pp'])} | "
                f"{compliant_interval} |"
            )

    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- Empty or invalid predictions are execution errors, not evaluation errors.",
            "- Gold evaluation failures are excluded from denominator calculations.",
            "- Accuracy intervals use question-clustered bootstrap, not independent rows.",
            "- Correct predictions that read a removed table or column are reported as",
            "  removed-item usage and are excluded from compliant accuracy.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    score_dir = (
        args.scores_dir.resolve()
        if args.scores_dir
        else root / "BIRD_RESULTS" / "scores" / "missing"
    )
    base_score_dir = (
        args.base_scores_dir.resolve()
        if args.base_scores_dir
        else root / "BIRD_RESULTS" / "scores" / "base"
    )
    variants_path = (
        args.variants.resolve()
        if args.variants
        else root / "perturbations" / "output" / "mini_dev_perturbations.jsonl"
    )
    analysis_dir = root / "BIRD_RESULTS" / "analysis"
    report_dir = root / "BIRD_RESULTS" / "reports"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    variants_by_id = {
        record["variant_id"]: record
        for record in read_jsonl(variants_path)
        if record["perturbation"]["family"] in FAMILIES
    }
    result: dict = {
        "method": {
            "bootstrap_replicates": args.bootstrap_replicates,
            "cluster_unit": "question_id",
            "schema_read_detection": "sqlite3 authorizer during EXPLAIN compilation",
        },
        "models": {},
    }

    all_model_records = {}
    for model_key in MODELS:
        scores = read_jsonl(score_dir / f"{model_key}.jsonl")
        base_scores = read_jsonl(base_score_dir / f"{model_key}.jsonl")
        if len(scores) != 597:
            raise ValueError(
                f"{model_key}: expected 597 scores, got {len(scores)}"
            )
        base_by_question = {record["question_id"]: record for record in base_scores}
        records_by_family = model_family_records(
            model_key,
            scores,
            variants_by_id,
            base_by_question,
            root,
        )
        all_model_records[model_key] = records_by_family
        result["models"][model_key] = {"families": {}}
        for family in FAMILIES:
            records = records_by_family[family]
            summary = summarize_records(records)
            bootstrap = clustered_bootstrap(
                records,
                args.bootstrap_replicates,
                bootstrap_rng(model_key, family),
            )
            result["models"][model_key]["families"][family] = {
                "summary": summary,
                "cluster_bootstrap": bootstrap,
            }

    for model_key in MODELS:
        if model_key == "api_control":
            continue
        for family in FAMILIES:
            comparison = common_base_comparison(
                all_model_records[model_key][family],
                all_model_records["api_control"][family],
                args.bootstrap_replicates,
                bootstrap_rng(f"{model_key}:vs_api", family),
            )
            result["models"][model_key]["families"][family][
                "comparison_to_api"
            ] = comparison

    json_path = analysis_dir / f"{args.output_prefix}_analysis.json"
    write_json(json_path, result)

    csv_path = analysis_dir / f"{args.output_prefix}_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(
            [
                "model",
                "family",
                "evaluated",
                "correct",
                "accuracy",
                "base_correct",
                "retention_on_base_correct",
                "removed_item_reads",
                "correct_using_removed_item",
                "compliant_correct",
                "compliant_accuracy",
            ]
        )
        for model_key in MODELS:
            for family in FAMILIES:
                summary = result["models"][model_key]["families"][family]["summary"]
                writer.writerow(
                    [
                        model_key,
                        family,
                        summary["evaluated"],
                        summary["correct"],
                        summary["accuracy"],
                        summary["base_correct"],
                        summary["retention_on_base_correct"],
                        summary["removed_item_reads"],
                        summary["correct_using_removed_item"],
                        summary["compliant_correct"],
                        summary["compliant_accuracy"],
                    ]
                )

    markdown_path = report_dir / f"{args.output_prefix.upper()}_RESULTS.md"
    markdown_path.write_text(build_markdown(result), encoding="utf-8")
    print(json_path)
    print(csv_path)
    print(markdown_path)


if __name__ == "__main__":
    main()
