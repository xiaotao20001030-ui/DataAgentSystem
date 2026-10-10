import sqlglot
from sqlglot import exp

sql = """
SELECT student.name, score.score
FROM student
JOIN score
    ON student.id = score.student_id
WHERE score.score > 80
"""

# 解析 SQL，当前示例使用 SQLite 方言
tree = sqlglot.parse_one(sql, read="sqlite")

# 提取 SQL 中的表名
tables = {
    table.name
    for table in tree.find_all(exp.Table)
}

# 提取 SQL 中显式出现的列名
columns = {
    column.name
    for column in tree.find_all(exp.Column)
}

print("涉及的表：")
print(sorted(tables))

print("涉及的列：")
print(sorted(columns))
