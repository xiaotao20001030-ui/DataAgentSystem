# 模型执行准确率评测

该目录负责为扰动变体生成 SQL、执行预测 SQL、计算执行准确率，并应用
“20 列扰动下小模型下降比 API 大模型多至少 10 个百分点”的判定。

## 模型矩阵

`model_matrix.json` 固定了：

- `Qwen/Qwen3-0.6B`
- `Qwen/Qwen3-1.7B`
- `Qwen/Qwen3-4B`
- `Qwen/Qwen2.5-Coder-1.5B-Instruct`
- 一个 OpenAI 兼容 API 大模型，`model` 需要按实际服务填写

本地模型统一使用 instruct/post-trained checkpoint 和
`enable_thinking=false` 的非思考模式，避免把基座补全模型与指令模型混用。

## 生成预测

三条主实验条件默认是 `base`、`add_random_20`、`add_synonym_20`。

```bash
cd /Users/xiaotao/PycharmProjects/DataAgentSystem/第四周
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  ../.venv/bin/python model_eval/generate_predictions.py \
  --model-key qwen3_0_6b --local-files-only
```

API 模型示例：

```bash
export OPENAI_API_KEY=...
../.venv/bin/python model_eval/generate_predictions.py \
  --model-key api_control \
  --api-base https://api.openai.com/v1
```

非 OpenAI 的兼容服务可在 `model_matrix.json` 修改 `api_base` 和 `model`。

## 执行评分

```bash
../.venv/bin/python model_eval/score_predictions.py \
  --predictions model_eval/predictions/qwen3_0_6b.jsonl
```

预测和 gold SQL 都在只读 SQLite 连接中执行。结果按值比较；gold SQL 含
`ORDER BY` 时保留行顺序，否则按多重集合比较。

## 通过标准

```bash
../.venv/bin/python model_eval/analyze_execution_gate.py
```

每个小模型分别对 `add_random_20` 和 `add_synonym_20` 计算
“基线准确率 - 扰动准确率”，再与 API 大模型做逐题配对 bootstrap。
只有每个小模型、两种多给扰动都满足下降差至少 10 个百分点且差值 95% CI
下界大于 0，总判定才通过。
