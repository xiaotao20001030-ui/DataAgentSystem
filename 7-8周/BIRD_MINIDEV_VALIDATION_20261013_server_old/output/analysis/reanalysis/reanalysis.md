# BIRD Mini-Dev re-analysis

- control model: `api_control`
- models: api_control, qwen2_5_coder_1_5b, qwen3_0_6b, qwen3_1_7b, qwen3_4b
- score files: `BIRD_RESULTS/scores_official/combined`

## Gate (qid-aligned)

| model | family | n | small drop | control drop | diff | 95% CI | excludes +10pp |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| qwen2_5_coder_1_5b | add_random_20 | 500 | 4.20 | 6.40 | -2.20 | [-7.00, 2.60] | True |
| qwen2_5_coder_1_5b | add_synonym_20 | 500 | 12.80 | 40.60 | -27.80 | [-33.40, -22.40] | True |
| qwen3_0_6b | add_random_20 | 500 | 4.60 | 6.40 | -1.80 | [-5.80, 2.00] | True |
| qwen3_0_6b | add_synonym_20 | 500 | 9.40 | 40.60 | -31.20 | [-36.60, -26.00] | True |
| qwen3_1_7b | add_random_20 | 500 | 5.40 | 6.40 | -1.00 | [-5.40, 3.40] | True |
| qwen3_1_7b | add_synonym_20 | 500 | 15.80 | 40.60 | -24.80 | [-30.00, -19.60] | True |
| qwen3_4b | add_random_20 | 500 | 7.20 | 6.40 | 0.80 | [-3.60, 5.20] | True |
| qwen3_4b | add_synonym_20 | 500 | 32.40 | 40.60 | -8.20 | [-13.00, -3.40] | True |

## Baseline-correct extra failure

| model | family | n | extra failure | 95% CI |
| --- | --- | ---: | ---: | --- |
| qwen2_5_coder_1_5b | add_random_20 | 116 | 34.48 | [24.14, 44.83] |
| qwen2_5_coder_1_5b | add_synonym_20 | 116 | 10.34 | [0.00, 20.69] |
| qwen3_0_6b | add_random_20 | 69 | 31.88 | [18.84, 43.48] |
| qwen3_0_6b | add_synonym_20 | 69 | 36.23 | [24.64, 47.83] |
| qwen3_1_7b | add_random_20 | 127 | 25.98 | [17.32, 34.65] |
| qwen3_1_7b | add_synonym_20 | 127 | 14.17 | [6.30, 22.83] |
| qwen3_4b | add_random_20 | 229 | 12.23 | [6.55, 17.90] |
| qwen3_4b | add_synonym_20 | 229 | 6.11 | [1.31, 11.35] |

## Synonym stratification: same_name count

| model | bucket | n | accuracy |
| --- | ---: | ---: | ---: |
| api_control | 0 | 344 | 74.13 |
| api_control | 1 | 12 | 0.00 |
| api_control | 2 | 248 | 25.81 |
| api_control | 3 | 420 | 16.90 |
| api_control | 4 | 296 | 24.66 |
| api_control | 5 | 680 | 12.79 |
| qwen2_5_coder_1_5b | 0 | 344 | 40.70 |
| qwen2_5_coder_1_5b | 1 | 12 | 0.00 |
| qwen2_5_coder_1_5b | 2 | 248 | 17.34 |
| qwen2_5_coder_1_5b | 3 | 420 | 11.19 |
| qwen2_5_coder_1_5b | 4 | 296 | 17.91 |
| qwen2_5_coder_1_5b | 5 | 680 | 4.26 |
| qwen3_0_6b | 0 | 344 | 22.09 |
| qwen3_0_6b | 1 | 12 | 0.00 |
| qwen3_0_6b | 2 | 248 | 2.42 |
| qwen3_0_6b | 3 | 420 | 1.90 |
| qwen3_0_6b | 4 | 296 | 7.09 |
| qwen3_0_6b | 5 | 680 | 0.44 |
| qwen3_1_7b | 0 | 344 | 37.50 |
| qwen3_1_7b | 1 | 12 | 0.00 |
| qwen3_1_7b | 2 | 248 | 8.87 |
| qwen3_1_7b | 3 | 420 | 6.90 |
| qwen3_1_7b | 4 | 296 | 10.14 |
| qwen3_1_7b | 5 | 680 | 2.94 |
| qwen3_4b | 0 | 344 | 59.88 |
| qwen3_4b | 1 | 12 | 0.00 |
| qwen3_4b | 2 | 248 | 8.87 |
| qwen3_4b | 3 | 420 | 12.14 |
| qwen3_4b | 4 | 296 | 16.55 |
| qwen3_4b | 5 | 680 | 5.59 |

