# Pure-column perturbation validation

- questions: 500
- levels: 5, 10, 20
- families: add_pure_column, base
- variants: 2000
- all added columns belong to gold tables: yes
- sha256: `ff0afd8687fc08349ceff3f6523e8a0f1be7a7f9740fd9246544eb4119e9cb18`

## Added columns

| family | level | relation | generated | count |
| --- | ---: | --- | --- | ---: |
| add_pure_column | 5 | within_table_filler | true | 250 |
| add_pure_column | 5 | within_table_random | false | 2250 |
| add_pure_column | 10 | within_table_filler | true | 869 |
| add_pure_column | 10 | within_table_random | false | 4131 |
| add_pure_column | 20 | within_table_filler | true | 3311 |
| add_pure_column | 20 | within_table_random | false | 6689 |
