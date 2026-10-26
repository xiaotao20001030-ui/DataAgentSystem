# Missing-schema compliance audit

| model | family | n | correct | strict compliant | select * | evidence leak | authorizer errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen2_5_coder_1_5b | missing_bridge_table | 103 | 3 | 3 | 0 | 9 | 84 |
| qwen2_5_coder_1_5b | missing_fk_column | 494 | 45 | 4 | 0 | 40 | 344 |
| qwen3_0_6b | missing_bridge_table | 103 | 0 | 0 | 1 | 9 | 89 |
| qwen3_0_6b | missing_fk_column | 494 | 8 | 2 | 6 | 40 | 414 |
| qwen3_1_7b | missing_bridge_table | 103 | 3 | 3 | 0 | 9 | 77 |
| qwen3_1_7b | missing_fk_column | 494 | 37 | 6 | 0 | 40 | 339 |
| qwen3_4b | missing_bridge_table | 103 | 3 | 3 | 0 | 9 | 51 |
| qwen3_4b | missing_fk_column | 494 | 102 | 8 | 1 | 40 | 164 |
