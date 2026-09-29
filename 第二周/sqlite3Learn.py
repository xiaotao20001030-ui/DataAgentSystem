import sqlite3

# conn = sqlite3.connect("spider_db.sqlite")
# cursor = conn.cursor()
#
# sql = "SELECT name FROM students WHERE age > 18"
# try:
#     cursor.execute(sql)
#     result = cursor.fetchall()          # 模型生成的 SQL 的执行结果
# except Exception as e:
#     result = None                        # 执行失败（语法错等）

import json

with open("dev.json") as f:
    dev = json.load(f)

print("总条数:", len(dev))
print("第一条:", json.dumps(dev[0], indent=2, ensure_ascii=False))