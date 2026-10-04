import os

import re

# ★ 必须在 import torch 之前设置
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# 服务器上指定卡（本地跑可删）
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import json
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from build_schema import db_schemas, build_schema_text

DATA_DIR = "/Users/xiaotao/PycharmProjects/DataAgentSystem/第二周/数据集"
MODEL_NAME = "Qwen/Qwen3-0.6B"  # 先跑 0.6B，跑通再换 1.7B


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


def main():
    print("加载分词器...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)

    print("加载模型...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype="auto",
        device_map="auto",
        trust_remote_code=True,
    )

    # 读一条样本
    with open(os.path.join(DATA_DIR, "dev.json"), encoding="utf-8") as f:
        dev = json.load(f)

    item = dev[0]
    db_id = item["db_id"]
    schema_text = build_schema_text(db_schemas[db_id])
    prompt = build_prompt(schema_text, item["question"])

    print("\n===== 问题 =====")
    print(item["question"])
    print("\n===== 标准 SQL =====")
    print(item["query"])

    # 生成
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
            do_sample=False,  # 贪心解码，结果稳定可复现
        )

    raw = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[-1]:],
        skip_special_tokens=True,
    )

    print("\n===== 模型原始输出 =====")
    print(raw)
    print("\n===== 清洗后的 SQL =====")
    pred_sql = clean_sql(raw)
    print(pred_sql)


if __name__ == "__main__":
    main()
