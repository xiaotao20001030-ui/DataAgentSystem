import json, os

DATA_DIR = "."   # 换成你的 spider 数据目录

with open(os.path.join(DATA_DIR, "dev.json"), encoding="utf-8") as f:
    dev = json.load(f)

with open(os.path.join(DATA_DIR, "tables.json"), encoding="utf-8") as f:
    tables = json.load(f)

db_schemas = {t["db_id"]: t for t in tables}

db_id = dev[0]["db_id"]
schema = db_schemas[db_id]

print("db_id:", db_id)
print("问题:", dev[0]["question"])
print("标准SQL:", dev[0]["query"])

print("\n表结构:")
table_names = schema["table_names_original"]
column_names = schema["column_names_original"]

for table_idx, col_name in column_names:
    if table_idx == -1:
        continue
    print(f"  {table_names[table_idx]}.{col_name}")

print("\n主键:", schema.get("primary_keys"))
print("外键:", schema.get("foreign_keys"))