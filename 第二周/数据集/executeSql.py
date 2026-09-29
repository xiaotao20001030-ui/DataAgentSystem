import sqlite3
import json, os

DATA_DIR = "/Users/xiaotao/PycharmProjects/DataAgentSystem/第二周/数据集"

with open(os.path.join(DATA_DIR, "dev.json"), encoding="utf-8") as f:
    dev = json.load(f)

with open(os.path.join(DATA_DIR, "tables.json"), encoding="utf-8") as f:
    tables = json.load(f)

db_schemas = {t["db_id"]: t for t in tables}

# 拿第一条
item = dev[0]
db_id = item["db_id"]
gold_sql = item["query"]

# ★ 关键：路径多了一层 db_id
db_path = os.path.join(DATA_DIR, "database", db_id, f"{db_id}.sqlite")

print("db_id:", db_id)
print("问题:", item["question"])
print("标准SQL:", gold_sql)
print("数据库路径:", db_path)
print("文件存在:", os.path.exists(db_path))

if not os.path.exists(db_path):
    raise FileNotFoundError(f"数据库不存在: {db_path}")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("\n=== sqlite_master 里的 CREATE TABLE ===")
cursor.execute("SELECT sql FROM sqlite_master WHERE type='table'")
for row in cursor.fetchall():
    print(row[0])
    print("-" * 50)

try:
    cursor.execute(gold_sql)
    print("\n✅ 标准SQL执行成功:", cursor.fetchall())
except Exception as e:
    print("\n❌ 执行失败:", e)

conn.close()