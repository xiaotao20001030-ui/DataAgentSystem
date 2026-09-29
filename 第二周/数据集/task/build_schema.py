import json, os

DATA_DIR = "/Users/xiaotao/PycharmProjects/DataAgentSystem/第二周/数据集"

with open(os.path.join(DATA_DIR, "tables.json"), encoding="utf-8") as f:
    tables = json.load(f)
# print("tables:", tables)
db_schemas = {t["db_id"]: t for t in tables}


def build_schema_text(schema):
    """把 tables.json 里的 schema 拼成 CREATE TABLE 文本"""
    table_names = schema["table_names_original"]
    column_names = schema["column_names_original"]
    column_types = schema["column_types"]
    primary_keys = schema.get("primary_keys", [])
    foreign_keys = schema.get("foreign_keys", [])

    # 按表分组
    tables_cols = {i: [] for i in range(len(table_names))}
    for col_idx, (table_idx, col_name) in enumerate(column_names):
        if table_idx == -1:      # 通配符 *，跳过
            continue
        col_type = column_types[col_idx]
        tables_cols[table_idx].append((col_name, col_type, col_idx))

    lines = []
    for t_idx, t_name in enumerate(table_names):
        lines.append(f"CREATE TABLE {t_name} (")
        col_lines = []
        for col_name, col_type, col_idx in tables_cols[t_idx]:
            marker = "  -- primary key" if col_idx in primary_keys else ""
            col_lines.append(f"    {col_name} {col_type}{marker}")
        lines.append(",\n".join(col_lines))
        lines.append(")")
        lines.append("")

    if foreign_keys:
        lines.append("-- Foreign keys:")
        for a, b in foreign_keys:
            t_a, c_a = column_names[a]
            t_b, c_b = column_names[b]
            lines.append(f"--   {table_names[t_a]}.{c_a} = {table_names[t_b]}.{c_b}")

    return "\n".join(lines)


if __name__ == "__main__":
    db_id = "concert_singer"
    schema = db_schemas[db_id]
    print(build_schema_text(schema))