# BIRD Mini-Dev re-analysis

- control model: `api_control`
- models: api_control, qwen2_5_coder_1_5b, qwen3_0_6b, qwen3_1_7b, qwen3_4b
- score files: `BIRD_RESULTS/scores_official_pure_column`

## Gate (qid-aligned)

| model | family | n | small drop | control drop | diff | 95% CI | excludes +10pp |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| qwen2_5_coder_1_5b | add_pure_column_20 | 500 | 0.60 | 4.40 | -3.80 | [-8.20, 0.40] | True |
| qwen3_0_6b | add_pure_column_20 | 500 | 5.00 | 4.40 | 0.60 | [-3.00, 4.20] | True |
| qwen3_1_7b | add_pure_column_20 | 500 | 9.00 | 4.40 | 4.60 | [0.20, 9.00] | True |
| qwen3_4b | add_pure_column_20 | 500 | 6.20 | 4.40 | 1.80 | [-2.40, 6.00] | True |

## Baseline-correct extra failure

| model | family | n | extra failure | 95% CI |
| --- | --- | ---: | ---: | --- |
| qwen2_5_coder_1_5b | add_pure_column_20 | 117 | 20.51 | [11.97, 29.06] |
| qwen3_0_6b | add_pure_column_20 | 68 | 32.35 | [20.59, 44.12] |
| qwen3_1_7b | add_pure_column_20 | 126 | 34.13 | [24.60, 43.65] |
| qwen3_4b | add_pure_column_20 | 230 | 10.00 | [4.78, 15.65] |

## Synonym stratification: same_name count

| model | bucket | n | accuracy |
| --- | ---: | ---: | ---: |

## Random stratification: new table count

| model | bucket | n | accuracy |
| --- | ---: | ---: | ---: |

## Real-synonym stratification: table placement

| model | bucket | n | accuracy |
| --- | --- | ---: | ---: |

## Retrieved schema vs base

| model | family | n | base acc | retrieved acc | drop | 95% CI |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| qwen2_5_coder_1_5b | - | 0 | - | - | - | - |
| qwen3_0_6b | - | 0 | - | - | - | - |
| qwen3_1_7b | - | 0 | - | - | - | - |
| qwen3_4b | - | 0 | - | - | - | - |
