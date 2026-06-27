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

