# HITL 研究方向确认

项目支持 `DIRECTION_ONLY` 模式，在范围分析完成后暂停研究，等待用户确认或修订研究方向。

## 状态流转

```text
IN_SCOPE
  -> AWAITING_DIRECTION_CONFIRM
  -> APPROVE -> IN_RESEARCH
  -> REVISE  -> IN_SCOPE -> AWAITING_DIRECTION_CONFIRM
```

暂停时，`AgentPipeline` 将 `DeepResearchState` 写入 Redis checkpoint，并通过 SSE 发布 `DIRECTION_CONFIRM` 事件。前端调用：

```http
POST /api/v1/research/{researchId}/direction-action
Authorization: Bearer <token>
Content-Type: application/json

{"action":"APPROVE","feedback":""}
```

修订方向时使用 `REVISE` 并在 `feedback` 中提交修改意见。服务恢复 checkpoint 后重新进入范围阶段；批准后跳过范围阶段并继续并行研究和报告生成。

Checkpoint key 为 `research:{id}:checkpoint`，有效期与研究 timeline 一致。接口必须校验研究任务所有权，并通过状态更新避免同一任务重复恢复。

