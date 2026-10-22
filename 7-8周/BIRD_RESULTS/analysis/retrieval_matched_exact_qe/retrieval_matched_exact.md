# Retrieval matched-baseline re-analysis (exact original setup)

- model: `/root/fsas/home/xiaotao/xiaotao/models/all-MiniLM-L6-v2`
- query: `question+evidence`
- questions: 500

## Miss rates

| k | single | multi_all | multi_nonbridge | bridge_cols | fk_cols | union | bridge_tables |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 20.57% | 46.50% | 37.34% | 43.60% | 58.97% | 57.66% | 18.45% |

## Paired within-question differences

| k | comparison | n questions | diff | 95% CI |
| ---: | --- | ---: | ---: | --- |
| 10 | bridge_cols_minus_multi_nonbridge | 90 | 2.15 pp | [-7.96, 12.24] pp |
| 10 | fk_cols_minus_multi_nonbridge | 390 | 26.11 pp | [22.15, 30.16] pp |
| 10 | union_minus_multi_nonbridge | 390 | 25.34 pp | [21.38, 29.37] pp |
| 10 | bridge_cols_minus_fk_cols | 91 | -12.38 pp | [-17.80, -6.98] pp |
