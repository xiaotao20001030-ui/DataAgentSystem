# Re-analysis and follow-up experiments

The completed server outputs are mirrored locally under
`7-8周/BIRD_RESULTS/`:

- `predictions_pure_column/`: 5 models × 1,000 (base + pure 20)
- `scores_official_pure_column/`: official set-semantics scores
- `analysis/reanalysis/`: original-score re-analysis
- `analysis/reanalysis_pure_column/`: pure-column gate + baseline-correct
- `analysis/retrieval_matched_exact/`: exact original retrieval setup
- `analysis/retrieval_matched_exact_qe/`: question+evidence version
- `analysis/missing_compliance/`: authorizer compliance audit
- `logs/pure_column/`: generation/scoring logs

The server-side `perturbations/output/pure_column_5_10_20/` was also copied
over the local version so variant IDs and question IDs match the scores.

This directory contains the analyses added after the first BIRD Mini-Dev
report. They do not change the original report; they make the confounding
factors explicit and provide the smallest useful follow-up experiment.

## 1. Why the follow-up is needed

The original `add_random_*` condition was intended to add irrelevant columns
but actually added columns from arbitrary tables. The new prompt therefore
also contained new tables:

| condition | variants with a new table | added columns in new tables |
| --- | ---: | ---: |
| `add_random_5` | 467 / 500 | 63.8% |
| `add_random_20` | 494 / 500 | 58.9% |
| `add_random_50` | 496 / 500 | 51.2% |

The original `add_synonym_5` condition is also not purely lexical: 63.5% of
its added columns are `same_name` copies. The pure-column condition below
keeps the table set fixed and the pure-synonym condition removes `same_name`
columns.

## 2. Generate the pure-column condition

Default: 20 columns, gold tables only, no new tables.

```bash
cd /Users/xiaotao/PycharmProjects/DataAgentSystem/7-8周
../.venv/bin/python perturbations/generate_pure_column.py --levels 20
```

For a dose-response version with 5/10/20 columns:

```bash
../.venv/bin/python perturbations/generate_pure_column.py \
  --levels 5,10,20 \
  --output-dir perturbations/output/pure_column_5_10_20
```

For pure lexical synonyms (no `same_name`):

```bash
../.venv/bin/python perturbations/generate_pure_column.py \
  --levels 20 \
  --include-pure-synonym \
  --output-dir perturbations/output/pure_column_and_synonym
```

The generated records use `family=add_pure_column` or
`family=add_pure_synonym`; all added columns belong to tables that were
already in the gold schema. The validation report records how many added
columns are real vs synthetic fillers.

## 3. Run the follow-up on the GPU server

Set the API model in `mini_dev_data/model_eval/model_matrix.json` before
running `api_control`. Example loop:

```bash
cd /path/to/7-8周
PY=../.venv/bin/python
VARIANTS=perturbations/output/pure_column_5_10_20/mini_dev_pure_column.jsonl
OUT=outputs/pure_column

for MODEL in qwen3_0_6b qwen3_1_7b qwen3_4b qwen2_5_coder_1_5b api_control; do
  $PY mini_dev_data/model_eval/generate_predictions.py \
    --model-key "$MODEL" \
    --variants "$VARIANTS" \
    --families base,add_pure_column_20 \
    --output-dir "$OUT/predictions" \
    --local-files-only
  $PY mini_dev_data/model_eval/score_predictions.py \
    --predictions "$OUT/predictions/$MODEL.jsonl" \
    --variants "$VARIANTS" \
    --output-dir "$OUT/scores"
done
```

`api_control` must be called without `--local-files-only` and with
`OPENAI_API_KEY` (or `--api-key-env`) set. For pure synonyms, repeat with
`--families base,add_pure_synonym_20` and the corresponding variants file.

The scorer now defaults to BIRD official set semantics
(`set(predicted_rows) == set(gold_rows)`). Use `--comparison multiset` only
for the old, non-official behavior.

## 4. Gate the new condition

```bash
$PY mini_dev_data/model_eval/analyze_execution_gate.py \
  --scores-dir "$OUT/scores" \
  --families base,add_pure_column_20 \
  --output "$OUT/execution_gate_pure_column.json"
```

The patched gate aligns pairs by `question_id`, reports a proper
`p_one_sided_10pp`, and adds `excludes_10pp_gap` and
`passed_strict_10pp_ci`. The original `passed` field is kept for continuity.

