
"""

# 安装必要依赖
!pip install transformers>=4.51.0 accelerate -q

from transformers import AutoModelForCausalLM, AutoTokenizer

model_name = "Qwen/Qwen3-0.6B"

# 加载分词器和模型
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype="auto",
    device_map="auto"
)

# 构造对话输入（使用官方 chat template）
messages = [{"role": "user", "content": "用一句话介绍你自己"}]
text = tokenizer.apply_chat_template(
    messages,
    tokenize=False,
    add_generation_prompt=True
)

model_inputs = tokenizer([text], return_tensors="pt").to(model.device)

# 生成回复
generated_ids = model.generate(**model_inputs, max_new_tokens=128)
output_ids = generated_ids[0][len(model_inputs.input_ids[0]):]

print(tokenizer.decode(output_ids, skip_special_tokens=True))
"""
import os

# 必须在导入 transformers 之前设置
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

model_name = "Qwen/Qwen3-0.6B"

# 加载分词器
tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)

# 加载模型，device_map="auto" 会自动把模型放到 GPU（如果可用）
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype="auto",
    trust_remote_code=True
)
# 构造对话消息
messages = [
    {"role": "user", "content": "请介绍一下你自己。"},
]

# 应用聊天模板，将消息转为模型输入
inputs = tokenizer.apply_chat_template(
    messages,
    add_generation_prompt=True,
    tokenize=True,
    return_dict=True,
    return_tensors="pt",
).to(model.device)

# 生成
outputs = model.generate(**inputs, max_new_tokens=200)

# 解码时跳过输入部分，只保留新生成的内容
generated_text = tokenizer.decode(
    outputs[0][inputs["input_ids"].shape[-1]:],
    skip_special_tokens=True
)
print(generated_text)