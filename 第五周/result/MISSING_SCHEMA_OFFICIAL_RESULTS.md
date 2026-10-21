# BIRD Missing-Schema Perturbation Results

This analysis evaluates the two missing-schema conditions required by the
validation experiment. Reported accuracy is execution accuracy. Compliant
accuracy additionally requires that the predicted SQL does not read any
table or column removed from the supplied schema.

## Raw and compliant results

| Model | Family | Correct | Accuracy | Base-correct retention | Compliant correct | Compliant accuracy |
|---|---|---:|---:|---:|---:|---:|
| qwen3_0_6b | missing_bridge_table | 0/103 | 0.00% | 0.00% | 0/14 | 0.00% |
| qwen3_0_6b | missing_fk_column | 8/494 | 1.62% | 12.20% | 2/80 | 2.50% |
| qwen3_1_7b | missing_bridge_table | 3/103 | 2.91% | 10.00% | 3/27 | 11.11% |
| qwen3_1_7b | missing_fk_column | 37/494 | 7.49% | 25.66% | 6/157 | 3.82% |
| qwen3_4b | missing_bridge_table | 3/103 | 2.91% | 6.38% | 3/53 | 5.66% |
| qwen3_4b | missing_fk_column | 100/494 | 20.24% | 38.66% | 8/332 | 2.41% |
| qwen2_5_coder_1_5b | missing_bridge_table | 2/103 | 1.94% | 14.29% | 2/22 | 9.09% |
| qwen2_5_coder_1_5b | missing_fk_column | 50/494 | 10.12% | 50.54% | 2/159 | 1.26% |
| api_control | missing_bridge_table | 20/103 | 19.42% | 28.36% | 9/81 | 11.11% |
| api_control | missing_fk_column | 173/494 | 35.02% | 50.92% | 11/446 | 2.47% |

## Correct predictions that still read removed schema items

| Model | Bridge table | Foreign-key column |
|---|---:|---:|
| qwen3_0_6b | 0/0 | 6/8 |
| qwen3_1_7b | 0/3 | 31/37 |
| qwen3_4b | 0/3 | 92/100 |
| qwen2_5_coder_1_5b | 0/2 | 48/50 |
| api_control | 11/20 | 162/173 |

## Gap relative to DeepSeek on common base-correct variants

A positive gap means DeepSeek retains more base-correct cases.

| Model | Family | Common variants | Common questions | Raw gap | Raw 95% CI | Compliant gap | Compliant 95% CI |
|---|---|---:|---:|---:|---:|---:|---:|
| qwen3_0_6b | missing_bridge_table | 2 | 2 | +50.00 pp | [0.00, 100.00] pp | +0.00 pp | [0.00, 0.00] pp |
| qwen3_0_6b | missing_fk_column | 39 | 37 | +58.97 pp | [43.90, 73.17] pp | +0.00 pp | [0.00, 0.00] pp |
| qwen3_1_7b | missing_bridge_table | 17 | 15 | +11.76 pp | [0.00, 31.25] pp | +0.00 pp | [0.00, 0.00] pp |
| qwen3_1_7b | missing_fk_column | 104 | 87 | +39.42 pp | [27.72, 50.94] pp | +0.00 pp | [-6.25, 6.25] pp |
| qwen3_4b | missing_bridge_table | 43 | 37 | +13.95 pp | [4.55, 25.58] pp | +4.17 pp | [0.00, 13.64] pp |
| qwen3_4b | missing_fk_column | 214 | 171 | +11.21 pp | [2.80, 19.53] pp | +0.65 pp | [-1.35, 2.78] pp |
| qwen2_5_coder_1_5b | missing_bridge_table | 5 | 5 | +20.00 pp | [0.00, 60.00] pp | +0.00 pp | [0.00, 0.00] pp |
| qwen2_5_coder_1_5b | missing_fk_column | 81 | 76 | +0.00 pp | [-12.50, 12.66] pp | +0.00 pp | [0.00, 0.00] pp |

## Interpretation guardrails

- Empty or invalid predictions are execution errors, not evaluation errors.
- Gold evaluation failures are excluded from denominator calculations.
- Accuracy intervals use question-clustered bootstrap, not independent rows.
- Correct predictions that read a removed table or column are reported as
  removed-item usage and are excluded from compliant accuracy.
