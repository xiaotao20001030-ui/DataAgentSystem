#!/usr/bin/env python3
"""Compare plain schema retrieval with one-hop foreign-key expansion.

Runs one or more embedding models on the original BIRD Mini-Dev schema,
reports connection-component recall/miss rate and the rendered-schema token
budget for each top-k.  The expansion is intentionally minimal: it retains
the top-k retrieved columns and adds the opposite endpoint of every declared
foreign-key edge incident on them.
"""

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path(os.environ.get("BIRD_EXPERIMENT_ROOT", str(PROJECT_ROOT.parent))).expanduser()
DEFAULT_DATA_ROOT = Path(os.environ.get(
    "BIRD_DATA_ROOT", str(DEFAULT_ROOT.parent / "BIRD_MINIDEV_VALIDATION_20261013_server_old" / "data")
)).expanduser()
K_VALUES = (5, 10, 20, 50)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--models", nargs="+", default=[
        "sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-base-en-v1.5"
    ])
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output" / "retrieval_fk")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--tokenizer", type=Path, default=None,
                        help="Local generation-model tokenizer for exact schema-snippet token counts.")
    return parser.parse_args()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def data_root(root, explicit):
    if explicit:
        return explicit
    return DEFAULT_DATA_ROOT


def schema(metadata):
    docs, adjacency = {}, defaultdict(set)
    for database in metadata:
        by_index = {}
        names = database["table_names_original"]
        primary_keys = set()
        for primary_key in database["primary_keys"]:
            if isinstance(primary_key, (list, tuple)):
                primary_keys.update(primary_key)
            else:
                primary_keys.add(primary_key)
        per_db = []
        for index, (table_index, column) in enumerate(database["column_names_original"]):
            if table_index < 0:
                continue
            column_id = f"{names[table_index]}.{column}"
            by_index[index] = column_id
            key_text = "primary key" if index in primary_keys else ""
            per_db.append({"id": column_id, "text": (
                f"table {names[table_index]}; column {column}; "
                f"type {database['column_types'][index]}; {key_text}"
            ).strip()})
        for left, right in database["foreign_keys"]:
            if left in by_index and right in by_index:
                adjacency[(database["db_id"], by_index[left])].add(by_index[right])
                adjacency[(database["db_id"], by_index[right])].add(by_index[left])
        docs[database["db_id"]] = per_db
    return docs, adjacency


def labels(variants):
    output = defaultdict(set)
    for variant in variants:
        family = variant["perturbation"]["family"]
        if family == "missing_bridge_table":
            for removed in variant["perturbation"]["removed"]:
                output[variant["question_id"]].update(removed.get("columns", []))
        elif family == "missing_fk_column":
            for removed in variant["perturbation"]["removed"]:
                output[variant["question_id"]].update(removed.get("join_columns", []))
    return output


def category_labels(variants):
    output = defaultdict(lambda: {'bridge_tables': set(), 'bridge_columns': set(), 'fk_columns': set()})
    for variant in variants:
        label = output[variant['question_id']]
        family = variant['perturbation']['family']
        for removed in variant['perturbation'].get('removed', []):
            if family == 'missing_bridge_table':
                label['bridge_tables'].add(removed['id'])
                label['bridge_columns'].update(removed['columns'])
            elif family == 'missing_fk_column':
                label['fk_columns'].update(removed['join_columns'])
    return output


def gap_bootstrap(multi_events, single_events, seed, iterations):
    rng = np.random.default_rng(seed)
    multi = np.asarray(multi_events, dtype=float)
    single = np.asarray(single_events, dtype=float)
    values = np.empty(iterations)
    for start in range(0, iterations, 256):
        stop = min(iterations, start + 256)
        m = multi[rng.integers(0, len(multi), size=(stop-start, len(multi)))].sum(axis=1)
        s = single[rng.integers(0, len(single), size=(stop-start, len(single)))].sum(axis=1)
        values[start:stop] = m[:, 0] / m[:, 1] - s[:, 0] / s[:, 1]
    return {'difference_percentage_points': float((multi[:, 0].sum()/multi[:, 1].sum()-single[:, 0].sum()/single[:, 1].sum())*100),
            'ci95_low_percentage_points': float(np.quantile(values, .025)*100),
            'ci95_high_percentage_points': float(np.quantile(values, .975)*100),
            'bootstrap_iterations': iterations,
            'bootstrap_fraction_nonpositive': float(np.mean(values <= 0))}


