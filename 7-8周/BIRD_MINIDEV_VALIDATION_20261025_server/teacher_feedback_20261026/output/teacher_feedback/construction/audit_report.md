# Teacher-feedback audit

## Synonym20 construction

{
  "question_count": 500,
  "added_columns": 10000,
  "relation_counts": {
    "same_name": 2168,
    "synonym": 7832
  },
  "generated_column_count": 10000,
  "sqlite_modified_by_generator": false,
  "added_name_entries_matching_existing_physical_columns": 141,
  "added_name_entries_absent_from_physical_columns": 9859,
  "explanation": "The perturbation generator only adds generated column metadata to the prompt schema. It neither alters SQLite nor supplies values for those new columns. Some generated names happen to coincide with real columns already in SQLite; generated=True is not proof of physical absence.",
  "duplicate_added_names_within_question": 616
}

## Bridge-table physical availability

{
  "variant_count": 103,
  "variants_with_removed_table_still_in_sqlite": 103,
  "all_removed_tables_still_accessible": true
}

## Relative accuracy drops

### api_control

| condition | relative drop | API relative drop | difference |
| --- | ---: | ---: | ---: |
| add_random_20 | 9.33% | 9.33% | +0.00 pp |
| add_synonym_20 | 60.06% | 60.06% | +0.00 pp |

### qwen2_5_coder_1_5b

| condition | relative drop | API relative drop | difference |
| --- | ---: | ---: | ---: |
| add_random_20 | 9.70% | 9.33% | +0.37 pp |
| add_synonym_20 | 48.51% | 60.06% | -11.55 pp |

### qwen3_0_6b

| condition | relative drop | API relative drop | difference |
| --- | ---: | ---: | ---: |
| add_random_20 | 31.51% | 9.33% | +22.18 pp |
| add_synonym_20 | 63.01% | 60.06% | +2.96 pp |

### qwen3_1_7b

| condition | relative drop | API relative drop | difference |
| --- | ---: | ---: | ---: |
| add_random_20 | 19.26% | 9.33% | +9.93 pp |
| add_synonym_20 | 58.52% | 60.06% | -1.54 pp |

### qwen3_4b

| condition | relative drop | API relative drop | difference |
| --- | ---: | ---: | ---: |
| add_random_20 | 13.83% | 9.33% | +4.50 pp |
| add_synonym_20 | 63.64% | 60.06% | +3.58 pp |

## Review sample

The completed fixed 30-case model-assisted SQL review is in sibling `synonym20/`; a human has not signed off its ambiguous semantic judgments.