## Random stratification: new table count

| model | bucket | n | accuracy |
| --- | ---: | ---: | ---: |
| api_control | 0 | 55 | 50.91 |
| api_control | 1 | 346 | 52.60 |
| api_control | 2 | 371 | 66.31 |
| api_control | 3 | 307 | 61.56 |
| api_control | 4 | 273 | 63.37 |
| api_control | 5 | 648 | 70.68 |
| qwen2_5_coder_1_5b | 0 | 55 | 16.36 |
| qwen2_5_coder_1_5b | 1 | 346 | 13.87 |
| qwen2_5_coder_1_5b | 2 | 371 | 26.68 |
| qwen2_5_coder_1_5b | 3 | 307 | 27.69 |
| qwen2_5_coder_1_5b | 4 | 273 | 25.64 |
| qwen2_5_coder_1_5b | 5 | 648 | 21.60 |
| qwen3_0_6b | 0 | 55 | 0.00 |
| qwen3_0_6b | 1 | 346 | 3.76 |
| qwen3_0_6b | 2 | 371 | 13.21 |
| qwen3_0_6b | 3 | 307 | 7.82 |
| qwen3_0_6b | 4 | 273 | 17.22 |
| qwen3_0_6b | 5 | 648 | 12.65 |
| qwen3_1_7b | 0 | 55 | 5.45 |
| qwen3_1_7b | 1 | 346 | 7.80 |
| qwen3_1_7b | 2 | 371 | 24.26 |
| qwen3_1_7b | 3 | 307 | 23.78 |
| qwen3_1_7b | 4 | 273 | 27.84 |
| qwen3_1_7b | 5 | 648 | 27.01 |
| qwen3_4b | 0 | 55 | 29.09 |
| qwen3_4b | 1 | 346 | 26.01 |
| qwen3_4b | 2 | 371 | 50.40 |
| qwen3_4b | 3 | 307 | 47.88 |
| qwen3_4b | 4 | 273 | 46.15 |
| qwen3_4b | 5 | 648 | 48.46 |

## Real-synonym stratification: table placement

| model | bucket | n | accuracy |
| --- | --- | ---: | ---: |
| api_control | gold_tables_only | 4 | 25.00 |
| api_control | new_table | 423 | 63.36 |
| qwen2_5_coder_1_5b | gold_tables_only | 4 | 25.00 |
| qwen2_5_coder_1_5b | new_table | 423 | 22.93 |
| qwen3_0_6b | gold_tables_only | 4 | 0.00 |
| qwen3_0_6b | new_table | 423 | 12.06 |
| qwen3_1_7b | gold_tables_only | 4 | 0.00 |
| qwen3_1_7b | new_table | 423 | 24.11 |
| qwen3_4b | gold_tables_only | 4 | 25.00 |
| qwen3_4b | new_table | 423 | 40.90 |

## Retrieved schema vs base

| model | family | n | base acc | retrieved acc | drop | 95% CI |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| qwen2_5_coder_1_5b | - | 0 | - | - | - | - |
| qwen3_0_6b | - | 0 | - | - | - | - |
| qwen3_1_7b | - | 0 | - | - | - | - |
| qwen3_4b | - | 0 | - | - | - | - |
