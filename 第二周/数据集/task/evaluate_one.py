import os

# ★ 必须在 import torch 之前设置
#os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"   # 服务器上跑时解开注释

import json
import sqlite3
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from build_schema import db_schemas, build_schema_text

# ============ 配置 ============
DATA_DIR = "/Users/xiaotao/PycharmProjects/DataAgentSystem/第二周/数据集"
#DATA_DIR = "/root/fsas/home/xiaotao/xiaotao/spider"
MODEL_NAME = "Qwen/Qwen3-0.6B"  # 之后可改成 1.7B
SAMPLE_INDEX = 0  # 先跑第 0 条，之后可以改
# ============ Prompt 构造 ============
def build_prompt(schema_text, question):
    return f"""You are a SQLite expert. Given a database schema and a question, write a SQL query that answers the question. Only output the SQL query, no explanation, no markdown fences.

### Database Schema:
{schema_text}

### Question:
{question}

### SQL:
"""


# ============ 输出清洗 ============
import re


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

    # 3. 用正则找真正的 SQL 语句（严格匹配单词边界）
    candidates = []
    for m in re.finditer(r'\b(SELECT|WITH)\b', text, re.IGNORECASE):
        start = m.start()
        after = text[start:start + 20]
        # 要求 SQL 关键字后面紧跟空格 + 合法字符
        if re.match(r'(SELECT|WITH)\s+[\w\*\("]', after, re.IGNORECASE):
            candidates.append(start)

    if candidates:
        text = text[candidates[-1]:]
    else:
        # 找不到真正的 SQL，返回原文
        return text.strip()

    # 4. 去掉分号及之后的所有内容
    text = text.split(";")[0].strip()

    return text

# ============ 执行 SQL ============
def execute_sql(db_path, sql):
    """执行 SQL，返回 (结果集, 错误信息)，出错时 result 为 None"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        result = cursor.fetchall()
        conn.close()
        return result, None
    except Exception as e:
        return None, str(e)


# ============ 结果对比 ============
def is_correct(pred_result, gold_result):
    """结果集对比：忽略顺序，忽略类型差异（统一转 str）"""
    if pred_result is None:
        return False

    def normalize(rows):
        return sorted([tuple(str(c) for c in row) for row in rows])

    return normalize(pred_result) == normalize(gold_result)


# ============ 主流程 ============
def main():
    print(f"加载模型: {MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype="auto",
        device_map="auto",
        trust_remote_code=True,
    )

    # 读样本
    with open(os.path.join(DATA_DIR, "dev.json"), encoding="utf-8") as f:
        dev = json.load(f)

    item = dev[SAMPLE_INDEX]
    db_id = item["db_id"]
    question = item["question"]
    gold_sql = item["query"]

    db_path = os.path.join(DATA_DIR, "database", db_id, f"{db_id}.sqlite")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    # 拼 prompt
    schema_text = build_schema_text(db_schemas[db_id])
    prompt = build_prompt(schema_text, question)

    # 模型生成
    messages = [{"role": "user", "content": prompt}]
    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=256,
            do_sample=False,  # 贪心解码，结果稳定
        )

    raw = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[-1]:],
        skip_special_tokens=True,
    )
    pred_sql = clean_sql(raw)

    # 执行对比
    gold_result, gold_err = execute_sql(db_path, gold_sql)
    pred_result, pred_err = execute_sql(db_path, pred_sql)

    # ============ 打印 ============
    print("\n" + "=" * 70)
    print(f"样本 #{SAMPLE_INDEX}")
    print("=" * 70)
    print(f"db_id   : {db_id}")
    print(f"问题    : {question}")
    print("-" * 70)
    print(f"标准 SQL: {gold_sql}")
    print(f"标准结果: {gold_result}" + (f"  [错误: {gold_err}]" if gold_err else ""))
    print("-" * 70)
    print(f"模型原始输出:\n{raw}")
    print("-" * 70)
    print(f"清洗后 SQL: {pred_sql}")
    print(f"预测结果 : {pred_result}" + (f"  [错误: {pred_err}]" if pred_err else ""))
    print("-" * 70)

    # ============ 判定 ============
    if pred_err:
        print(f"❌ 失败：预测 SQL 执行报错")
    elif is_correct(pred_result, gold_result):
        print(f"✅ 正确")
    else:
        print(f"❌ 失败：结果不一致")
    print("=" * 70)


if __name__ == "__main__":
    main()
