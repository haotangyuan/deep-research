# API 接口文档

> 完整的交互式 API 文档请访问启动后的 Scalar UI：http://localhost:8080/scalar/index.html

## 认证说明

所有需要认证的接口都需要在请求头中携带 JWT Token：

```
Authorization: Bearer <your_jwt_token>
```

## 接口列表

### 用户认证

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/v1/user/register` | 用户注册 | ❌ |
| POST | `/api/v1/user/login` | 用户登录 | ❌ |
| GET | `/api/v1/user/me` | 获取当前用户信息 | ✅ |

### 研究管理

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/v1/research/create` | 创建研究会话 | ✅ |
| GET | `/api/v1/research/list` | 获取研究列表 | ✅ |
| GET | `/api/v1/research/{researchId}` | 获取研究状态 | ✅ |
| GET | `/api/v1/research/{researchId}/messages` | 获取研究消息和事件 | ✅ |
| POST | `/api/v1/research/{researchId}/messages` | 发送消息 | ✅ |
| GET | `/api/v1/research/sse` | SSE 实时事件流 | ✅ |

### 模型管理

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/v1/models` | 获取可用模型列表 | ✅ |
| POST | `/api/v1/models` | 添加自定义模型 | ✅ |
| DELETE | `/api/v1/models/{modelId}` | 删除自定义模型 | ✅ |

## 研究状态说明

| 状态 | 说明 |
|------|------|
| NEW | 新建研究 |
| QUEUE | 排队中 |
| START | 开始研究 |
| IN_SCOPE | 确定研究范围 |
| NEED_CLARIFICATION | 需要用户澄清 |
| IN_RESEARCH | 研究中 |
| IN_REPORT | 生成报告中 |
| COMPLETED | 研究完成 |
| FAILED | 研究失败 |

## 核心流程

### 发起研究

```
1. POST /api/v1/research/create?num=1        → 获取 researchId
2. POST /api/v1/research/{id}/messages        → 发送研究问题 + modelId + budget
3. GET  /api/v1/research/sse?researchId={id}  → SSE 订阅进度事件
4. GET  /api/v1/research/{id}                 → 轮询最终状态
5. GET  /api/v1/research/{id}/messages        → 获取完整消息和事件历史
```

### SSE 事件类型

| 类型 | 说明 |
|------|------|
| QUEUE | 排队中，含预计开始时间 |
| SCOPE | 范围分析阶段事件 |
| SUPERVISOR | 研究规划阶段事件 |
| RESEARCH | 子主题研究事件 |
| SEARCH | 搜索执行事件 |
| REPORT | 报告生成事件 |
| ERROR | 错误事件 |

### 模型配置

模型通过数据库 `model` 表管理，支持两种类型：

- **GLOBAL**：管理员预置的全局模型，所有用户可用
- **USER**：用户自定义模型，仅该用户可用

每个模型记录包含：`model`（模型标识）、`base_url`（API 地址）、`api_key`（密钥）、`name`（显示名称）。
