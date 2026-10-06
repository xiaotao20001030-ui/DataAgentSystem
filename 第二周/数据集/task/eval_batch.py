import os
import re
import random
import json
import sqlite3
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

# ============ 配置 ============
# 强制使用国内镜像下载模型
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ⚠️ 确保这里是你服务器上的真实数据路径
# 根据你之前的日志，你的项目在 /home/xiaotao/xiaotao/ 下，请核对下面这个路径是否正确
DATA_DIR = "/Users/xiaotao/PycharmProjects/DataAgentSystem/第二周/数据集"
MODEL_NAME = "Qwen/Qwen3-0.6B"  # 跑完 0.6B 后改成 1.7B 再跑一次
NUM_SAMPLES = 100  # 抽取 100 条
RANDOM_SEED = 42   # 固定随机种子，保证每次抽的 100 条是一样的

# 读取tables.json数据
with open(os.path.join(DATA_DIR, "tables.json"), encoding="utf-8") as f:
    tables = json.load(f)
db_schemas = {t["db_id"]: t for t in tables}


def build_schema_text(schema):
    """把 tables.json 里的 schema 拼成 CREATE TABLE 文本"""
    table_names = schema["table_names_original"]
    column_names = schema["column_names_original"]
    column_types = schema["column_types"]
    primary_keys = schema.get("primary_keys", [])
    foreign_keys = schema.get("foreign_keys", [])
    tables_cols = {i: [] for i in range(len(table_names))}
    for col_idx, (table_idx, col_name) in enumerate(column_names):
        if table_idx == -1: continue
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
        lines.append(")\n")

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
    """从模型输出里提取纯 SQL（保持你原有逻辑，略作优化）"""
    text = text.strip()
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()

    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.lower().startswith("sql"): p = p[3:].strip()
            if p.upper().startswith("SELECT") or p.upper().startswith("WITH"):
                text = p
                break

    candidates = []
    for m in re.finditer(r'\b(SELECT|WITH)\b', text, re.IGNORECASE):
        start = m.start()
        after = text[start:start + 20]
        if re.match(r'(SELECT|WITH)\s+[\w\*\("]', after, re.IGNORECASE):
            candidates.append(start)

    if candidates:
        text = text[candidates[-1]:]

    text = text.split(";")[0].strip()
    return text

#执行sql
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
    if pred_result is None: return False
    def normalize(rows):
        return sorted([tuple(str(c) for c in row) for row in rows])
    return normalize(pred_result) == normalize(gold_result)


def main():
    print(f"加载模型: {MODEL_NAME}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME, torch_dtype="auto", device_map="auto", trust_remote_code=True
    )

    # 读数据集
    with open(os.path.join(DATA_DIR, "dev.json"), encoding="utf-8") as f:
        dev = json.load(f)

    # ★ 修改为随机抽取 100 条
    random.seed(RANDOM_SEED)
    if len(dev) > NUM_SAMPLES:
        samples = random.sample(dev, NUM_SAMPLES)
    else:
        samples = dev

    correct_count = 0
    total_count = 0
    error_cases = []

    # 使用 tqdm 显示进度条，避免 print 卡住进程
    for idx, item in enumerate(samples):
        db_id = item["db_id"]
        question = item["question"]
        gold_sql = item["query"]

        # 注意路径拼接，确保与你的数据存储结构一致
        db_path = os.path.join(DATA_DIR, "database", db_id, f"{db_id}.sqlite")
        if not os.path.exists(db_path):
            print(f"⚠️ 跳过样本 {idx}: 数据库不存在 {db_path}", flush=True)
            continue

        schema_text = build_schema_text(db_schemas[db_id])
        prompt = build_prompt(schema_text, question)

        messages = [{"role": "user", "content": prompt}]
        inputs = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt"
        ).to(model.device)

        with torch.no_grad():
            outputs = model.generate(**inputs, max_new_tokens=256, do_sample=False)

        raw = tokenizer.decode(outputs[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
        pred_sql = clean_sql(raw)

        gold_result, gold_err = execute_sql(db_path, gold_sql)
        pred_result, pred_err = execute_sql(db_path, pred_sql)

        total_count += 1
        if is_correct(pred_result, gold_result):
            correct_count += 1
        else:
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
            # 打印时加上 flush=True，避免阻塞后台
            print(f"❌ 样本 {idx} 失败. Q: {question[:30]}...", flush=True)

        if (idx + 1) % 10 == 0:
            print(f"进度: {idx + 1}/{len(samples)} | 当前准确率: {correct_count / total_count * 100:.2f}%", flush=True)

    # === 输出最终结果 ===
    accuracy = correct_count / total_count * 100 if total_count > 0 else 0
    print("\n" + "=" * 60, flush=True)
    print(f"模型: {MODEL_NAME}")
    print(f"总样本数: {total_count}")
    print(f"正确数: {correct_count}")
    print(f"✅ 执行准确率 (Execution Accuracy): {accuracy:.2f}%")
    print("=" * 60, flush=True)

    model_short = MODEL_NAME.replace("/", "_")
    error_file = f"error_cases_{model_short}.json"
    with open(error_file, "w", encoding="utf-8") as f:
        json.dump(error_cases, f, ensure_ascii=False, indent=2)
    print(f"\n已将 {len(error_cases)} 个错误案例保存至 {error_file}，请打开进行人工分类。", flush=True)

if __name__ == "__main__":
    main()