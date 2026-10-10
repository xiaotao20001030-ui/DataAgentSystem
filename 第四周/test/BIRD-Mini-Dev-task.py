# ============================================================
# 任务 4：BIRD Mini-Dev 上的 Schema Linking (列级检索) 基线实验
# 作者: xiaotao
# 功能: 用 sqlglot 解析标准 SQL 提取 GT，然后跑 BM25 和向量检索，
#       计算列级 Recall@k，并区分单表/多表问题生成基线结果表。
# ============================================================

# --- 1. 导入所有必需的库 ---
import json  # 用于读取 JSON 格式的数据集和 Schema 文件
import os  # 用于拼接文件路径，避免不同操作系统路径分隔符的问题

import numpy as np  # 用于数值计算和数组操作 (如排序、求均值)
import pandas as pd  # 用于创建和操作数据表格 (DataFrame)
import sqlglot  # 核心库：用于解析 SQL 语句为抽象语法树 (AST)
from rank_bm25 import BM25Okapi  # 用于 BM25 稀疏检索算法
from sentence_transformers import SentenceTransformer, util  # 用于向量检索 (稠密检索)
from sqlglot import exp  # sqlglot 的表达式模块，用于遍历 AST 节点 (如 Table, Column)
from tqdm import tqdm  # 用于显示进度条，让循环过程可视化

# ============================================================
# 第一部分：加载 BIRD Mini-Dev 数据集
# ============================================================

# 定义数据集的绝对路径 (根据你电脑的实际位置)
BASE_DIR = "/Users/xiaotao/PycharmProjects/DataAgentSystem/第四周/minidev/MINIDEV"

# 1. 加载问题 (questions) 数据
# 这里使用的是 sqlite 版本的问题文件，包含了 question, SQL, db_id 等字段
with open(os.path.join(BASE_DIR, "mini_dev_sqlite.json"), 'r', encoding='utf-8') as f:
    questions = json.load(f)  # 将 JSON 文件加载为 Python 的 list 字典
print(f"✅ 加载了 {len(questions)} 条问题")

# 2. 加载 Schema (数据库表结构) 数据
# dev_tables.json 包含了所有数据库的表名、列名、主外键等结构化信息
with open(os.path.join(BASE_DIR, "dev_tables.json"), 'r', encoding='utf-8') as f:
    tables = json.load(f)  # 加载为 Python 的 list，每个元素是一个数据库的 schema
print(f"✅ 加载了 {len(tables)} 个数据库的 Schema")


# ============================================================
# 第二部分：核心函数定义 (解析 Ground Truth 和 构建语料库)
# ============================================================

# ---------- 2.1 解析 Ground Truth (标准答案) ----------
def extract_gt_from_sql(sql):
    """
    输入: 标准 SQL 语句 (字符串)
    输出: 该 SQL 真正用到的表集合 (gt_tables) 和 列集合 (gt_columns)
    核心思想: 利用 sqlglot 将 SQL 解析为语法树，遍历树节点提取信息。
    """
    try:
        # 将 SQL 字符串解析为抽象语法树 (AST)
        parsed = sqlglot.parse_one(sql)
    except Exception:
        # 如果遇到 sqlglot 无法解析的极少数奇怪 SQL，直接返回空集合，跳过该条数据
        return set(), set()

    gt_tables = set()  # 用于存储提取出的真实表名 (小写)
    gt_columns = set()  # 用于存储提取出的真实列名，格式为 "表名.列名" (小写)
    alias_map = {}  # 用于处理表别名，例如 "customers AS T1" 中的 T1 -> customers

    # --- 步骤 A: 提取所有表 ---
    for table in parsed.find_all(exp.Table):
        real_name = table.name.lower()  # 获取真实的表名并转小写
        gt_tables.add(real_name)  # 加入表集合

        # 如果表有别名 (alias)，记录映射关系，方便后续还原列所属的真实表
        if table.alias:
            alias_map[table.alias.lower()] = real_name

    # --- 步骤 B: 提取所有列 ---
    for column in parsed.find_all(exp.Column):
        col_name = column.name.lower()  # 获取列名并转小写
        tbl_name = column.table.lower()  # 获取列所属的表名 (可能是别名) 并转小写

        # 如果列所属的表名是别名，通过 alias_map 还原成真实的表名
        if tbl_name in alias_map:
            tbl_name = alias_map[tbl_name]

        # 只有当列所属的表确实在本次查询的 gt_tables 里时，才认为它是有效列
        if tbl_name in gt_tables:
            # 拼接成 "表名.列名" 的唯一格式，方便后续比对
            gt_columns.add(f"{tbl_name}.{col_name}")
        else:
            # 处理少数没有表名前缀的列 (例如 SELECT 1 或子查询里没前缀的列)
            gt_columns.add(col_name)

    return gt_tables, gt_columns


# ---------- 2.2 构建检索语料库 ----------
# 思路: 把每个数据库的 Schema 转换成一堆 "文本字符串"，方便后续 BM25 和向量模型处理。
# 结构: db_corpus = { 'db_id': { 'tables': [...], 'columns': [...] } }
db_corpus = {}