## 5. Re-analyze the existing score files (no inference)

```bash
$PY analysis/reanalyze_execution.py \
  --scores-dir /path/to/BIRD_RESULTS/scores_official \
  --variants perturbations/output/mini_dev_perturbations.jsonl \
  --real-variants perturbations/output/real_synonym_sensitivity/mini_dev_add_real_synonym_20.jsonl \
  --output-dir analysis/reanalysis
```

This writes transition matrices, qid-aligned gate estimates, baseline-correct
extra-failure estimates, and synonym/random/real-synonym strata. The most
important output is the `same_name_count` stratification: if the 5-column
cliff is driven by `same_name` columns, the report should say so.

## 6. Retrieval matched baseline

```bash
$PY analysis/retrieval_matched_baseline.py \
  --top-k 5,10,20,50 \
  --output-dir analysis/retrieval_matched
```

The script uses `sentence-transformers/all-MiniLM-L6-v2`, question-only
queries, and `table.column` column documents by default. It adds
`multi_nonbridge` — gold columns in multi-table questions that are neither
bridge-table columns nor join/FK columns — and performs within-question
paired bootstrap comparisons.

The server-side run with the exact original document construction and label
sets (`analysis/retrieval_matched_exact/`) reproduces the original absolute
rates and adds the matched baseline:

| k | single target | multi non-bridge | bridge columns | FK/join columns |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 28.71% | 47.45% | 41.60% | 57.85% |

At k=10, the paired `bridge_cols - multi_nonbridge` difference is
**-13.91 pp** with 95% CI [-24.22, -3.69] pp; the
`fk_cols - multi_nonbridge` difference is **+13.75 pp** with 95% CI
[+9.79, +17.73] pp. In other words, the original +28.17 pp "bridge component"
effect is mostly multi-table difficulty plus a specific join/FK-column
penalty; bridge-table columns are actually easier than the matched baseline.

With question+evidence, the bridge-column difference is +2.15 pp
(95% CI [-7.96, +12.24], not significant), while the FK difference is
+26.11 pp (95% CI [+22.15, +30.16]). The bridge-table effect is not robust
across query modes; the FK/join effect is.

## 7. Optional RQ3 condition: retrieved schema

```bash
$PY perturbations/generate_retrieved_schema.py --k 10
```

This builds `base` plus `retrieved_schema` variants whose prompt schema is
the top-10 retrieved columns (grouped by table), not the gold schema. Run the
five models with `--families base,retrieved_schema_10`, score, and use
`analysis/reanalyze_execution.py`; its `Retrieved schema vs base` section
compares per-question execution. This is the condition that actually links
retrieval misses to execution failures; the original oracle-schema
experiments cannot identify that link.

## 8. Audit missing-schema compliance

```bash
$PY analysis/audit_missing_schema.py   --scores-dir /path/to/BIRD_RESULTS/scores_official   --variants perturbations/output/mini_dev_perturbations.jsonl
```

This re-runs SQLite's authorizer on the saved predictions and separates
strict compliance from non-`SELECT *` compliance. It also counts evidence
mentions of removed names, so an apparent "recovery" that came from the
evidence field is visible.

## 9. Pure-column result (server, completed)

`add_pure_column_20` was run for all five models on the server. The
qid-aligned gate still fails (drop difference vs DeepSeek): Qwen3-0.6B
+0.60pp [-3.00, +4.20], Qwen3-1.7B +4.60pp [+0.20, +9.00], Qwen3-4B
+1.80pp [-2.40, +6.00], Qwen2.5-Coder -3.80pp [-8.20, +0.40]. All 95% CIs
exclude a +10pp gap. Baseline-correct extra failure remains positive:
+32.35, +34.13, +10.00, +20.51pp respectively. Results are in
`analysis/reanalysis_pure_column/`.

## 10. Spider sample-size warning

Using the BIRD base accuracies as a rough guide, the expected number of
questions both `Qwen3-0.6B` and DeepSeek answer correctly is about 7 in 50
questions and 19 in 135 questions, not 30. Even the 135-question set is
underpowered for the 0.6B model under a "30 common base-correct" rule. Either
drop 0.6B from the confirmatory gate, increase the question count, or use a
within-question design with more perturbations per question.