def original_hypothesis(predictions, seed, iterations):
    metrics = {}
    for k in K_VALUES:
        events = defaultdict(list)
        for prediction in predictions:
            selected = set(prediction['top_columns'][:k])
            gold = set(prediction['gold_columns'])
            if prediction['question_type'] == 'single' and gold:
                events['single_target_columns'].append((len(gold-selected), len(gold)))
            for source, metric in [('bridge_columns','bridge_table_columns'), ('fk_columns','foreign_key_columns')]:
                targets = set(prediction[source])
                if targets:
                    events[metric].append((len(targets-selected), len(targets)))
        metric = {}
        for name, event in events.items():
            misses, total = np.asarray(event).sum(axis=0)
            metric[name] = {'misses': int(misses), 'total': int(total), 'miss_rate': float(misses/total), 'question_count': len(event)}
        metric['foreign_key_columns_vs_single'] = gap_bootstrap(events['foreign_key_columns'], events['single_target_columns'], seed+k, iterations)
        metrics[str(k)] = metric
    return metrics


def count_tokens(columns, tokenizer):
    text = "\n".join(item["text"] for item in sorted(columns, key=lambda item: item["id"].lower()))
    if tokenizer is None:
        return len(text.split())
    return len(tokenizer.encode(text, add_special_tokens=False))


def summarize(rows, mode, k):
    hits = total = tokens = 0
    for row in rows:
        selected = row[mode][k]
        hits += len(selected & row["targets"])
        total += len(row["targets"])
        tokens += row[f"{mode}_tokens"][k]
    recall = hits / total if total else 0
    return {"target_columns": total, "hits": hits, "recall": recall,
            "miss_rate": 1 - recall, "mean_schema_token_proxy": tokens / len(rows)}


def paired_improvement_ci(rows, k, seed=20261026, iterations=10000):
    plain_hits = np.array([len(row["plain"][k] & row["targets"]) for row in rows])
    expanded_hits = np.array([len(row["expanded"][k] & row["targets"]) for row in rows])
    totals = np.array([len(row["targets"]) for row in rows])
    rng = np.random.default_rng(seed)
    sample_indices = rng.integers(0, len(rows), size=(iterations, len(rows)))
    improvements = ((expanded_hits[sample_indices] - plain_hits[sample_indices]).sum(axis=1)
                    / totals[sample_indices].sum(axis=1))
    return {
        "miss_rate_reduction_percentage_points":
            (expanded_hits.sum() - plain_hits.sum()) / totals.sum() * 100,
        "ci95_low_percentage_points": float(np.quantile(improvements, 0.025) * 100),
        "ci95_high_percentage_points": float(np.quantile(improvements, 0.975) * 100),
        "question_cluster_bootstrap_iterations": iterations,
    }


