# Missing-schema compliance audit

| model | family | n | correct | strict compliant | select * | evidence leak | authorizer errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| api_control | missing_bridge_table | 103 | 20 | 9 | 0 | 9 | 22 |
| api_control | missing_fk_column | 494 | 173 | 11 | 0 | 40 | 48 |
| qwen2_5_coder_1_5b | missing_bridge_table | 103 | 2 | 2 | 0 | 9 | 81 |
| qwen2_5_coder_1_5b | missing_fk_column | 494 | 50 | 2 | 0 | 40 | 335 |
| qwen3_0_6b | missing_bridge_table | 103 | 0 | 0 | 1 | 9 | 89 |
| qwen3_0_6b | missing_fk_column | 494 | 8 | 2 | 6 | 40 | 414 |
| qwen3_1_7b | missing_bridge_table | 103 | 3 | 3 | 0 | 9 | 76 |
| qwen3_1_7b | missing_fk_column | 494 | 37 | 6 | 0 | 40 | 337 |
| qwen3_4b | missing_bridge_table | 103 | 3 | 3 | 0 | 9 | 50 |
| qwen3_4b | missing_fk_column | 494 | 100 | 8 | 1 | 40 | 162 |
