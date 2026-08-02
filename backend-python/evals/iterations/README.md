# Eval 迭代记录

这里保存每次正式 Eval 的可审计闭环，不新增数据库表。

每个 Experiment 对应一份 JSON（机器读取）和一份 Markdown（人工复盘），固定记录：

1. 跑了哪些 Dataset Item、档位和 Run；
2. 暴露了什么问题，以及触发结论的 Eval 指标；
3. 根因对应哪些 Agent 模块；
4. 做了什么修改；
5. 修改后执行了哪些测试或复评，指标如何变化。

`index.json` 是自动生成的轻量索引。初次 Eval 后 validation 为 `pending`；只有完成测试或复评后才能改为 `passed`、`partial` 或 `failed`。
