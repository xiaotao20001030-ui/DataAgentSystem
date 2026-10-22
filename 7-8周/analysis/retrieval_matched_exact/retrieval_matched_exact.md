# Retrieval matched-baseline re-analysis (exact original setup)

- model: `/root/fsas/home/xiaotao/xiaotao/models/all-MiniLM-L6-v2`
- query: `question`
- questions: 500

## Miss rates

| k | single | multi_all | multi_nonbridge | bridge_cols | fk_cols | union | bridge_tables |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 41.63% | 66.78% | 60.91% | 67.60% | 74.77% | 73.93% | 38.83% |
| 10 | 28.71% | 51.70% | 47.45% | 41.60% | 57.85% | 56.88% | 16.50% |
| 20 | 17.22% | 34.92% | 31.61% | 22.80% | 39.69% | 38.95% | 1.94% |
| 50 | 8.61% | 14.86% | 13.46% | 6.00% | 17.13% | 16.57% | 0.00% |

## Paired within-question differences

| k | comparison | n questions | diff | 95% CI |
| ---: | --- | ---: | ---: | --- |
| 5 | bridge_cols_minus_multi_nonbridge | 90 | 2.74 pp | [-7.43, 13.04] pp |
| 5 | fk_cols_minus_multi_nonbridge | 390 | 15.84 pp | [12.03, 19.63] pp |
| 5 | union_minus_multi_nonbridge | 390 | 15.26 pp | [11.41, 19.11] pp |
| 5 | bridge_cols_minus_fk_cols | 91 | -8.70 pp | [-13.63, -3.90] pp |
| 10 | bridge_cols_minus_multi_nonbridge | 90 | -13.91 pp | [-24.22, -3.69] pp |
| 10 | fk_cols_minus_multi_nonbridge | 390 | 13.75 pp | [9.79, 17.73] pp |
| 10 | union_minus_multi_nonbridge | 390 | 13.11 pp | [9.16, 17.14] pp |
| 10 | bridge_cols_minus_fk_cols | 91 | -13.19 pp | [-18.52, -8.02] pp |
| 20 | bridge_cols_minus_multi_nonbridge | 90 | -11.65 pp | [-20.28, -3.24] pp |
| 20 | fk_cols_minus_multi_nonbridge | 390 | 12.34 pp | [8.57, 16.02] pp |
| 20 | union_minus_multi_nonbridge | 390 | 11.92 pp | [8.15, 15.61] pp |
| 20 | bridge_cols_minus_fk_cols | 91 | -10.22 pp | [-14.78, -5.73] pp |
| 50 | bridge_cols_minus_multi_nonbridge | 90 | -3.48 pp | [-8.67, 1.74] pp |
| 50 | fk_cols_minus_multi_nonbridge | 390 | 7.30 pp | [4.47, 10.12] pp |
| 50 | union_minus_multi_nonbridge | 390 | 7.19 pp | [4.36, 10.02] pp |
| 50 | bridge_cols_minus_fk_cols | 91 | -1.52 pp | [-3.65, 0.46] pp |
