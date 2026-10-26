#!/usr/bin/env python3
"""Evaluate whether vector retrieval misses bridge schema components."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


K_VALUES = (5, 10, 20, 50)
PRIMARY_K = 10
BOOTSTRAP_ITERATIONS = 10000


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=project_root / "mini_dev_data",
    )
    parser.add_argument(
        "--perturbation-root",
        type=Path,
        default=project_root / "perturbations" / "output",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "retrieval" / "output",
    )
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument(
        "--include-evidence",
        action="store_true",
        help="Append the BIRD evidence field to the retrieval query.",
    )
    return parser.parse_args()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def build_schema_documents(metadata):
    documents_by_db = {}
    for database in metadata:
        table_names = database["table_names_original"]
        primary_keys = set()
        for primary_key in database["primary_keys"]:
            if isinstance(primary_key, (list, tuple)):
                primary_keys.update(primary_key)
            else:
                primary_keys.add(primary_key)

        documents = []
        for index, (table_index, column_name) in enumerate(
            database["column_names_original"]
        ):
            if table_index < 0:
                continue
            table_name = table_names[table_index]
            column_id = f"{table_name}.{column_name}"
            key_text = "primary key" if index in primary_keys else ""
            documents.append(
                {
                    "column_id": column_id,
                    "text": (
                        f"table {table_name}; column {column_name}; "
                        f"type {database['column_types'][index]}; {key_text}"
                    ).strip(),
                }
            )
        documents_by_db[database["db_id"]] = documents
    return documents_by_db


def build_label_sets(perturbations):
    labels = defaultdict(
        lambda: {
            "bridge_tables": set(),
            "bridge_table_columns": set(),
            "fk_columns": set(),
        }
    )
    for record in perturbations:
        perturbation = record["perturbation"]
        question_id = record["question_id"]
        if perturbation["family"] == "missing_bridge_table":
            for removed in perturbation["removed"]:
                labels[question_id]["bridge_tables"].add(removed["id"])
                labels[question_id]["bridge_table_columns"].update(
                    removed["columns"]
                )
        elif perturbation["family"] == "missing_fk_column":
            for removed in perturbation["removed"]:
                labels[question_id]["fk_columns"].update(
                    removed["join_columns"]
                )
    return labels


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def aggregate_events(question_events):
    numerator = sum(event["hits"] for event in question_events)
    denominator = sum(event["total"] for event in question_events)
    return {
        "hits": numerator,
        "total": denominator,
        "misses": denominator - numerator,
        "miss_rate": ratio(denominator - numerator, denominator),
    }


def bootstrap_gap(multi_events, single_events, iterations, seed):
    if not multi_events or not single_events:
        return {
            "difference": None,
            "ci95_low": None,
            "ci95_high": None,
            "p_one_sided": None,
            "iterations": iterations,
        }

    rng = np.random.default_rng(seed)
    differences = np.empty(iterations, dtype=float)
    for iteration in range(iterations):
        multi_sample = rng.integers(0, len(multi_events), size=len(multi_events))
        single_sample = rng.integers(
            0, len(single_events), size=len(single_events)
        )

        multi_hits = sum(multi_events[index]["hits"] for index in multi_sample)
        multi_total = sum(multi_events[index]["total"] for index in multi_sample)
        single_hits = sum(
            single_events[index]["hits"] for index in single_sample
        )
        single_total = sum(
            single_events[index]["total"] for index in single_sample
        )
        differences[iteration] = (
            (multi_total - multi_hits) / multi_total
            - (single_total - single_hits) / single_total
        )

    observed_multi = aggregate_events(multi_events)["miss_rate"]
    observed_single = aggregate_events(single_events)["miss_rate"]
    observed = observed_multi - observed_single
    return {
        "difference": observed,
        "difference_percentage_points": observed * 100,
        "ci95_low": float(np.quantile(differences, 0.025)),
        "ci95_high": float(np.quantile(differences, 0.975)),
        "ci95_low_percentage_points": float(
            np.quantile(differences, 0.025) * 100
        ),
        "ci95_high_percentage_points": float(
            np.quantile(differences, 0.975) * 100
        ),
        "p_one_sided": float(
            (np.count_nonzero(differences <= 0) + 1) / (iterations + 1)
        ),
        "iterations": iterations,
    }


def make_events(predictions, question_type, label_key, k):
    events = []
    for prediction in predictions:
        if prediction["question_type"] != question_type:
            continue
        selected = set(prediction["top_columns"][:k])
        if label_key == "bridge_tables":
            candidates = prediction["bridge_tables"]
            if not candidates:
                continue
            hits = sum(
                any(
                    column_id.split(".", 1)[0] == table
                    for column_id in selected
                )
                for table in candidates
            )
            events.append(
                {
                    "question_id": prediction["question_id"],
                    "hits": hits,
                    "total": len(candidates),
                }
            )
        else:
            candidates = prediction[label_key]
            if not candidates:
                continue
            events.append(
                {
                    "question_id": prediction["question_id"],
                    "hits": len(set(candidates) & selected),
                    "total": len(set(candidates)),
                }
            )
    return events


def evaluate_predictions(predictions, seed):
    metrics = {}
    for k in K_VALUES:
        single_columns = make_events(predictions, "single", "gold_columns", k)
        bridge_tables = make_events(predictions, "multi", "bridge_tables", k)
        bridge_columns = make_events(
            predictions, "multi", "bridge_table_columns", k
        )
        fk_columns = make_events(predictions, "multi", "fk_columns", k)

        combined_multi_events = []
        for prediction in predictions:
            if prediction["question_type"] != "multi":
                continue
            selected = set(prediction["top_columns"][:k])
            candidates = set(prediction["bridge_table_columns"]) | set(
                prediction["fk_columns"]
            )
            if candidates:
                combined_multi_events.append(
                    {
                        "question_id": prediction["question_id"],
                        "hits": len(candidates & selected),
                        "total": len(candidates),
                    }
                )

        metrics[str(k)] = {
            "single_target_columns": aggregate_events(single_columns),
            "bridge_tables": aggregate_events(bridge_tables),
            "bridge_table_columns": aggregate_events(bridge_columns),
            "foreign_key_columns": aggregate_events(fk_columns),
            "bridge_components": aggregate_events(combined_multi_events),
            "gaps": {
                "bridge_tables_vs_single": bootstrap_gap(
                    bridge_tables,
                    single_columns,
                    BOOTSTRAP_ITERATIONS,
                    seed + k,
                ),
                "bridge_table_columns_vs_single": bootstrap_gap(
                    bridge_columns,
                    single_columns,
                    BOOTSTRAP_ITERATIONS,
                    seed + k + 50,
                ),
                "foreign_key_columns_vs_single": bootstrap_gap(
                    fk_columns,
                    single_columns,
                    BOOTSTRAP_ITERATIONS,
                    seed + k + 100,
                ),
                "bridge_components_vs_single": bootstrap_gap(
                    combined_multi_events,
                    single_columns,
                    BOOTSTRAP_ITERATIONS,
                    seed + k + 200,
                ),
            },
        }
    return metrics


def render_report(summary, query_mode):
    primary = summary["metrics"][str(PRIMARY_K)]
    single = primary["single_target_columns"]
    bridge_tables = primary["bridge_tables"]
    fk_columns = primary["foreign_key_columns"]
    components = primary["bridge_components"]
    bridge_columns = primary["bridge_table_columns"]
    bridge_columns_gap = primary["gaps"][
        "bridge_table_columns_vs_single"
    ]
    components_gap = primary["gaps"]["bridge_components_vs_single"]
    retrieval_gate = (
        components_gap["ci95_low"] is not None
        and components_gap["ci95_low"] > 0
        and components_gap["p_one_sided"] < 0.05
    )

    lines = [
        "# BIRD Mini-Dev 向量检索桥接成分漏选分析",
        "",
        f"- 向量模型：`{summary['embedding_model']}`",
        f"- 设备：`{summary['device']}`",
        f"- 检索文本：`{query_mode}`",
        f"- 主分析 k：{PRIMARY_K}",
        f"- Bootstrap：{BOOTSTRAP_ITERATIONS} 次，按问题聚类",
        "",
        f"## k={PRIMARY_K} 结果",
        "",
        "| 指标 | 漏选数 | 总数 | 漏选率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    rows = [
        ("单表目标列", single),
        ("桥接表", bridge_tables),
        ("桥接表内列", bridge_columns),
        ("外键/关键连接列", fk_columns),
        ("桥接成分并集", components),
    ]
    for name, value in rows:
        lines.append(
            f"| {name} | {value['misses']} | {value['total']} | "
            f"{value['miss_rate'] * 100:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## 与单表目标列的差距",
            "",
            "| 对比 | 差值 | 95% CI | 单侧 p |",
            "| --- | ---: | --- | ---: |",
        ]
    )
    for name, key in [
        ("桥接表 - 单表目标列", "bridge_tables_vs_single"),
        (
            "桥接表内列 - 单表目标列",
            "bridge_table_columns_vs_single",
        ),
        ("外键列 - 单表目标列", "foreign_key_columns_vs_single"),
        ("桥接成分并集 - 单表目标列", "bridge_components_vs_single"),
    ]:
        gap = primary["gaps"][key]
        lines.append(
            f"| {name} | {gap['difference_percentage_points']:+.2f} pp | "
            f"[{gap['ci95_low_percentage_points']:+.2f}, "
            f"{gap['ci95_high_percentage_points']:+.2f}] pp | "
            f"{gap['p_one_sided']:.4f} |"
        )

    lines.extend(["", "## Top-k 曲线", ""])
    lines.append(
        "| k | 单表目标列 | 桥接表 | 桥接表内列 | 外键列 | 桥接成分并集 |"
    )
    lines.append("| ---: | ---: | ---: | ---: | ---: | ---: |")
    for k in K_VALUES:
        metric = summary["metrics"][str(k)]
        lines.append(
            f"| {k} | "
            f"{metric['single_target_columns']['miss_rate'] * 100:.2f}% | "
            f"{metric['bridge_tables']['miss_rate'] * 100:.2f}% | "
            f"{metric['bridge_table_columns']['miss_rate'] * 100:.2f}% | "
            f"{metric['foreign_key_columns']['miss_rate'] * 100:.2f}% | "
            f"{metric['bridge_components']['miss_rate'] * 100:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## 判定",
            "",
            f"- 桥接成分显著高于单表目标列："
            f"**{'是' if retrieval_gate else '否'}**",
            f"- 桥接表内列差距："
            f"**{bridge_columns_gap['difference_percentage_points']:+.2f} pp**；"
            f"95% CI [{bridge_columns_gap['ci95_low_percentage_points']:+.2f}, "
            f"{bridge_columns_gap['ci95_high_percentage_points']:+.2f}] pp。",
            "- 判定标准：主 k 下差值 95% CI 下界 > 0，且单侧 p < 0.05。",
            "",
            "注意：桥接表是表级覆盖率；桥接表内列、外键列和单表目标列"
            "均为列级覆盖率。桥接成分并集将桥接表列与关键连接列合并后"
            "按列级统计。",
        ]
    )
    return "\n".join(lines) + "\n", retrieval_gate


def main():
    args = parse_args()
    data_root = args.data_root.resolve()
    perturbation_root = args.perturbation_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    questions = json.loads(
        (data_root / "mini_dev_sqlite.json").read_text(encoding="utf-8")
    )[:500]
    metadata = json.loads(
        (data_root / "dev_tables.json").read_text(encoding="utf-8")
    )
    structures = read_jsonl(perturbation_root / "question_structures.jsonl")
    perturbations = read_jsonl(
        perturbation_root / "mini_dev_perturbations.jsonl"
    )
    structure_by_id = {item["question_id"]: item for item in structures}
    labels = build_label_sets(perturbations)
    documents_by_db = build_schema_documents(metadata)

    model = SentenceTransformer(
        args.model,
        device=args.device,
        local_files_only=True,
    )
    document_embeddings = {}
    for db_id, documents in documents_by_db.items():
        document_embeddings[db_id] = model.encode(
            [document["text"] for document in documents],
            batch_size=args.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    query_mode = "question+evidence" if args.include_evidence else "question"
    query_texts = []
    for item in questions:
        query = item["question"]
        if args.include_evidence and item.get("evidence"):
            query = f"{query}\nEvidence: {item['evidence']}"
        query_texts.append(query)
    query_embeddings = model.encode(
        query_texts,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    predictions = []
    for item, query_embedding in zip(questions, query_embeddings):
        documents = documents_by_db[item["db_id"]]
        scores = document_embeddings[item["db_id"]] @ query_embedding
        top_indices = np.argsort(-scores)[: max(K_VALUES)]
        structure = structure_by_id[item["question_id"]]
        label = labels[item["question_id"]]
        predictions.append(
            {
                "question_id": item["question_id"],
                "db_id": item["db_id"],
                "question_type": structure["question_type"],
                "question": item["question"],
                "gold_columns": structure["gold_columns"],
                "bridge_tables": sorted(label["bridge_tables"]),
                "bridge_table_columns": sorted(
                    label["bridge_table_columns"]
                ),
                "fk_columns": sorted(label["fk_columns"]),
                "top_columns": [
                    documents[index]["column_id"] for index in top_indices
                ],
                "top_scores": [
                    float(scores[index]) for index in top_indices
                ],
            }
        )

    metrics = evaluate_predictions(predictions, args.seed)
    summary = {
        "dataset": "BIRD Mini-Dev SQLite",
        "question_count": len(questions),
        "embedding_model": args.model,
        "device": args.device,
        "query_mode": query_mode,
        "k_values": list(K_VALUES),
        "primary_k": PRIMARY_K,
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "seed": args.seed,
        "metrics": metrics,
    }
    report, retrieval_gate = render_report(summary, query_mode)
    summary["retrieval_gate_passed"] = retrieval_gate
    primary_gaps = metrics[str(PRIMARY_K)]["gaps"]
    summary["retrieval_gate_details"] = {
        "primary_metric": "bridge_components_vs_single",
        "bridge_table_columns_gap": primary_gaps[
            "bridge_table_columns_vs_single"
        ],
        "foreign_key_columns_gap": primary_gaps[
            "foreign_key_columns_vs_single"
        ],
        "bridge_components_gap": primary_gaps[
            "bridge_components_vs_single"
        ],
    }

    predictions_path = output_dir / f"retrieval_predictions_{query_mode}.jsonl"
    with predictions_path.open("w", encoding="utf-8") as output:
        for prediction in predictions:
            output.write(
                json.dumps(
                    prediction,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            output.write("\n")

    summary_path = output_dir / f"retrieval_summary_{query_mode}.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"retrieval_report_{query_mode}.md").write_text(
        report,
        encoding="utf-8",
    )
    print(report)


if __name__ == "__main__":
    main()
