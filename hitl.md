# HITL（Human-in-the-Loop）技术方案

> **文档目标**：完整梳理当前项目基于 LangGraph + CopilotKit 的 HITL 实现方案，并在最后详解如何使用 AgentScope 框架在 Deep Research 多 Agent 项目中实现 HITL。

---

## 目录

- [第一部分：当前项目 HITL 实现方案](#第一部分当前项目-hitl-实现方案)
  - [1. 架构总览](#1-架构总览)
  - [2. 第一层：工具装饰器 —— `add_human_in_the_loop()`](#2-第一层工具装饰器--add_human_in_the_loop)
  - [3. 第二层：LangGraph `interrupt()` 机制](#3-第二层langgraph-interrupt-机制)
  - [4. 第三层：状态持久化 —— `AsyncRedisSaver`](#4-第三层状态持久化--asyncredissaver)
  - [5. 第四层：Pipeline 中断检测与 SSE 推送](#5-第四层pipeline-中断检测与-sse-推送)
  - [6. 第五层：前端 CopilotKit 审批表单](#6-第五层前端-copilotkit-审批表单)
  - [7. 第六层：结果回传与状态恢复](#7-第六层结果回传与状态恢复)
  - [8. `thread_id` 的存储与传递](#8-thread_id-的存储与传递)
  - [9. 完整时序图](#9-完整时序图)
  - [10. 设计亮点与注意事项](#10-设计亮点与注意事项)
- [第二部分：使用 AgentScope 实现 HITL](#第二部分使用-agentscope-实现-hitl)
  - [1. AgentScope 框架概述](#1-agentscope-框架概述)
  - [2. AgentScope 内置 HITL 能力详解](#2-agentscope-内置-hitl-能力详解)
  - [3. AgentScope 的 Hook 系统](#3-agentscope-的-hook-系统)
  - [4. Deep Research 多 Agent 项目架构设计](#4-deep-research-多-agent-项目架构设计)
  - [5. HITL 核心实现（自建方案）](#5-hitl-核心实现自建方案)
  - [6. 状态持久化与断点续传](#6-状态持久化与断点续传)
  - [7. 前端交互方案](#7-前端交互方案)
  - [8. 完整工作流示例](#8-完整工作流示例)
  - [9. 与 LangGraph 方案的对比](#9-与-langgraph-方案的对比)
  - [10. 最佳实践建议](#10-最佳实践建议)

---

## 第一部分：当前项目 HITL 实现方案

### 1. 架构总览

当前项目基于 **LangGraph** + **CopilotKit** + **FastAPI** 构建了一套完整的 HITL（Human-in-the-Loop）机制，核心依赖：

| 组件 | 作用 |
|------|------|
| **LangGraph `interrupt()`** | 在图执行流程中暂停，等待人工决策 |
| **Redis `AsyncRedisSaver`** | 持久化图状态（checkpoint），支持断点续传 |
| **AG-UI SSE 事件协议** | 后端向前端推送中断事件的标准协议 |
| **CopilotKit `useCopilotAction`** | 前端渲染审批 UI 并收集用户决策 |
| **FastAPI Router (`chat.py`)** | API 层：解析消息、转发中断、路由 resume |

整体链路分为 **7 层**，贯穿前后端：

```
工具装饰 → 图暂停 → 状态持久化 → 中断检测 → SSE 推送 → 前端渲染 → 结果回传恢复
```

---

### 2. 第一层：工具装饰器 —— `add_human_in_the_loop()`

**文件位置**：`app/modules/tools/common/human_in_the_loop.py`

任何需要人工审批的工具，在注册前都会被这个装饰器包裹。装饰器将原工具替换成一个 **先暂停、等用户决策、再执行** 的异步工具：

```python
def add_human_in_the_loop(tool: BaseTool, *, interrupt_config=None) -> BaseTool:
    """将任意工具包装为支持 HITL 的版本"""

    @create_tool(tool.name, description=tool.description, args_schema=tool.args_schema)
    async def call_tool_with_interrupt(config: RunnableConfig, **tool_input):
        # 步骤1：构造中断请求
        request: HumanInterrupt = {
            "action_request": {
                "action": tool.name,                # 工具名
                "agent": tool.metadata.get("agent", ""),  # 所属 Agent
                "args": json.loads(json.dumps(tool_input, ensure_ascii=False))
            },
            "config": {
                "allow_accept": True,    # 允许确认
                "allow_edit": True,      # 允许编辑
                "allow_respond": True,   # 允许自定义回复
            },
            "description": tool.description
        }

        # 步骤2：暂停执行 —— 这是整个 HITL 的触发点
        response = interrupt([request])

        # 步骤3：根据用户决策分流处理
        response_type = response.get("type")
        args = response.get("args", {})

        if response_type == "accept":
            return await tool.ainvoke(args, config)     # 原参数执行
        elif response_type == "edit":
            return await tool.ainvoke(args, config)     # 修改后参数执行
        elif response_type == "cancel":
            return TOOL_CALL_CANCEL_RESPONSE            # 取消，返回取消消息
        else:
            raise ValueError(f"不支持的响应类型: {response_type}")

    return call_tool_with_interrupt
```

**装饰器的注册方式**：

- **自动注册**（以 `apply_` 开头的工具自动加 HITL）：
  ```python
  # tools.py
  if str.startswith(tool.name, "apply_"):
      tool.metadata["need_human"] = True
      tool = add_human_in_the_loop(tool)
  ```

- **手动注册**（指定特定工具）：
  ```python
  # action_agents.py
  leave_apply_decorated = add_human_in_the_loop(submit_vacation_application)
  ```

**设计优势**：工具本身无需做任何修改，装饰器模式实现了完全无侵入的 HITL 接入。

---

### 3. 第二层：LangGraph `interrupt()` 机制

`interrupt([request])` 是整个 HITL 机制的核心触发点。它不是普通的函数调用，而是 LangGraph 的内置原语，会执行以下操作：

1. **抛出内部异常**（`GraphInterrupt`），立即中断当前节点的执行
2. **将中断信息写入 checkpoint**，保存图的完整状态（所有 channel values、消息历史、已完成的节点状态）
3. **让 `graph.ainvoke()` 提前返回**，返回包含 `__interrupt__` 字段的中间状态

```python
# LangGraph Orchestrator 中检测中断
result = await orchestrator_with_description.ainvoke(initial_state, config=config)

if "__interrupt__" in result:
    # 图被 interrupt() 暂停了，返回中断信息
    return orchestrator_distribute_messages, result
```

子图编译时绑定了 `AsyncRedisSaver` 作为 checkpointer：

```python
orchestrator_with_description = orchestrator_worker_builder.compile(
    checkpointer=checkpointer  # ← AsyncRedisSaver 实例
)
```

---

### 4. 第三层：状态持久化 —— `AsyncRedisSaver`

**文件位置**：`app/modules/model_base/AsyncRedisSaver.py`

使用 Redis 存储 LangGraph checkpoint，保障服务重启后仍能恢复。Redis 中使用了三种 key 来管理状态：

| Key 类型 | 格式 | 内容 |
|---------|------|------|
| **HASH** | `checkpoint:{thread_id}:{checkpoint_id}` | 序列化的图状态 + metadata + parent_id |
| **LIST** | `writes:{thread_id}:{checkpoint_id}` | 节点的写操作记录（pending writes） |
| **SET** | `idx:{thread_id}` | 所有 checkpoint_id 的集合（用于查找最新） |

**核心设计要点**：

- **TTL = 7200 秒**（2 小时）：所有 key 自动过期，防止 Redis 堆积
- **UUID6 单调 ID**：`max(checkpoint_ids)` 直接获取最新 checkpoint，无需额外排序
- **Redis Pipeline 批量写入**：减少网络往返延迟

```python
# 存储 checkpoint（aput 方法）
pipe = self.conn.pipeline()
pipe.hset(checkpoint_key, mapping={
    'checkpoint': serialized_checkpoint,
    'metadata': serialized_metadata,
    'parent_checkpoint_id': checkpoint_id or ''
})
pipe.expire(checkpoint_key, self.ttl)
pipe.sadd(index_key, checkpoint["id"])
pipe.expire(index_key, self.ttl)
await pipe.execute()
```

```python
# 获取最新 checkpoint（aget_tuple 方法）
checkpoint_ids = await self.conn.smembers(index_key)
target_id = max(id.decode() for id in checkpoint_ids)  # UUID6 单调性
```

---

### 5. 第四层：Pipeline 中断检测与 SSE 推送

#### 5.1 Pipeline 中断检测

**文件位置**：`app/modules/pipelines/stream_response_pipeline.py`

每个 Pipeline 组件执行后，都会检查是否发生了中断：

```python
for component in self.components:
    context = await component.execute(context)

    # 检查是否中断
    if context.is_interrupt():
        # 提取中断信息
        interrupt_json = self.extract_action_request(context.interrupt_event)
        interrupt_json_str = json.dumps(interrupt_json, ensure_ascii=False)

        # 存入数据库（type=INTERRUPT），供 resume 时查找
        answer_id = await self._save_answer_details(
            content="触发了一次用户干预操作",
            extra_meta_json=interrupt_json_str,
            type=AnswerDetailTypeEnum.INTERRUPT,
        )

        # 向前端推送中断事件
        yield {"interrupt_event": interrupt_json_str, "message_id": answer_id}
        break  # 停止后续组件的执行
```

#### 5.2 Router 将中断转换为 CopilotKit SSE 事件

**文件位置**：`app/api/routers/chat.py`

```python
async def _handle_interrupt(update, encoder):
    message_id = update.get("message_id")
    interrupt_json = json.loads(update.get("interrupt_event"))

    # 发送三个连续的 SSE 事件
    # ① ToolCallStartEvent：声明一个工具调用开始
    yield encoder.encode(ToolCallStartEvent(
        tool_call_id=message_id,
        tool_call_name=interrupt_json.get("action", "")
    ))

    # ② ToolCallArgsEvent：传递工具参数 + message_id（用于 resume 匹配）
    yield encoder.encode(ToolCallArgsEvent(
        tool_call_id=message_id,
        delta=json.dumps({
            "agent": interrupt_json.get("agent"),
            "tool_input": interrupt_json.get("args"),
            "messageId": message_id
        })
    ))

    # ③ ToolCallEndEvent：标记工具调用结束（等待用户操作）
    yield encoder.encode(ToolCallEndEvent(
        tool_call_id=message_id,
    ))
```

**为什么需要三个事件？** CopilotKit 前端将 `ToolCallStart → ToolCallArgs → ToolCallEnd` 这三个连续的 SSE 事件识别为一次需要人工介入的工具调用，从而触发 `useCopilotAction` 渲染对应的审批 UI。

---

### 6. 第五层：前端 CopilotKit 审批表单

#### 6.1 事件适配器

**文件位置**：`src/app/lib/event-request.ts`

`EventRouteAdapter` 负责将后端 SSE 事件转发给 CopilotKit runtime：

```typescript
case "TOOL_CALL_START":
    eventStream$.sendActionExecutionStart({
        actionExecutionId: message.toolCallId,
        actionName: message.toolCallName,
    });
    break;

case "TOOL_CALL_ARGS":
    eventStream$.sendActionExecutionArgs({
        actionExecutionId: message.toolCallId,
        args: message.delta,
    });
    break;

case "TOOL_CALL_END":
    eventStream$.sendActionExecutionEnd({
        actionExecutionId: message.toolCallId,
    });
    fetchEvents = false;  // ⚡ 停止读取 SSE 流，等待用户操作
    break;
```

#### 6.2 审批表单渲染

前端通过 `useCopilotAction` 注册工具处理器。以请假审批为例：

```typescript
// leave.tsx
useCopilotAction({
    name: "leave_apply",
    render: ({ args, handler }) => {
        return (
            <LeaveApplyForm
                data={args.tool_input}
                onApprove={() => handler({ type: "accept", args: args.tool_input })}
                onEdit={(editedArgs) => handler({ type: "edit", args: editedArgs })}
                onCancel={() => handler({ type: "cancel", args: {} })}
            />
        )
    }
})
```

**支持的 HITL 审批场景**：

| 前端组件 | 场景 | 文件 |
|---------|------|------|
| `useLeaveInterruptAction` | 请假申请 / 销假确认 / 销假取消 | `hrportal/leave.tsx` |
| `useEmpInfoModifyInterruptAction` | 个人信息修改 | `hrportal/employee-info-modify.tsx` |
| `useCertificateInterruptAction` | 证明开具（在职/收入/户口卡） | `hrportal/certificate.tsx` |
| `useVacationInterruptAction` | 请假 Demo | `chat-interrupt-for-vacation.tsx` |
| `usePurchaseInterruptAction` | 采购审批 Demo | `chat-interrupt-for-purchase.tsx` |

---

### 7. 第六层：结果回传与状态恢复

#### 7.1 前端发送 ResultMessage

用户操作后，CopilotKit 自动将决策结果封装为 `ResultMessage` 发回后端：

```json
{
    "messages": [
        { "type": "HumanMessage", "content": "申请请假" },
        {
            "type": "ResultMessage",
            "result": {
                "action": "leave_apply",
                "type": "accept",
                "args": { "leave_type": "年假", "days": 3 }
            }
        }
    ],
    "threadId": "01JXXXXXXXXX"  // ← 同一个 threadId！
}
```

#### 7.2 后端提取 resume 信息

```python
# chat.py
def _extract_user_info(messages):
    if messages and messages[-1].get('type') == 'ResultMessage':
        resume_result = messages[-1].get('result')
        # resume_result = {"action": "leave_apply", "type": "accept", "args": {...}}
    return user_message, message_id, ..., resume_result, ...
```

#### 7.3 Pipeline 恢复执行

```python
# stream_response_pipeline.py → pre_process()
if context.resume_result:
    # 恢复场景：不创建新用户消息，复用已有对话 ID
    answer_detail = await get_answer_detail_by_id(self.message_id)
    if answer_detail is not None:
        self.message_id = answer_detail.message_id
```

#### 7.4 LangGraph 恢复图状态

```python
# langgraph_orchestrator.py
if self.resume_result is not None:
    # 发送恢复命令——这会：
    # ① 用 thread_id 从 Redis 找到最新 checkpoint
    # ② 恢复所有 channel values，还原到中断前的节点
    # ③ 将 resume_result 作为 interrupt() 的返回值传回
    resume_command = Command(resume={
        "type": self.resume_type,
        "args": self.resume_args,
        "action": self.resume_action
    })
    result = await orchestrator_with_description.ainvoke(resume_command, config=config)
```

**Resume 的核心逻辑**：

```
LangGraph.ainvoke(Command(resume=...), config={thread_id: "01J..."})
    │
    ├─ 1. 用 thread_id 从 Redis 查找最新 checkpoint
    │     target_id = max(checkpoint_ids)   ← UUID6 单调性
    │
    ├─ 2. 反序列化图状态，将所有 channel_values 恢复
    │
    ├─ 3. 定位到 interrupt() 被调用的位置
    │
    ├─ 4. 将 resume_result 作为 interrupt() 的返回值注入
    │     response = interrupt([request])  ← 这行现在拿到返回值了！
    │
    └─ 5. 根据 response_type 决定执行路径
          accept → tool.ainvoke(args)      原参数执行
          edit   → tool.ainvoke(args)      修改后参数执行
          cancel → "操作已被用户取消"        返回取消消息
```

---

### 8. `thread_id` 的存储与传递

**核心结论：`thread_id` 存储在前端 CopilotKit 内存中，后端完全无状态。**

#### 生成

```typescript
// Zustand store 初始化时生成
currentConversationId: ulid()

// EventRouteAdapter 发请求时兜底
const threadId = threadIdFromRequest ?? ulid();
```

#### 传递

每次请求都同时放在两个位置发给后端：

```typescript
body: JSON.stringify({
    ...request,                      // 顶层 threadId（CopilotKit 标准字段）
    customParams: {
        conv_id: threadId,           // 自定义参数中也放一份
        ...
    },
})
```

#### Resume 为什么能对上？

```
第一次请求：
  前端生成 threadId = "01JAAA"  →  后端用 "01JAAA" 存 Redis

interrupt() 暂停后：
  前端渲染审批表单
  CopilotKit 内存中仍持有 threadId = "01JAAA"

Resume 请求：
  CopilotKit 自动带上同一个 threadId = "01JAAA"
  后端用这个 key 从 Redis 找到 checkpoint → 恢复执行 ✓
```

#### 各层存储对比

| 存储位置 | 存储内容 | 生命周期 |
|---------|---------|---------|
| **前端 CopilotKit 内存** | `threadId`（主要来源） | 一次会话期间全程持有 |
| **前端 Zustand store** | `currentConversationId` | 应用运行期间 |
| **Redis** | checkpoint 数据 | TTL 7200 秒 |
| **后端服务器** | ❌ 不存储 | 每次从请求参数读取 |

> **注意**：刷新页面会导致 CopilotKit 内存被清空，新生成的 `threadId` 在 Redis 中没有对应 checkpoint，无法 resume。

---

### 9. 完整时序图

```
用户发消息
    │
    ▼
FastAPI /ag-ui-endpoint [POST]
    │  提取 threadId (=conv_id) 作为 thread_id
    │  提取 messages → 判断是普通消息还是 ResultMessage
    ▼
StreamResponsePipeline.run()
    │  依次执行各组件
    ▼
LLM 决策调用 leave_apply 工具
    │  该工具已被 add_human_in_the_loop 装饰
    ▼
interrupt([request]) 被调用
    │  → LangGraph 抛出内部异常 (GraphInterrupt)
    │  → 当前图状态序列化，写入 Redis (AsyncRedisSaver)
    │  → TTL=7200s
    ▼
pipeline.context.is_interrupt() == True
    │  → 提取 interrupt_json (action + args + agent)
    │  → 存入 DB (type=INTERRUPT)
    │  → 获取 answer_id 作为 message_id
    ▼
yield {"interrupt_event": ..., "message_id": answer_id}
    │
    ▼
chat.py._handle_interrupt()
    │  → ToolCallStart (tool_call_id=message_id, name=action)
    │  → ToolCallArgs (delta={agent, tool_input, messageId})
    │  → ToolCallEnd (tool_call_id=message_id)
    ▼
前端 EventRouteAdapter 接收 SSE 事件
    │  → sendActionExecutionStart/Args/End
    │  → fetchEvents = false ← 停止读取 SSE
    ▼
CopilotKit 触发 useCopilotAction("leave_apply")
    │  → 渲染审批表单，展示请假参数
    ▼
用户点击"确认 / 修改 / 取消"
    │  → handler({type, args})
    ▼
前端发送新请求
    │  → messages 末尾含 ResultMessage
    │  → threadId 不变
    ▼
FastAPI 提取 resume_result
    │  → {"action": "leave_apply", "type": "accept", "args": {...}}
    ▼
Pipeline 检测到 resume_result → 跳过创建新用户消息
    ▼
LangGraphOrchestrator 发送 Command(resume=...)
    │  → Redis 恢复 checkpoint
    │  → interrupt() 返回 resume_result
    ▼
call_tool_with_interrupt 继续执行
    │  accept → 调用真实工具（原参数）
    │  edit   → 调用真实工具（修改后参数）
    │  cancel → 返回"操作已被用户取消"
    ▼
后续节点继续流转，最终结果返回给用户
```

---

### 10. 设计亮点与注意事项

#### 设计亮点

| 设计点 | 实现方式 | 目的 |
|-------|---------|------|
| **工具无侵入** | 装饰器模式 `add_human_in_the_loop()` | 任何工具无需修改即可接入 HITL |
| **状态不丢失** | Redis checkpoint + UUID6 单调 ID | 服务重启后仍可 resume |
| **前后端解耦** | AG-UI SSE 事件协议 | 前端只需响应标准事件，不感知后端实现 |
| **并发安全** | `thread_id = conv_id` 隔离 | 多用户并发不互相干扰 |
| **超时自动清理** | Redis TTL = 7200s | 未处理的 interrupt 自动过期 |
| **自动识别** | 以 `apply_` 开头的工具自动加 HITL | 减少开发者的配置负担 |

#### 注意事项

- **刷新页面 = 丢失中断状态**：CopilotKit 内存被清空，新 `threadId` 在 Redis 中无对应 checkpoint
- **后端完全无状态**：每次请求从入参中读取 `threadId`，Redis 仅做存储介质
- **多标签页安全**：每个标签页 CopilotKit 实例独立，`threadId` 不同，互不干扰
- **Resume 幂等性**：同一个 checkpoint 只能 resume 一次，resume 后 checkpoint 向前推进

---

## 第二部分：使用 AgentScope 实现 HITL

### 1. AgentScope 框架概述

AgentScope 是阿里通义实验室开源的**面向生产的智能体开发框架**（v1.0+），核心特点：

- **事件驱动架构**：统一的事件系统贯穿 Agent 全生命周期
- **Hook 系统**：在推理、工具调用、回复等关键节点挂载自定义逻辑
- **Pipeline 语法糖**：`sequential_pipeline`、`fanout_pipeline` 快速编排多 Agent
- **MsgHub**：发布-订阅模式实现多 Agent 间异步通信
- **Workstation**：可视化拖拽编排（在线 IDE）
- **内置 HITL 能力**：`UserAgent` + `interrupt()` + `handle_interrupt` + `JSONSession` 持久化

> **重要更正**：AgentScope **有内置的 HITL 原语**，早期版本本文档所述的"没有内置 interrupt()"不准确。AgentScope 提供了两套 HITL 机制：① `UserAgent` 主动请求人类输入、② `interrupt()` + `handle_interrupt` 实时中断与恢复。但这些机制与 LangGraph 的 `interrupt()` + `Command(resume=...)` 模式有本质差异（详见下文对比）。

---

### 2. AgentScope 内置 HITL 能力详解

在讨论自定义方案之前，必须先了解 AgentScope 自带了什么。

#### 2.1 UserAgent — 主动请求人类输入

AgentScope 内置了一个 `UserAgent` 类型，专门用于在多 Agent 对话流中**暂停并等待人类输入**。它通过 `UserInputBase` 抽象来捕获用户响应：

```
Pipeline 执行中
    │
    ▼
UserAgent 被调用
    ├── 暂停当前流程
    ├── 通过 UserInput 向用户展示问题
    ├── 等待用户输入
    └── 拿到输入后 → 继续流水线
```

支持两种前端实现：

| 实现类 | 说明 | 适用场景 |
|--------|------|---------|
| `TerminalUserInput` | 使用 Python `input()` 控制台交互，支持 JSON Schema 结构化引导 | 本地开发调试 |
| `StudioUserInput` | 通过 Socket.IO 连接 AgentScope Studio（Web 界面） | 生产环境 Web 端 |

对于简单的审批场景（如"是否确认执行"），**不需要自己写 `asyncio.Event` 等待逻辑**，直接用 `UserAgent` 即可：

```python
from agentscope.agent import UserAgent

user_agent = UserAgent(name="HumanReviewer")

# 在 Pipeline 中穿插 UserAgent
async with MsgHub([orchestrator, search_agent, user_agent]) as hub:
    search_result = await search_agent(query_msg)
    # search_agent 查到敏感数据 → 让人类审查
    human_decision = await user_agent(Msg("assistant", f"查到以下数据，是否采用？\n{search_result}", "assistant"))
    # 根据 human_decision 的内容决定后续流程
```

#### 2.2 `interrupt()` + `handle_interrupt` — 实时中断

AgentScope 的 `AgentBase` 内置了基于 `asyncio.CancelledError` 的中断机制，**不需要手动实现**：

```python
class AgentBase:
    async def __call__(self, *args: Any, **kwargs: Any) -> Msg:
        reply_msg: Msg | None = None
        try:
            self._reply_task = asyncio.current_task()
            reply_msg = await self.reply(*args, **kwargs)
        except asyncio.CancelledError:
            # ★ 内置中断处理 —— 子类重写 handle_interrupt 即可
            reply_msg = await self.handle_interrupt(*args, **kwargs)
        ...
```

**调用方式**：`agent.interrupt()` → 取消当前 `reply` 任务 → 触发 `handle_interrupt` → 返回中断状态消息。

```python
# Agent 正在执行长时间任务
task = asyncio.create_task(agent(user_input))

# 用户在 Studio 界面点击 "停止" 或 Ctrl+C
agent.interrupt()
# → asyncio.CancelledError 被 AgentBase.__call__ 捕获
# → 调用 handle_interrupt()，返回默认中断消息
# → Agent 的记忆和状态被正确保存
```

**中断后的状态保持**：

- 中断发生时，Agent 的**记忆（memory）和上下文被完整保留**
- `ReActAgent` 具备完善的中断逻辑，确保不会丢失对话流
- 结合 `JSONSession` 等 Session 机制，**执行完成后自动持久化状态**，下次启动可从断点恢复
- 支持在 Pipeline 中传播中断信号（`sequential_pipeline`、`fanout_pipeline` 都会响应中断）

#### 2.3 内置 HITL 与 LangGraph 的本质差异

虽然 AgentScope 有内置的 `interrupt()`，但它和 LangGraph 的实现模式完全不同：

| 维度 | LangGraph `interrupt()` | AgentScope `interrupt()` |
|------|------------------------|--------------------------|
| **模式** | **暂停模式**（pause-and-resume） | **取消模式**（cancel-and-reinvoke） |
| **行为** | 代码执行到 `interrupt()` 时**悬浮暂停**，等 `Command(resume=...)` **同一点继续** | 取消当前 `reply` 任务，`handle_interrupt` 返回消息，**下次调用 Agent 时从记忆恢复** |
| **状态恢复** | 框架自动序列化所有 channel_values → Redis → 反序列化 → 精确还原 | 依赖 Agent 自身的记忆（memory）和 Session 持久化 → 再次调用时加载 |
| **审批流实现** | `interrupt()` 阻塞 → 前端确认 → `resume` 返回值 → 继续执行后续代码 | `pre_acting` hook + `UserAgent` → 获取用户输入 → 决定是否执行工具 |

**核心差异用代码说明**：

```python
# ═══ LangGraph 模式（暂停-恢复）═══
async def tool_with_hitl(config, **args):
    response = interrupt([request])    # ★ 在这里暂停！
    # ... 用户操作完 ...
    if response["type"] == "accept":   # ★ 同一次调用继续
        return await tool.ainvoke(args)

# ═══ AgentScope 模式（取消-再调用）═══
class MyAgent(ReActAgent):
    async def handle_interrupt(self, *args, **kwargs) -> Msg:
        # ★ 被取消后，返回中断消息
        return Msg("assistant", "操作已中断，输入 resume 继续", "assistant")
    
    def pre_acting(self, kwargs):
        # ★ 或者在工具调用前用 UserAgent 请求确认
        if is_sensitive(kwargs["tool_name"]):
            user_msg = await user_agent.ask("确认执行？")
            if user_msg == "no":
                return None  # 阻止工具调用
        return kwargs
```

#### 2.4 什么时候用内置，什么时候自建

| 场景 | 推荐方案 | 原因 |
|------|---------|------|
| 工具调用前简单审批（是否执行） | AgentScope 内置 `pre_acting` + `UserAgent` | 不需要断点续传，开箱即用 |
| 实时打断 Agent 执行 | AgentScope 内置 `interrupt()` + `handle_interrupt` | 框架原生支持 |
| Web 端人工输入 | AgentScope 内置 `StudioUserInput` | 已集成 Socket.IO |
| Pipeline 级多步骤断点续传 | 自建 `CheckpointStore` + `HITLManager` | AgentScope 无精确到代码行的恢复能力 |
| 需要"在代码中间暂停等用户，再继续" | 自建 `asyncio.Event` 或切回 LangGraph | AgentScope 的 `interrupt()` 是取消模式 |

---

### 3. AgentScope 的 Hook 系统

AgentScope 的 Hook 系统是 HITL 实现的核心基础。它在 Agent 执行的关键节点提供了**双向拦截**能力（前置修改入参、后置修改结果）。

#### 3.1 ReAct Agent 执行生命周期与 Hook 挂载点

```
用户输入
    │
    ├─→ pre_observe           ← 观察输入前
    ├─→ observe               ← 观察输入
    ├─→ post_observe          ← 观察输入后
    │
    ├─→ pre_reply             ← 回复前
    │    ├─→ pre_reasoning    ← LLM 推理前
    │    ├─→ _reasoning       ← LLM 推理（调用大模型）
    │    ├─→ post_reasoning   ← LLM 推理后 ⭐ HITL 关键点：可审查推理结果
    │    ├─→ pre_acting       ← 工具调用前 ⭐ HITL 关键点：可拦截工具执行
    │    ├─→ _acting          ← 实际执行工具
    │    ├─→ post_acting      ← 工具执行后 ⭐ HITL 关键点：可修正执行结果
    │    ├─→ ...（循环直到不需要工具）
    ├─→ reply                 ← 生成最终回复
    ├─→ post_reply            ← 回复后
    │
    ├─→ pre_print             ← 输出前
    ├─→ print                 ← 输出
    ├─→ post_print            ← 输出后
    │
    └─→ on_error              ← 异常时（可用于兜底）
```

#### 3.2 Hook 注册 API

```python
from agentscope.agent import ReActAgent

# 方法1：实例级 Hook（仅影响单个 Agent）
agent.register_instance_hook("pre_acting", "my_audit", audit_function)

# 方法2：类级 Hook（影响所有 Agent 实例）
ReActAgent.register_class_hook("pre_acting", "global_safety", global_safety_check)

# 方法3：通过继承重写
class MyAgent(ReActAgent):
    def pre_acting(self, kwargs):
        # 自定义拦截逻辑
        return kwargs
```

#### 3.3 关键 Hook 签名

```python
# 工具调用前拦截（最重要）
def pre_acting(self: AgentBase, kwargs: dict) -> dict | None:
    """
    kwargs 包含：
        - tool_name: str       # 即将调用的工具名
        - tool_args: dict      # 工具参数
        - ...                  # 其他上下文信息
    返回：
        - dict: 修改后的 kwargs（继续执行）
        - None: 阻止本次工具调用
    """

# LLM 推理后审查
def post_reasoning(self: AgentBase, kwargs: dict, output: Any) -> Any | None:
    """
    output: LLM 的原始推理结果（包含 tools_to_call 等）
    返回：
        - 修改后的 output（继续执行）
        - None: 阻止后续动作
    """

# 工具执行后修正
def post_acting(self: AgentBase, kwargs: dict, output: Any) -> Any | None:
    """
    output: 工具执行的原始结果
    返回：
        - 修改后的 output
    """
```

---

### 4. Deep Research 多 Agent 项目架构设计

#### 4.1 场景定义

Deep Research 是一种典型的复杂多步骤研究型 Agent 应用场景：

```
用户提出研究问题
    → 问题分解（拆成多个子问题）
    → 并行搜索（多个搜索 Agent 并发执行）
    → 信息综合（阅读、筛选、交叉验证）
    → 深度扩展（对关键点深入挖掘）
    → 反思改进（检查结果质量，必要时重试）
    → 报告生成（结构化最终报告）
```

**HITL 在这个场景中的介入点**：

| 阶段 | HITL 触发条件 | 人工决策内容 |
|------|-------------|------------|
| 问题分解后 | 分解结果质量不确定 | 审查子问题列表，修改/补充/删除 |
| 信息综合前 | 搜索到敏感或高风险信息 | 确认是否使用这些信息源 |
| 报告生成前 | 数据涉及业务决策 | 审核中间结论，修正方向 |
| 工具调用时 | 调用外部 API、数据库、文件系统 | 确认操作安全性 |

#### 4.2 项目结构

```
deep-research-project/
├── agents/
│   ├── orchestrator.py       # 主编排 Agent（任务分解 + 调度）
│   ├── search_agent.py       # 搜索 Agent（调用搜索工具）
│   ├── analyst_agent.py      # 分析 Agent（信息综合 + 深度扩展）
│   └── report_agent.py       # 报告生成 Agent（结构化输出）
├── hitl/
│   ├── hitl_manager.py       # HITL 管理器（中断/恢复核心逻辑）
│   ├── checkpoint_store.py   # 状态持久化（Redis/文件）
│   ├── hooks.py              # HITL Hook 函数集合
│   └── approval_queue.py     # 审批队列（支持多人审批）
├── pipeline/
│   └── research_pipeline.py  # 研究 Pipeline 编排
├── tools/
│   ├── search_tool.py        # Web 搜索工具
│   ├── browser_tool.py       # 网页浏览工具
│   └── database_tool.py      # 数据库查询工具（需 HITL）
├── frontend/
│   └── approval_ui.py        # 审批 UI（Web/CLI）
├── config.yaml                # 配置文件
└── main.py                    # 入口
```

#### 4.3 核心工作流设计

```python
# research_pipeline.py
class DeepResearchPipeline:
    """Deep Research 主 Pipeline"""

    def __init__(self):
        self.orchestrator = OrchestratorAgent()
        self.searchers = [SearchAgent(f"searcher_{i}") for i in range(3)]
        self.analyst = AnalystAgent()
        self.reporter = ReportAgent()
        self.hitl_manager = HITLManager()

    async def execute(self, question: str):
        # 阶段1：问题分解 —— HITL 审查子问题
        subtasks = await self.orchestrator.decompose(question)
        approved_subtasks = await self.hitl_manager.review_subtasks(subtasks)

        # 阶段2：并行搜索 —— Hook 拦截敏感工具调用
        search_results = await self._parallel_search(approved_subtasks)

        # 阶段3：信息综合 —— HITL 审查中间结论
        synthesis = await self.analyst.synthesize(search_results)
        approved_synthesis = await self.hitl_manager.review_synthesis(synthesis)

        # 阶段4：深度扩展
        expanded = await self.analyst.deep_expand(approved_synthesis)

        # 阶段5：报告生成
        report = await self.reporter.generate(expanded)

        return report
```

---

### 5. HITL 核心实现

#### 5.1 HITLManager 设计

Goroutine 用 Python asyncio + 事件循环实现**同步阻塞式等待**：

```python
# hitl/hitl_manager.py
import asyncio
import json
import uuid
from enum import Enum
from typing import Any, Dict, Optional, Callable
from dataclasses import dataclass, field

class ApprovalDecision(Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"

@dataclass
class InterruptRequest:
    """中断请求数据结构"""
    request_id: str
    agent_name: str
    action: str                     # 触发中断的操作名
    args: Dict[str, Any]            # 操作参数
    description: str                # 操作描述
    created_at: float
    config: Dict[str, bool] = field(default_factory=lambda: {
        "allow_accept": True,
        "allow_edit": True,
        "allow_reject": True,
    })

@dataclass
class InterruptResponse:
    """用户决策结果"""
    request_id: str
    decision: ApprovalDecision
    edited_args: Dict[str, Any] = field(default_factory=dict)
    comment: str = ""

class HITLManager:
    """
    HITL 管理器 —— 核心中断/恢复引擎

    工作原理：
    1. Agent 通过 Hook 调用 interrupt() → 创建中断请求 → 等待用户决策
    2. 用户通过 UI 提交决策 → resolve() 唤醒等待
    3. Agent 拿到决策结果 → 继续或终止执行
    """

    def __init__(self, frontend_callback: Callable = None):
        # 等待中的中断请求 {request_id: asyncio.Event}
        self._pending_events: Dict[str, asyncio.Event] = {}
        # 已完成的决策结果 {request_id: InterruptResponse}
        self._results: Dict[str, InterruptResponse] = {}
        # 前端通知回调（WebSocket/SSE 推送）
        self._frontend_callback = frontend_callback

    async def interrupt(
        self,
        agent_name: str,
        action: str,
        args: Dict[str, Any],
        description: str = "",
        config: Dict[str, bool] = None,
    ) -> InterruptResponse:
        """
        暂停 Agent 执行，等待用户决策。

        这是一个异步阻塞调用：
        - 会一直等待直到用户提交决策
        - 等待期间不占用 CPU
        """
        request_id = str(uuid.uuid4())
        request = InterruptRequest(
            request_id=request_id,
            agent_name=agent_name,
            action=action,
            args=args,
            description=description,
            created_at=asyncio.get_event_loop().time(),
            config=config or {"allow_accept": True, "allow_edit": True, "allow_reject": True},
        )

        # 1. 创建事件用于等待
        event = asyncio.Event()
        self._pending_events[request_id] = event

        # 2. 通知前端展示审批 UI
        if self._frontend_callback:
            await self._frontend_callback(request)

        print(f"\n[HITL] ⏸️  暂停 Agent「{agent_name}」")
        print(f"[HITL] 操作: {action}")
        print(f"[HITL] 参数: {json.dumps(args, ensure_ascii=False, indent=2)}")
        print(f"[HITL] 等待用户决策... (request_id={request_id})\n")

        # 3. 阻塞等待用户决策
        await event.wait()

        # 4. 获取结果
        response = self._results.pop(request_id)
        self._pending_events.pop(request_id)

        print(f"[HITL] ▶️  收到决策: {response.decision.value}")
        return response

    def resolve(self, request_id: str, response: InterruptResponse):
        """
        用户提交决策后，唤醒等待的 Agent。

        此方法通常由前端 API 端点调用。
        """
        if request_id not in self._pending_events:
            raise ValueError(f"未知的中断请求: {request_id}")

        self._results[request_id] = response
        self._pending_events[request_id].set()  # 唤醒 interrupt() 中的 await


# 全局 HITL 管理器实例（单例模式）
hitl_manager = HITLManager()
```

#### 5.2 HITL Hook 们实现

```python
# hitl/hooks.py
from typing import Optional, Dict, Any
from agentscope.agent import AgentBase
from .hitl_manager import hitl_manager, ApprovalDecision

# 需要 HITL 审批的敏感工具列表
SENSITIVE_TOOLS = {
    "database_query": "数据库查询",
    "file_write": "文件写入",
    "api_call": "外部 API 调用",
    "send_email": "发送邮件",
    "execute_sql": "SQL 执行",
}

# 需要审查推理结果的模式
SENSITIVE_PATTERNS = [
    "delete", "drop", "truncate", "rm -rf",
    "production", "prod_db", "机密", "绝密",
]


# ============= 工具调用前 HITL（pre_acting）=============
def hitl_pre_acting(self: AgentBase, kwargs: dict) -> Optional[dict]:
    """
    在工具调用前检查：
    - 如果工具在敏感列表中 → 暂停，等待用户审批
    - 审批通过 → 原参数或修改后参数继续执行
    - 审批拒绝 → 阻止调用，返回取消信息
    """
    tool_name = kwargs.get("tool_name", "")
    tool_args = kwargs.get("tool_args", {})

    # 判断是否需要 HITL
    if tool_name not in SENSITIVE_TOOLS:
        return kwargs  # 非敏感工具，直接放行

    # 发起中断：暂停 Agent 执行
    response = asyncio_run_sync(
        hitl_manager.interrupt(
            agent_name=self.name,
            action=tool_name,
            args=tool_args,
            description=f"即将调用敏感工具「{SENSITIVE_TOOLS[tool_name]}」",
            config={
                "allow_accept": True,
                "allow_edit": True,
                "allow_reject": True,
            }
        )
    )

    # 根据决策处理
    if response.decision == ApprovalDecision.APPROVE:
        # 确认：原参数继续
        return kwargs
    elif response.decision == ApprovalDecision.EDIT:
        # 编辑：用修改后的参数替换
        kwargs["tool_args"] = response.edited_args
        return kwargs
    elif response.decision == ApprovalDecision.REJECT:
        # 拒绝：阻止工具调用（返回 None）
        print(f"[HITL] ❌ 用户拒绝了「{tool_name}」调用")
        return None


# ============= 推理后 HITL（post_reasoning）=============
def hitl_post_reasoning(self: AgentBase, kwargs: dict, output: Any) -> Any:
    """
    在 LLM 推理后检查：
    - 如果推理结果涉及敏感操作 → 暂停，等待用户审查
    """
    reasoning_text = str(output)

    # 检查是否涉及敏感内容
    is_sensitive = any(
        pattern.lower() in reasoning_text.lower()
        for pattern in SENSITIVE_PATTERNS
    )

    if not is_sensitive:
        return output

    response = asyncio_run_sync(
        hitl_manager.interrupt(
            agent_name=self.name,
            action="reasoning_review",
            args={"reasoning": reasoning_text},
            description="LLM 推理涉及敏感操作，请审查",
            config={
                "allow_accept": True,
                "allow_edit": True,
                "allow_reject": False,
            }
        )
    )

    if response.decision == ApprovalDecision.APPROVE:
        return output
    elif response.decision == ApprovalDecision.EDIT:
        # 用户可以修改推理方向（通过 edited_args）
        return response.edited_args.get("reasoning", output)


# ============= 工具执行后 HITL（post_acting）=============
def hitl_post_acting(self: AgentBase, kwargs: dict, output: Any) -> Any:
    """
    工具执行后审查结果——例如检查是否返回了敏感数据。
    """
    tool_name = kwargs.get("tool_name", "")

    if tool_name == "database_query":
        # 数据库查询结果可能包含敏感数据，让用户确认
        response = asyncio_run_sync(
            hitl_manager.interrupt(
                agent_name=self.name,
                action="review_query_result",
                args={"tool": tool_name, "result_preview": str(output)[:500]},
                description="数据库查询返回了结果，请确认是否可展示给用户",
                config={"allow_accept": True, "allow_edit": False, "allow_reject": True},
            )
        )
        if response.decision == ApprovalDecision.REJECT:
            return "⚠️ 查询结果已被审核人员屏蔽"


# ============= 辅助函数：在同步 Hook 中调用异步 interrupt =============
def asyncio_run_sync(coro):
    """在同步上下文中运行异步协程"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果当前在事件循环中，使用 run_coroutine_threadsafe
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=300)  # 5 分钟超时
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)
```

#### 5.3 在 AgentScope Pipeline 中注册 Hook

```python
# main.py
from agentscope.agent import ReActAgent
from agentscope.pipeline import sequential_pipeline, fanout_pipeline
from agentscope.message import Msg

from hitl.hooks import hitl_pre_acting, hitl_post_reasoning, hitl_post_acting
from agents.orchestrator import OrchestratorAgent
from agents.search_agent import SearchAgent
from agents.analyst_agent import AnalystAgent
from agents.report_agent import ReportAgent


async def deep_research_with_hitl(question: str):
    # 创建 Agent
    orchestrator = OrchestratorAgent(
        name="ResearchOrchestrator",
        sys_prompt="你是深度研究项目的协调者...",
        model_config_name="qwen_max",
    )
    searcher_1 = SearchAgent(name="Searcher_1")
    searcher_2 = SearchAgent(name="Searcher_2")
    analyst = AnalystAgent(name="Analyst")
    reporter = ReportAgent(name="Reporter")

    # ============ 注册 HITL Hook（关键步骤）============
    # 方式1：为特定 Agent 注册实例级 Hook
    analyst.register_instance_hook("pre_acting", "hitl_tool_check", hitl_pre_acting)

    # 方式2：为所有 Agent 注册类级 Hook（全局生效）
    ReActAgent.register_class_hook("post_reasoning", "hitl_reasoning_review", hitl_post_reasoning)
    ReActAgent.register_class_hook("post_acting", "hitl_result_review", hitl_post_acting)

    # ============ Pipeline 编排 ============
    from agentscope.pipeline import MsgHub

    async with MsgHub(
        participants=[orchestrator, searcher_1, searcher_2, analyst, reporter]
    ) as hub:
        # 阶段1：Orchestrator 分解任务
        user_msg = Msg("user", question, "user")
        plan_msg = await orchestrator(await user_msg)

        # 阶段2：并行搜索
        search_results = await fanout_pipeline(
            [searcher_1, searcher_2],
            plan_msg,
        )
        # 如果搜索工具在 SENSITIVE_TOOLS 中，这里会自动触发 HITL

        # 阶段3：分析师综合信息
        analysis_msg = Msg("user", f"请综合以下搜索结果：\n{search_results}", "user")
        synthesis = await analyst(await analysis_msg)
        # 如果分析过程中 LLM 推理涉及敏感内容，会自动暂停

        # 阶段4：报告生成
        report_msg = Msg("user", f"请生成最终报告：\n{synthesis}", "user")
        report = await reporter(await report_msg)

    return report
```

---

### 6. 状态持久化与断点续传

AgentScope 本身没有像 LangGraph 那样的内置 Checkpoint 系统（`JSONSession` 仅支持执行结束后保存，不支持执行中暂停）。对于需要精确断点续传的复杂场景，可以通过状态序列化来实现。

#### 6.1 CheckpointStore 设计

```python
# hitl/checkpoint_store.py
import json
import pickle
import redis.asyncio as redis
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class CheckpointState:
    """可序列化的 Agent 状态快照"""
    session_id: str
    agent_name: str
    pipeline_step: int            # 当前 Pipeline 阶段
    conversation_history: list    # 对话历史
    agent_memory: list            # Agent 内部记忆
    interrupt_request_id: str     # 当前中断请求 ID
    metadata: dict


class CheckpointStore:
    """
    状态持久化存储——支持中断后恢复执行。

    存储方案（三选一）：
    - Redis：生产环境推荐
    - SQLite：本地开发
    - 文件系统（pickle）：快速原型
    """

    def __init__(self, backend="redis", redis_url="redis://localhost:6379"):
        self.backend = backend
        if backend == "redis":
            self.redis_client = redis.from_url(redis_url, decode_responses=False)
        elif backend == "file":
            import os
            self.checkpoint_dir = "./checkpoints"
            os.makedirs(self.checkpoint_dir, exist_ok=True)
        self.ttl = 7200  # 2 小时过期

    async def save(self, state: CheckpointState):
        """保存 Agent 状态快照"""
        data = pickle.dumps(state)

        if self.backend == "redis":
            key = f"checkpoint:{state.session_id}:{state.pipeline_step}"
            await self.redis_client.set(key, data, ex=self.ttl)
            # 同时维护索引
            await self.redis_client.sadd(f"idx:{state.session_id}", key)
        elif self.backend == "file":
            path = f"{self.checkpoint_dir}/{state.session_id}_{state.pipeline_step}.pkl"
            with open(path, "wb") as f:
                f.write(data)

    async def load(self, session_id: str, pipeline_step: int = None) -> Optional[CheckpointState]:
        """加载 Agent 状态快照"""
        if self.backend == "redis":
            if pipeline_step is not None:
                key = f"checkpoint:{session_id}:{pipeline_step}"
                data = await self.redis_client.get(key)
                return pickle.loads(data) if data else None
            else:
                # 获取最新 checkpoint
                index_key = f"idx:{session_id}"
                keys = await self.redis_client.smembers(index_key)
                if not keys:
                    return None
                latest_key = max(k.decode() for k in keys)
                data = await self.redis_client.get(latest_key)
                return pickle.loads(data) if data else None
        elif self.backend == "file":
            import glob
            files = glob.glob(f"{self.checkpoint_dir}/{session_id}_*.pkl")
            if not files:
                return None
            latest = max(files)
            with open(latest, "rb") as f:
                return pickle.load(f)

    async def delete_session(self, session_id: str):
        """清理整个会话的 checkpoint"""
        if self.backend == "redis":
            index_key = f"idx:{session_id}"
            keys = await self.redis_client.smembers(index_key)
            if keys:
                await self.redis_client.delete(*keys)
            await self.redis_client.delete(index_key)

checkpoint_store = CheckpointStore()
```

#### 6.2 支持断点续传的 Pipeline

```python
# pipeline/research_pipeline.py

class ResumableResearchPipeline:
    """
    支持 HITL 断点续传的研究 Pipeline。

    每个阶段执行前保存 checkpoint，
    中断发生后可以从最后一个 checkpoint 恢复。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.hitl = HITLManager()
        self.checkpoint = CheckpointStore()

    async def execute_or_resume(
        self,
        question: str,
        resume_request_id: str = None,
        resume_response: InterruptResponse = None,
    ):
        """
        智能入口：
        - 如果提供了 resume 参数 → 从 checkpoint 恢复并继续
        - 如果没有 → 从头开始执行
        """
        if resume_request_id and resume_response:
            # 恢复路径
            last_checkpoint = await self.checkpoint.load(self.session_id)
            if not last_checkpoint:
                raise ValueError("未找到可恢复的 checkpoint")
            # 唤醒等待的 Agent
            self.hitl.resolve(resume_request_id, resume_response)
            # 从断点继续执行（Agent 会自动从 interrupt() 处恢复）
            return await self._continue_from_step(last_checkpoint.pipeline_step)
        else:
            # 全新执行
            return await self._execute_full(question)

    async def _execute_full(self, question: str):
        """完整执行流程（带 checkpoint 和 HITL）"""
        step = 0

        try:
            # 步骤1：分解
            step = 1
            await self._save_checkpoint(step, {...})
            subtasks = await self._decompose_with_hitl(question)

            # 步骤2：并行搜索
            step = 2
            await self._save_checkpoint(step, {...})
            results = await self._search_with_hitl(subtasks)

            # 步骤3：综合
            step = 3
            await self._save_checkpoint(step, {...})
            synthesis = await self._synthesize_with_hitl(results)

            # 步骤4：报告
            step = 4
            report = await self._generate_report(synthesis)

            # 完成：清理 checkpoint
            await self.checkpoint.delete_session(self.session_id)
            return report

        except InterruptedException as e:
            # HITL 中断：状态已通过 checkpoint 保存
            # 向前端返回中断信息
            return {
                "status": "interrupted",
                "request_id": e.request_id,
                "agent": e.agent_name,
                "action": e.action,
                "args": e.args,
                "step": step,
            }

    async def _continue_from_step(self, start_step: int):
        """从指定步骤恢复执行"""
        # 重新构建 Pipeline 状态
        # 由于 Agent 本身在 interrupt() 处阻塞，
        # 调用 resolve() 后会自动从原位置继续
        # 此处处理 Pipeline 层面的编排恢复
        pass

    async def _save_checkpoint(self, step: int, state: dict):
        await self.checkpoint.save(CheckpointState(
            session_id=self.session_id,
            agent_name="research_pipeline",
            pipeline_step=step,
            conversation_history=state.get("history", []),
            agent_memory=[],
            interrupt_request_id="",
            metadata={"timestamp": time.time()},
        ))
```

---

### 7. 前端交互方案

除了 AgentScope 内置的 `StudioUserInput`（基于 Socket.IO）外，对于需要自定义审批 UI 的复杂场景，可以使用以下方案。

#### 7.1 方案一：WebSocket（推荐用于 AgentScope）

```python
# frontend/approval_server.py
from fastapi import FastAPI, WebSocket
import json
from hitl.hitl_manager import hitl_manager, ApprovalDecision, InterruptResponse

app = FastAPI()

# WebSocket 连接管理
active_connections: dict[str, WebSocket] = {}

# 设置 HITL 管理器的前端回调
async def notify_frontend(request):
    """当有中断请求时，通过 WebSocket 推送给前端"""
    session_id = request.args.get("session_id", "default")
    ws = active_connections.get(session_id)
    if ws:
        await ws.send_json({
            "type": "hitl_interrupt",
            "request_id": request.request_id,
            "agent": request.agent_name,
            "action": request.action,
            "args": request.args,
            "description": request.description,
        })

hitl_manager._frontend_callback = notify_frontend


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    active_connections[session_id] = websocket
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "hitl_response":
                # 前端提交了审批决策
                response = InterruptResponse(
                    request_id=data["request_id"],
                    decision=ApprovalDecision(data["decision"]),
                    edited_args=data.get("edited_args", {}),
                    comment=data.get("comment", ""),
                )
                hitl_manager.resolve(data["request_id"], response)
                await websocket.send_json({"type": "ack", "status": "ok"})
    except Exception:
        active_connections.pop(session_id, None)
```

#### 7.2 方案二：HTTP Polling + REST API

```python
# 前端轮询接口（用于无法建立 WebSocket 的场景）
@app.get("/api/hitl/pending/{session_id}")
async def get_pending_interrupts(session_id: str):
    """查询当前是否有待处理的 HITL 请求"""
    pending = []
    for req_id, event in hitl_manager._pending_events.items():
        if not event.is_set():
            pending.append({"request_id": req_id, "session_id": session_id})
    return {"pending": pending}

@app.post("/api/hitl/approve")
async def approve_interrupt(request_id: str, decision: str, edited_args: dict = None):
    """提交 HITL 决策"""
    response = InterruptResponse(
        request_id=request_id,
        decision=ApprovalDecision(decision),
        edited_args=edited_args or {},
    )
    hitl_manager.resolve(request_id, response)
    return {"status": "ok"}
```

#### 7.3 前端审批 UI 设计要点

```typescript
// 前端审批组件的数据流
type HitlInterrupt = {
    request_id: string;
    agent: string;
    action: string;
    args: Record<string, any>;
    description: string;
};

// 审批操作
type Decision = "approve" | "edit" | "reject";

// 用户决策后：
// 1. accept  → 原参数发回后端
// 2. edit    → 修改后的参数发回后端
// 3. reject  → 通知后端取消操作
```

---

### 8. 完整工作流示例

下面是一个完整的 Deep Research 执行流程，展示 HITL 在整个过程中的作用：

```
用户问题：「分析 2025 年 AI Agent 框架的技术趋势，并给出选型建议」

═══════════════════════════════════════════════════════
阶段1：任务分解 (OrchestratorAgent)
═══════════════════════════════════════════════════════
  LLM 推理 → 拆分为 4 个子任务：
    1. 调研 LangGraph 技术路线
    2. 调研 AgentScope 技术路线
    3. 调研 CrewAI / AutoGen 等竞品
    4. 对比分析并给出选型建议

  🔍 post_reasoning Hook 检查：
     → 推理结果正常，无敏感内容 → 放行

───────────────────────────────────────────────────────
阶段2：并行搜索 (SearchAgent × 3)
───────────────────────────────────────────────────────
    Searcher_1 搜索 LangGraph → 调用 browser_tool、search_tool
    Searcher_2 搜索 AgentScope → 调用 search_tool
    Searcher_3 搜索竞品         → 调用 search_tool、database_query

    ⚠️ Searcher_3 尝试调用 database_query：
       → pre_acting Hook 检测到敏感工具
       → 🔴 HITL 中断触发！

    ┌─────────────────────────────────────────────────┐
    │  [审批通知]                                     │
    │  Agent: Searcher_3                              │
    │  操作: database_query                           │
    │  参数: {"query": "SELECT * FROM production_db..."}│
    │  描述: 即将调用敏感工具「数据库查询」             │
    │                                                 │
    │  [✅ 确认]  [✏️ 修改]  [❌ 拒绝]                 │
    └─────────────────────────────────────────────────┘

    用户点击 [修改]，将查询范围限制为 read_only → 继续执行

───────────────────────────────────────────────────────
阶段3：信息综合 (AnalystAgent)
───────────────────────────────────────────────────────
    分析师综合 3 路搜索结果：
    LLM 推理过程中提到「删除测试数据库中的旧数据」

    🔍 post_reasoning Hook 检测到敏感模式 "delete"
       → 🔴 HITL 中断触发！

    ┌─────────────────────────────────────────────────┐
    │  [审批通知]                                     │
    │  Agent: Analyst                                 │
    │  操作: reasoning_review                         │
    │  推理内容: 「建议删除测试数据库...」               │
    │                                                 │
    │  [✅ 确认]  [✏️ 修改]                            │
    └─────────────────────────────────────────────────┘

    用户点击 [修改]，将建议改为「归档而非删除」→ 继续执行

───────────────────────────────────────────────────────
阶段4：报告生成 (ReportAgent)
───────────────────────────────────────────────────────
    没有触发敏感操作 → 直接生成最终报告

═══════════════════════════════════════════════════════
✅ 研究完成：生成结构化报告
═══════════════════════════════════════════════════════
```

---

### 9. 与 LangGraph 方案的对比

| 维度 | LangGraph（当前项目） | AgentScope（内置） | AgentScope（自建方案） |
|------|---------------------|-------------------|----------------------|
| **中断原语** | `interrupt()` 原生暂停-恢复 | `interrupt()` 取消模式 + `handle_interrupt` | `asyncio.Event` 阻塞等待 |
| **状态持久化** | 内置 `AsyncRedisSaver` checkpointer | `JSONSession` 执行后保存 | 自制 `CheckpointStore`（pickle + Redis） |
| **精确断点续传** | ✅ 原生支持（恢复到代码行级） | ❌ 不支持 | 支持（需手动定义 checkpoint 点位） |
| **前端通信** | AG-UI SSE 协议 + CopilotKit | `StudioUserInput`（Socket.IO，Web 端开箱即用） | FastAPI WebSocket / HTTP Polling |
| **审批 UI** | CopilotKit `useCopilotAction` | AgentScope Studio 内置交互 | 自行实现 Web UI 或 CLI 交互 |
| **敏感工具审批** | `add_human_in_the_loop` 装饰器 | `pre_acting` hook + `UserAgent` | 自制 Hook + `HITLManager` |
| **Hook 粒度** | 仅工具调用前（`interrupt()` 在工具内） | 全生命周期：pre_acting / post_reasoning / post_acting 等 | 同内置 |
| **多 Agent 编排** | LangGraph StateGraph（显式状态机） | `sequential_pipeline` + `fanout_pipeline` + `MsgHub` | 同内置 |
| **学习成本** | 中（需理解 StateGraph 和 checkpoint） | 低（Pipeline 语法糖 + Studio 开箱即用） | 中-高（需自建 HITLManager + CheckpointStore） |

#### 何时选 AgentScope？

- 需要**轻量级**的多 Agent 编排（Pipeline 语法糖 + MsgHub 开箱即用）
- 审批场景主要是**简单确认**（工具调用前/后的人工审核），用内置 `pre_acting` + `UserAgent` 即可
- 需要使用 AgentScope Studio 的 Web 端交互能力（`StudioUserInput`）
- 与 ModelScope 或阿里云生态集成
- 团队更熟悉 Python 异步编程而非 LangGraph 的图编程模型
- 对"精确到代码行的断点续传"需求不高（如果高则需自建或切 LangGraph）

#### 何时选 LangGraph？

- 已有 LangChain/LangGraph 基础设施
- 需要**暂停-恢复**模式（`interrupt()` 在同一次调用内暂停，`Command(resume=...)` 精确恢复）
- 需要精确的状态机控制（复杂条件分支、循环、Checkpoint 自动管理）
- 需要成熟的前端方案（CopilotKit `useCopilotAction` 开箱即用）
- 对状态持久化有高标准要求（`AsyncRedisSaver` 经过大规模生产验证）

---

### 10. 最佳实践建议

#### 10.1 分级审批策略

不是所有操作都需要人工审批。建议按风险等级划分：

| 风险等级 | 触发条件 | 审批方式 |
|---------|---------|---------|
| 🟢 低 | 只读查询、公开信息搜索 | 自动放行 |
| 🟡 中 | 写操作（非关键表）、外部 API 调用 | 单人审批 |
| 🟠 高 | 敏感数据查询、配置修改 | 单人审批 + 二次确认 |
| 🔴 极高 | 生产数据库操作、资金交易 | 多人审批 + OTP 验证 |

```python
# 分级审批配置
RISK_LEVELS = {
    "search_tool": "low",
    "browser_tool": "low",
    "api_call": "medium",
    "database_query": "high",
    "database_write": "critical",
    "execute_sql": "critical",
}

def hitl_pre_acting_with_risk(self, kwargs):
    tool_name = kwargs.get("tool_name")
    risk = RISK_LEVELS.get(tool_name, "low")

    if risk == "low":
        return kwargs  # 自动放行
    elif risk == "medium":
        # 单人审批，超时自动通过
        return asyncio_run_sync(hitl_manager.interrupt(
            ..., config={"allow_accept": True, "timeout": 30}
        ))
    elif risk in ("high", "critical"):
        # 多人审批
        return asyncio_run_sync(multi_approval_manager.interrupt(...))
```

#### 10.2 审批超时处理

```python
async def interrupt_with_timeout(
    agent_name, action, args, description, timeout=300
):
    """带超时的 HITL 中断——超时后自动拒绝"""
    try:
        return await asyncio.wait_for(
            hitl_manager.interrupt(agent_name, action, args, description),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        print(f"[HITL] ⏰ 审批超时（{timeout}s），自动拒绝操作「{action}」")
        return InterruptResponse(
            request_id="timeout",
            decision=ApprovalDecision.REJECT,
        )
```

#### 10.3 多人审批机制

```python
class MultiApprovalManager:
    """多人审批——需 N 人中有 M 人同意才通过"""

    def __init__(self, required_approvals=2, total_reviewers=3):
        self.required = required_approvals
        self.total = total_reviewers
        self._votes = {}  # {request_id: [votes]}

    async def interrupt(self, agent_name, action, args, description):
        request_id = str(uuid.uuid4())
        self._votes[request_id] = []
        event = asyncio.Event()

        # 通知所有审批人
        for reviewer_id in range(self.total):
            await self._notify_reviewer(request_id, reviewer_id, agent_name, action, args)

        # 等待足够数量的同意票
        await event.wait()
        return InterruptResponse(request_id=request_id, decision=ApprovalDecision.APPROVE)

    def cast_vote(self, request_id, reviewer_id, decision):
        self._votes[request_id].append((reviewer_id, decision))
        approvals = sum(1 for _, d in self._votes[request_id]
                       if d == ApprovalDecision.APPROVE)
        if approvals >= self.required:
            # 达到最低同意数，唤醒 Agent
            self._pending_events[request_id].set()
```

#### 10.4 审计日志

所有 HITL 决策都应记录审计日志：

```python
import logging

hitl_audit_logger = logging.getLogger("hitl_audit")

def log_hitl_decision(agent_name, action, decision, user_id, timestamp):
    hitl_audit_logger.info(json.dumps({
        "agent": agent_name,
        "action": action,
        "decision": decision.value,
        "user": user_id,
        "timestamp": timestamp,
    }, ensure_ascii=False))
```

---

> **文档版本**: v1.0  
> **最后更新**: 2026-06-16  
> **覆盖内容**: LangGraph HITL 实现详解 / AgentScope HITL 方案设计 / Deep Research 场景实战
