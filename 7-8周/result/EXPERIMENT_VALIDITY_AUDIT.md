# BIRD Mini-Dev 实验有效性审计

## 已修正的评分问题

旧自定义评分器使用 Counter，并在 gold SQL 含 ORDER BY 时强制顺序；BIRD 官方
Mini-Dev 使用 set 比较，忽略顺序和重复行。正式结果已使用官方语义和 30 秒超时
重新评分全部 27,620 条预测。

重评分共产生：

```text
false -> true: 803
true -> false: 16
```

## 仍然存在的设计限制

- baseline floor effect 使绝对准确率下降门槛对 Qwen3-0.6B 不公平。
- 合成近义列是人工干扰，真实 schema 近义列影响小得多。
- 漏给实验只隐藏 schema，数据库仍保留列；必须区分普通准确率和合规准确率。
- 597 个漏给变体来自 391 道题，统计使用 question-cluster bootstrap。
- 主实验仅覆盖 BIRD Mini-Dev 和一个 API 对照。
- 现有预测为单次 greedy 推理；seed 代码已修复，但未通过三个种子重跑生成。

## 正式判断

- 原预注册执行门槛不通过。
- 检索桥接偏差显著，检索门槛通过。
- Baseline-correct 和真实近义列提供机制支持，但属于补充分析。