for db in tables:  # 遍历每个数据库的 schema
    db_id = db['db_id']  # 数据库唯一标识
    table_names = db['table_names_original']  # 该库所有原始表名列表
    column_names = db['column_names_original']  # 该库所有原始列信息，格式为 [表索引, 列名]

    # --- 构建表级文档 ---
    # 把一张表的所有列拼成一句话，方便后续做表级检索
    table_docs = []
    for i, t_name in enumerate(table_names):
        # 提取属于第 i 张表的所有列名
        cols = [col[1] for col in column_names if col[0] == i]
        # 拼成类似 "Table: customers, Columns: id, name, age"
        doc = f"Table: {t_name}, Columns: {', '.join(cols)}"
        table_docs.append(doc)

    # --- 构建列级文档 ---
    # 直接把每一列构建成 "表名.列名" 的格式，这是评测的最小单位
    col_docs = []
    for col in column_names:
        if col[0] == -1:  # 跳过特殊列 (索引为 -1 通常表示无效列)
            continue
        t_name = table_names[col[0]]  # 通过索引找到所属表名
        c_name = col[1]  # 列名
        col_docs.append(f"{t_name}.{c_name}")  # 例如 "customers.CustomerID"

    # 保存到全局字典中，方便后续通过 db_id 快速提取
    db_corpus[db_id] = {'tables': table_docs, 'columns': col_docs}

print("✅ 语料库构建完毕")
# 测试一下: 打印第一个数据库的前 5 个列，确认格式正确
first_db = list(db_corpus.keys())[0]
print(f"数据库 [{first_db}] 的前 5 个列:", db_corpus[first_db]['columns'][:5])

# ============================================================
# 第三部分：检索器实现 (BM25 和 向量检索)
# ============================================================

# 加载预训练的向量模型 (首次运行会自动下载，约 80MB)
# all-MiniLM-L6-v2 是一个轻量级、速度快的语义嵌入模型
model = SentenceTransformer('all-MiniLM-L6-v2')


def bm25_retrieve(question, corpus, top_k=10):
    """
    BM25 稀疏检索: 基于词频和逆文档频率
    输入: 问题文本, 候选文档列表 (列名列表), 返回前 top_k 个
    """
    # 1. 对语料库的每一篇文档进行分词 (转小写并按空格切分)
    tokenized_corpus = [doc.lower().split() for doc in corpus]
    # 2. 初始化 BM25 模型，计算 IDF 等统计量
    bm25 = BM25Okapi(tokenized_corpus)
    # 3. 对用户问题同样进行分词
    tokenized_query = question.lower().split()
    # 4. 计算问题与每一篇文档的 BM25 分数
    scores = bm25.get_scores(tokenized_query)
    # 5. 将分数从高到低排序，取前 top_k 个索引
    top_indices = np.argsort(scores)[::-1][:top_k]  # [::-1] 实现降序
    # 6. 返回对应的文档文本
    return [corpus[i] for i in top_indices]


def vector_retrieve(question, corpus, top_k=10):
    """
    向量检索 (稠密检索): 基于语义相似度
    输入: 问题文本, 候选文档列表, 返回前 top_k 个
    """
    # 1. 将问题编码为向量 (转换为 PyTorch 张量，方便计算)
    q_emb = model.encode(question, convert_to_tensor=True)
    # 2. 将整个语料库编码为向量矩阵
    doc_embs = model.encode(corpus, convert_to_tensor=True)
    # 3. 计算问题向量与每个文档向量的余弦相似度 (cos_sim)
    scores = util.cos_sim(q_emb, doc_embs)[0]  # [0] 取出那一行的分数
    # 4. 按分数降序排序，取前 top_k 个索引
    top_indices = np.argsort(scores.cpu().numpy())[::-1][:top_k]
    # 5. 返回对应的文档文本
    return [corpus[i] for i in top_indices]


# --- 快速测试检索器 ---
sample = questions[0]
db_id = sample['db_id']
q_text = sample['question']
corpus = db_corpus[db_id]['columns']  # 取第一个问题的数据库的列语料

print("问题:", q_text)
print("BM25 Top-5:", bm25_retrieve(q_text, corpus, 5))
print("向量 Top-5:", vector_retrieve(q_text, corpus, 5))


# ============================================================
# 第四部分：全量评测与生成基线结果表
# ============================================================

