# BIRD 官方评分复核

## 原因

旧评分器使用 Counter 比较结果，并对部分 ORDER BY 查询强制行顺序；BIRD 官方
Mini-Dev evaluation_ex.py 使用 set 比较，忽略行顺序和重复行。

## 修正

- 27,620 条预测全部重新评分。
- 模型 SQL 与 gold SQL 均使用 30 秒超时。
- 查询错误与 gold 错误按官方规则计为 incorrect。
- 输出独立保存在 BIRD_RESULTS/scores_official。
- 生成脚本已补 `random.seed`、`torch.manual_seed`、CUDA seed 和 API seed；
  既有 greedy 预测没有因 seed 修复而重新生成。

## 差异

```text
false -> true: 803
true -> false: 16
```

逐条件差异见 official_rescore_delta.csv。
