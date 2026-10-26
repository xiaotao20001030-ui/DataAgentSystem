# One-hop FK expansion vs plain retrieval

Schema token count uses: /root/fsas/home/xiaotao/xiaotao/MINIDEV/modules/Qwen3-0.6B.

## all-MiniLM-L6-v2

Questions: 391; query instruction: ``.
At k=10, one-hop FK expansion reduces miss rate by 19.09 pp (question-cluster bootstrap 95% CI [16.89, 21.28] pp).

| k | plain miss | expanded miss | delta | plain tokens | expanded tokens |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 73.93% | 56.98% | -16.96% | 53.3 | 66.8 |
| 10 | 56.88% | 37.79% | -19.09% | 107.6 | 128.5 |
| 20 | 38.95% | 21.03% | -17.93% | 207.7 | 233.4 |
| 50 | 16.57% | 8.33% | -8.24% | 462.1 | 480.2 |

## BGE base en v1.5

Questions: 391; query instruction: `Represent this sentence for searching relevant passages: `.
At k=10, one-hop FK expansion reduces miss rate by 24.03 pp (question-cluster bootstrap 95% CI [21.78, 26.26] pp).

| k | plain miss | expanded miss | delta | plain tokens | expanded tokens |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 74.81% | 55.23% | -19.57% | 55.0 | 67.6 |
| 10 | 61.05% | 37.02% | -24.03% | 110.4 | 127.6 |
| 20 | 42.64% | 23.55% | -19.09% | 212.2 | 235.9 |
| 50 | 19.38% | 10.47% | -8.91% | 467.1 | 481.5 |