def evaluate_all(questions, retriever_func, k_values=[1, 3, 5, 10]):
    """
    评测函数: 遍历所有问题，计算 Recall@k
    核心逻辑:
        1. 用 sqlglot 从标准 SQL 提取真实的表和列 (Ground Truth)
        2. 根据真实的表数量，区分是单表问题还是多表问题
        3. 使用指定的 retriever_func (BM25 或 向量) 检索出 Top-K 个列
        4. 计算 Recall@k = 命中列数 / 真实列总数
        5. 按单表/多表分类，计算平均 Recall@k
    """
    # 初始化结果字典: { 'single': {1: [], 3: [], ...}, 'multi': {1: [], 3: [], ...} }
    results = {'single': {k: [] for k in k_values},
               'multi': {k: [] for k in k_values}}

    # 使用 tqdm 显示进度条
    for item in tqdm(questions, desc="评测中"):
        q_text = item['question']  # 用户问题
        db_id = item['db_id']  # 数据库 ID
        sql = item['SQL']  # 标准答案 SQL

        # --- 1. 提取 Ground Truth ---
        gt_tables, gt_columns = extract_gt_from_sql(sql)
        if len(gt_columns) == 0:
            continue  # 如果没解析出列，跳过这条数据

        # --- 2. 判断是单表还是多表问题 ---
        # 如果真实用到的表数量为 1，归为 single，否则归为 multi
        p_type = 'single' if len(gt_tables) == 1 else 'multi'

        # --- 3. 获取当前数据库对应的列语料库 ---
        corpus = db_corpus[db_id]['columns']
        if not corpus:
            continue  # 如果该数据库没有列，跳过

        # --- 4. 执行检索 ---
        # 为了能统一算不同 k 的 Recall，我们一次性检索出最大的 k (比如 10)
        pred_cols = retriever_func(q_text, corpus, top_k=max(k_values))

        # --- 5. 计算并记录 Recall@k ---
        for k in k_values:
            # 取前 k 个预测结果，转为集合方便求交集
            pred_k = set(pred_cols[:k])
            # 计算公式: 命中列数 / 真实列总数
            recall = len(pred_k & gt_columns) / len(gt_columns)
            # 把这条数据的 recall 记录到对应的类型 (single/multi) 和 k 值下
            results[p_type][k].append(recall)

    # --- 6. 对每种类型和每个 k 求平均 ---
    report = {}
    for p_type in ['single', 'multi']:
        # 如果该类型下有数据，就求均值；否则返回 0.0
        report[p_type] = {k: np.mean(results[p_type][k]) if results[p_type][k] else 0.0
                          for k in k_values}
    return report


# --- 开始运行评测 ---
print("===== 跑 BM25 =====")
bm25_report = evaluate_all(questions, bm25_retrieve)

print("===== 跑 向量检索 =====")
vec_report = evaluate_all(questions, vector_retrieve)

# ============================================================
# 第五部分：生成最终的“基线结果表”并保存
# ============================================================

# --- 5.1 整理数据为普通表格 (4行数据) ---
rows = []
# 遍历两种方法: BM25 和 向量检索
for method_name, report in [("BM25", bm25_report), ("向量检索", vec_report)]:
    # 遍历两种问题类型: 单表 和 多表
    for p_type in ['single', 'multi']:
        # 转换为中文标签
        p_name = "单表问题" if p_type == "single" else "多表问题"
        # 创建一行数据
        row = {"方法": method_name, "问题类型": p_name}
        # 把 Recall@1, 3, 5, 10 的数值填入
        for k in [1, 3, 5, 10]:
            row[f"Recall@{k}"] = f"{report[p_type][k]:.4f}"  # 保留 4 位小数
        rows.append(row)

# 创建 DataFrame
df = pd.DataFrame(rows)
print("\n========== 🎯 最终基线结果表 (原始长表版) ==========")
print(df.to_string(index=False))

# 保存原始结果到 CSV
df.to_csv("baseline_results.csv", index=False)
print("\n✅ 结果已保存到 baseline_results.csv")

# ============================================================
# 第六部分：将结果表转换为“宽表”以便于汇报展示
# ============================================================

# --- 6.1 重新读取刚才保存的 CSV (确保数据源一致) ---
df = pd.read_csv("baseline_results.csv")

# --- 6.2 使用 pivot 转换为宽表 ---
# 将“问题类型”从行索引变成列索引，让单表和多表并排显示
pivot_df = df.pivot(index='方法', columns='问题类型', values=['Recall@1', 'Recall@3', 'Recall@5', 'Recall@10'])

# --- 6.3 调整列的顺序，让同类指标挨在一起 ---
# 这样表格看起来是: R@1(单), R@1(多), R@3(单), R@3(多)... 一目了然
pivot_df = pivot_df.reindex(columns=[
    ('Recall@1', '单表问题'), ('Recall@1', '多表问题'),
    ('Recall@3', '单表问题'), ('Recall@3', '多表问题'),
    ('Recall@5', '单表问题'), ('Recall@5', '多表问题'),
    ('Recall@10', '单表问题'), ('Recall@10', '多表问题'),
])

print("========== 🎯 最终基线结果表 (宽表版 - 推荐汇报使用) ==========")
print(pivot_df.to_string())

# --- 6.4 导出为新的 CSV，命名明确 ---
pivot_df.to_csv("final_baseline_results_wide.csv")
print("\n✅ 宽表版结果已保存到 final_baseline_results_wide.csv")
