# API 与数据契约

## 响应格式

```json
{"code":0,"message":"success","data":{}}
```

除注册和登录外，请求使用 `Authorization: Bearer <token>`。

## REST API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/user/register` | 注册 |
| POST | `/api/v1/user/login` | 登录 |
| GET | `/api/v1/user/me` | 当前用户 |
| GET/POST | `/api/v1/models` | 查询或新增模型 |
| DELETE | `/api/v1/models/{modelId}` | 删除模型 |
| GET | `/api/v1/research/create?num=1` | 创建研究会话 |
| GET | `/api/v1/research/list` | 研究列表 |
| GET | `/api/v1/research/{id}` | 研究状态 |
| GET/POST | `/api/v1/research/{id}/messages` | 查询或发送消息 |
| POST | `/api/v1/research/{id}/direction-action` | 确认或修订方向 |
| POST | `/api/v1/research/{id}/interventions` | 提交 ULTRA 下一轮轻干预 |
| POST | `/api/v1/research/{id}/cancel` | 取消研究 |
| GET | `/api/v1/research/sse` | 研究事件流 |

## SSE

连接头：`X-Research-Id`、`X-Client-Id`，重连时增加 `Last-Event-ID`。事件类型为 `message`、`event`、`report-stream`；结束包为 `[DONE] <status>`。

Redis key：

- `research:{id}:timeline`
- `research:{id}:checkpoint`
- `user:{userId}:researches`

## 数据表

| 表 | 内容 |
|---|---|
| `user` | 用户与头像 |
| `model` | 全局和用户模型配置 |
| `research_session` | 会话、状态、预算、token 用量 |
| `chat_message` | 用户和助手消息 |
| `workflow_event` | Agent 工作流时间线 |
| `research_intervention` | ULTRA 动态工作流的下一轮轻干预记录 |

## ULTRA 轻干预

- 仅 `ULTRA` 动态工作流支持。
- 当前轮不会被中断，干预只会在下一轮规划开始前生效。
- 同一研究同一时刻最多保留 1 条 `pending` 干预。
- 当用户再次提交时，按 `latest_wins` 规则替换旧的 `pending` 干预，旧记录保留并标记为 `superseded`。
- 干预提交成功后，会同步在聊天区、主时间线和 Agent Flow 中生成用户可感知的回显。

`POST /api/v1/research/{id}/interventions` 请求体：

```json
{
  "focusSections": ["海力士在存储市场的地位"],
  "reinforceModes": ["data", "latest"],
  "note": "优先分析优势、劣势和前瞻展望",
  "replacePending": true
}
```

`GET /api/v1/research/{id}/messages` 返回体新增：

- `pendingIntervention`
- `recentInterventions`

`pendingIntervention` / `recentInterventions[*]` 关键字段：

| 字段 | 含义 |
|---|---|
| `status` | `pending / applied / partially_applied / expired / rejected / superseded` |
| `focusSections` | 下一轮重点 section，最多 3 个 |
| `reinforceModes` | 结构化补强方向，枚举值为 `official / data / comparison / latest` |
| `applySummary` | 系统在某一轮实际采纳的结果摘要 |
| `rejectCode` / `rejectReason` | 未执行或过期原因 |