def main():
    args = parse_args()
    from sentence_transformers import SentenceTransformer
    root, droot, output = args.experiment_root.resolve(), data_root(args.experiment_root.resolve(), args.data_root), args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    questions = json.loads((droot / "mini_dev_sqlite.json").read_text(encoding="utf-8"))[:500]
    variants = read_jsonl(root / "perturbations/output/mini_dev_perturbations.jsonl")
    targets = labels(variants)
    docs_by_db, adjacency = schema(json.loads((droot / "dev_tables.json").read_text(encoding="utf-8")))
    structures = {record['question_id']: record for record in read_jsonl(root / 'perturbations/output/question_structures.jsonl')}
    categorized = category_labels(variants)
    tokenizer = None
    if args.tokenizer:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), local_files_only=True)
    all_summaries = {}
    for model_name in args.models:
        model = SentenceTransformer(model_name, device=args.device, local_files_only=True)
        document_embeddings = {
            db_id: model.encode([document["text"] for document in documents],
                                batch_size=args.batch_size, normalize_embeddings=True,
                                show_progress_bar=False)
            for db_id, documents in docs_by_db.items()
        }
        # BGE's model card recommends this query instruction for retrieval.
        instruction = "Represent this sentence for searching relevant passages: " if "bge-base-en-v1.5" in model_name.lower() else ""
        query_embeddings = model.encode(
            [instruction + question["question"] for question in questions],
            batch_size=args.batch_size, normalize_embeddings=True,
            show_progress_bar=False,
        )
        rows = []
        predictions = []
        for question, q_embedding in zip(questions, query_embeddings):
            docs = docs_by_db[question["db_id"]]
            ranked = np.argsort(-(document_embeddings[question["db_id"]] @ q_embedding))
            structure = structures[question['question_id']]
            predictions.append({
                'question_id': question['question_id'], 'db_id': question['db_id'],
                'question_type': structure['question_type'], 'question': question['question'],
                'gold_columns': structure['gold_columns'],
                **{name: sorted(value) for name, value in categorized[question['question_id']].items()},
                'top_columns': [docs[index]['id'] for index in ranked[:max(K_VALUES)]],
                'top_scores': [float(document_embeddings[question['db_id']][index] @ q_embedding) for index in ranked[:max(K_VALUES)]],
            })
            if not targets[question['question_id']]:
                continue
            row = {"question_id": question["question_id"], "db_id": question["db_id"],
                   "targets": set(targets[question["question_id"]]), "plain": {}, "expanded": {},
                   "plain_tokens": {}, "expanded_tokens": {}}
            by_id = {item["id"]: item for item in docs}
            for k in K_VALUES:
                plain = {docs[index]["id"] for index in ranked[:k]}
                expanded = set(plain)
                for column in plain:
                    expanded.update(adjacency[(question["db_id"], column)])
                row["plain"][k], row["expanded"][k] = plain, expanded
                row["plain_tokens"][k] = count_tokens([by_id[item] for item in plain], tokenizer)
                row["expanded_tokens"][k] = count_tokens([by_id[item] for item in expanded], tokenizer)
            rows.append(row)
        all_summaries[model_name] = {
            "query_instruction": instruction,
            "question_count": len(rows),
            "schema_tokenizer": str(args.tokenizer) if tokenizer else "whitespace proxy",
            "top10_paired_improvement": paired_improvement_ci(rows, 10, args.seed, args.iterations),
            "original_hypothesis": original_hypothesis(predictions, args.seed, args.iterations),
            **{mode: {str(k): summarize(rows, mode, k) for k in K_VALUES}
               for mode in ("plain", "expanded")},
        }
        model_label = Path(model_name).name
        (output / f'{model_label}_predictions.jsonl').write_text(
            '\n'.join(json.dumps(prediction, ensure_ascii=False) for prediction in predictions)+'\n', encoding='utf-8')
        (output / 'fk_expansion_summary.json').write_text(json.dumps(all_summaries, indent=2)+'\n', encoding='utf-8')
    (output / "fk_expansion_summary.json").write_text(json.dumps(all_summaries, indent=2) + "\n", encoding="utf-8")
    lines = ["# One-hop FK expansion vs plain retrieval", "",
             f"Schema token count uses: {args.tokenizer if tokenizer else 'whitespace proxy'}.", ""]
    for model, summary in all_summaries.items():
        model_label = "BGE base en v1.5" if "bge-base-en-v1.5" in model.lower() else "all-MiniLM-L6-v2"
        ci = summary["top10_paired_improvement"]
        lines += [f"## {model_label}", "", f"Questions: {summary['question_count']}; query instruction: `{summary['query_instruction']}`.",
                  f"At k=10, one-hop FK expansion reduces miss rate by {ci['miss_rate_reduction_percentage_points']:.2f} pp "
                  f"(question-cluster bootstrap 95% CI [{ci['ci95_low_percentage_points']:.2f}, {ci['ci95_high_percentage_points']:.2f}] pp).",
                  "", "| k | plain miss | expanded miss | delta | plain tokens | expanded tokens |", "| ---: | ---: | ---: | ---: | ---: | ---: |"]
        for k in K_VALUES:
            plain, expanded = summary["plain"][str(k)], summary["expanded"][str(k)]
            lines.append(f"| {k} | {plain['miss_rate']:.2%} | {expanded['miss_rate']:.2%} | {(expanded['miss_rate']-plain['miss_rate']):+.2%} | {plain['mean_schema_token_proxy']:.1f} | {expanded['mean_schema_token_proxy']:.1f} |")
        lines.append("")
    (output / "fk_expansion_report.md").write_text("\n".join(lines), encoding="utf-8")
    hypothesis_lines = ['# 外键列对单表列：MiniLM / BGE 原假设对照', '',
                        '| 检索器 | k | 单表目标列漏选率 | 外键/连接列漏选率 | 差值 | 按题聚类 bootstrap 95% CI |',
                        '| --- | ---: | ---: | ---: | ---: | --- |']
    for model_name, summary in all_summaries.items():
        for k in K_VALUES:
            metric = summary['original_hypothesis'][str(k)]
            gap = metric['foreign_key_columns_vs_single']
            hypothesis_lines.append(f"| {Path(model_name).name} | {k} | {metric['single_target_columns']['miss_rate']:.2%} | {metric['foreign_key_columns']['miss_rate']:.2%} | {gap['difference_percentage_points']:+.2f} pp | [{gap['ci95_low_percentage_points']:+.2f}, {gap['ci95_high_percentage_points']:+.2f}] pp |")
    hypothesis_lines += ['', '原始单表对照与历史 matched-baseline 对照使用不同问题群体，不能把两种差值混为一谈。',
                         'BGE 使用推荐检索查询指令；任务信息仅来自 question。检索文档、候选列和标签与 MiniLM 相同。', '']
    (output / 'original_hypothesis_report.md').write_text('\n'.join(hypothesis_lines), encoding='utf-8')
    # Show both individual curves and the direct miss-rate/token trade-off.
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(len(all_summaries), 3, figsize=(15, 4 * len(all_summaries)), squeeze=False)
    for row_index, (model, summary) in enumerate(all_summaries.items()):
        model_label = "BGE base en v1.5" if "bge-base-en-v1.5" in model.lower() else "all-MiniLM-L6-v2"
        ks = list(K_VALUES)
        for mode, label, color in (("plain", "plain top-k", "#4C78A8"), ("expanded", "top-k + FK 1-hop", "#F58518")):
            axes[row_index, 0].plot(ks, [summary[mode][str(k)]["miss_rate"] * 100 for k in ks], marker="o", label=label, color=color)
            axes[row_index, 1].plot(ks, [summary[mode][str(k)]["mean_schema_token_proxy"] for k in ks], marker="o", label=label, color=color)
            tokens = [summary[mode][str(k)]["mean_schema_token_proxy"] for k in ks]
            misses = [summary[mode][str(k)]["miss_rate"] * 100 for k in ks]
            axes[row_index, 2].plot(tokens, misses, marker="o", label=label, color=color)
            for k, token, miss in zip(ks, tokens, misses):
                axes[row_index, 2].annotate(f"k={k}", (token, miss), xytext=(3, 4),
                                            textcoords="offset points", fontsize=7)
        axes[row_index, 0].set_title(f"{model_label}: connection-component miss rate")
        axes[row_index, 0].set_xlabel("initial top-k")
        axes[row_index, 0].set_ylabel("miss rate (%)")
        axes[row_index, 1].set_title(f"{model_label}: schema length")
        axes[row_index, 1].set_xlabel("initial top-k")
        axes[row_index, 1].set_ylabel("schema tokens" if tokenizer else "whitespace token proxy")
        axes[row_index, 2].set_title(f"{model_label}: miss rate vs schema length")
        axes[row_index, 2].set_xlabel("mean schema tokens" if tokenizer else "mean whitespace token proxy")
        axes[row_index, 2].set_ylabel("miss rate (%)")
        for axis in axes[row_index]:
            axis.grid(alpha=0.25)
            axis.legend()
    figure.tight_layout()
    figure.savefig(output / "fk_expansion_tradeoff.png", dpi=180)
    plt.close(figure)


if __name__ == "__main__":
    main()
