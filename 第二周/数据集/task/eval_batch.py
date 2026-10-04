import os
import re

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# os.environ["CUDA_VISIBLE_DEVICES"] = "0"  # 如果用 GPU 就解开
import json
import sqlite3
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

# ============ 配置 ============
DATA_DIR = "/Users/xiaotao/PycharmProjects/DataAgentSystem/第二周/数据集"
#DATA_DIR = "/root/fsas/home/xiaotao/xiaotao/spider"
MODEL_NAME = "Qwen/Qwen3-0.6B"  # 跑完 0.6B 后改成 1.7B 再跑一次
NUM_SAMPLES = 3  # 抽 100 条

# 读取tables.json数据
with open(os.path.join(DATA_DIR, "tables.json"), encoding="utf-8") as f:
    tables = json.load(f)
db_schemas = {
    t["db_id"]: t for t in tables
}


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
        if table_idx == -1:  # 通配符 *，跳过
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


def build_prompt(schema_text, question):
    return f"""You are a SQLite expert. Given a database schema and a question, write a SQL query that answers the question. Only output the SQL query, no explanation, no markdown fences.

### Database Schema:
{schema_text}

### Question:
{question}

### SQL:
"""


def clean_sql(text):
    """从模型输出里提取纯 SQL（终极版）"""
    text = text.strip()

    # 1. 去掉 </think> 之前的所有内容
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()

    # 2. 处理 ```sql ... ``` 包裹
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.lower().startswith("sql"):
                p = p[3:].strip()
            if p.upper().startswith("SELECT") or p.upper().startswith("WITH"):
                text = p
                break

    # 3. 用正则找真正的 SQL 语句（大写 SELECT/WITH 开头，后跟空格和合法字符）
    # 匹配 SELECT 或 WITH 开头，到第一个分号或换行结束
    pattern = re.compile(
        r'\b(SELECT|WITH)\b\s+.*?(?=;|\n\n|$)',
        re.IGNORECASE | re.DOTALL
    )
    matches = pattern.findall(text)

    if matches:
        # 取最后一个匹配（通常是最终答案）
        # 但 findall 只返回括号组，这里需要换个方式
        pass

    # 更稳妥的方式：找最后一个 "SELECT" 或 "WITH" 的位置
    # 并且要求它后面紧跟空格和字母/下划线/*（排除 "with Singer_ID" 这种）
    candidates = []
    for m in re.finditer(r'\b(SELECT|WITH)\b', text, re.IGNORECASE):
        start = m.start()
        # 检查后面是否紧跟合法的 SQL 内容
        after = text[start:start + 20]
        if re.match(r'(SELECT|WITH)\s+[\w\*\("]', after, re.IGNORECASE):
            candidates.append(start)

    if candidates:
        # 取最后一个候选位置（模型通常最后才输出正确 SQL）
        text = text[candidates[-1]:]
    else:
        # 实在找不到，返回原文让执行报错
        return text.strip()

    # 4. 去掉分号及之后的所有内容
    text = text.split(";")[0].strip()

    return text


def execute_sql(db_path, sql):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        result = cursor.fetchall()
        conn.close()
        return result, None
    except Exception as e:
        return None, str(e)


def is_correct(pred_result, gold_result):
    if pred_result is None:
        return False

    # 忽略顺序，统一转 str 比较
    def normalize(rows):
        return sorted([tuple(str(c) for c in row) for row in rows])

    return normalize(pred_result) == normalize(gold_result)


def main():
    print(f"加载模型: {MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME, torch_dtype="auto", device_map="auto", trust_remote_code=True
    )

    # 读数据集
    with open(os.path.join(DATA_DIR, "dev.json"), encoding="utf-8") as f:
        dev = json.load(f)

    # 抽取前 100 条 (如果 dev 集不足 100 条，就全跑)
    samples = dev[:NUM_SAMPLES]

    correct_count = 0
    total_count = 0
    error_cases = []  # 用于存放人工分类的素材

    for idx, item in enumerate(samples):
        db_id = item["db_id"]
        question = item["question"]
        gold_sql = item["query"]

        db_path = os.path.join(DATA_DIR, "database", db_id, f"{db_id}.sqlite")
        if not os.path.exists(db_path):
            print(f"⚠️ 跳过样本 {idx}: 数据库不存在 {db_path}")
            continue

        # 构造 Prompt
        schema_text = build_schema_text(db_schemas[db_id])
        prompt = build_prompt(schema_text, question)

        messages = [{"role": "user", "content": prompt}]
        inputs = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt"
        ).to(model.device)

        # 生成
        with torch.no_grad():
            outputs = model.generate(**inputs, max_new_tokens=256, do_sample=False)

        raw = tokenizer.decode(outputs[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
        pred_sql = clean_sql(raw)

        # 执行
        gold_result, gold_err = execute_sql(db_path, gold_sql)
        pred_result, pred_err = execute_sql(db_path, pred_sql)

        total_count += 1
        is_ok = is_correct(pred_result, gold_result)
        if is_ok:
            correct_count += 1
        else:
            # 记录错误案例
            error_cases.append({
                "question_id": idx,
                "db_id": db_id,
                "question": question,
                "gold_sql": gold_sql,
                "pred_sql": pred_sql,
                "pred_error": pred_err,
                "gold_result": str(gold_result),
                "pred_result": str(pred_result)
            })
            print(f"❌ 样本 {idx} 失败. Q: {question[:30]}...")

        if (idx + 1) % 10 == 0:
            print(f"进度: {idx + 1}/{len(samples)} | 当前准确率: {correct_count / total_count * 100:.2f}%")

    # === 输出最终结果 ===
    accuracy = correct_count / total_count * 100 if total_count > 0 else 0
    print("\n" + "=" * 60)
    print(f"模型: {MODEL_NAME}")
    print(f"总样本数: {total_count}")
    print(f"正确数: {correct_count}")
    print(f"✅ 执行准确率 (Execution Accuracy): {accuracy:.2f}%")
    print("=" * 60)

    # 保存错误案例，供人工分类
    model_short = MODEL_NAME.split("/")[-1]
    error_file = f"error_cases_{model_short}.json"
    with open(error_file, "w", encoding="utf-8") as f:
        json.dump(error_cases, f, ensure_ascii=False, indent=2)
    print(f"\n已将 {len(error_cases)} 个错误案例保存至 {error_file}，请打开进行人工分类。")


if __name__ == "__main__":
    main()
