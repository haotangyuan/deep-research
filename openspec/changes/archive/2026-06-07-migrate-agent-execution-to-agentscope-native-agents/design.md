## Context

Deep Research 目前已经支持 `RESEARCH_AGENT_FRAMEWORK=agentscope-java`，但 agentscope-java 路径只使用 `OpenAIChatModel` 完成模型调用。Scope、Supervisor、Researcher、Search、Report 的循环、工具拦截、预算控制和消息记忆仍由项目自有代码手动编排。这种方式能复用 AgentScope 的模型客户端，但不能让 AgentScope v2 原生 `Agent` / `ReActAgent`、`Toolkit`、`RuntimeContext`、类型化事件和 Middleware 完整接管 Agent 生命周期。

AgentScope Java v2 官方文档说明：`Agent` 是统一的推理-行动循环接口，`ReActAgent` 是默认实现；`call` 和 `streamEvents` 驱动同一套循环，`RuntimeContext` 在一次调用内把 per-call 元数据传递给 middleware 和 tool；工具通过 `Toolkit` 和 `@Tool`/`@ToolParam` 注册；Middleware 提供 `onAgent`、`onReasoning`、`onActing`、`onModelCall` 和 `onSystemPrompt` 生命周期钩子。当前本地依赖 `agentscope-core:2.0.0-RC1` 已包含 `ReActAgent`、`Toolkit`、`@Tool`、`@ToolParam`、`RuntimeContext`、`MiddlewareBase`、`OtelTracingMiddleware`、`TracerRegistry`，但未包含 v1 文档中的 `TelemetryTracer` 或 Java Studio hook 类；因此实现必须以 v2 文档和当前 jar 实际 API 为准。

## Goals / Non-Goals

**Goals:**
- 将 agentscope-java runtime 的核心执行迁移为 AgentScope native `ReActAgent` + `Toolkit` + Middleware。
- 保留现有五 Agent 协作语义、预算行为、工具名称、输出格式、REST/SSE/数据库/前端合同。
- 将现有 delegated tools 迁移为 AgentScope native tools，使 AgentScope tool execution lifecycle 可观测。
- 在 AgentScope Agent 构建时挂载 v2 `OtelTracingMiddleware`，并通过 `RuntimeContext` 传入业务 trace context。
- 保留 `langchain4j` 回退路径，不让 native AgentScope 类型泄露到回退 adapter。
- 恢复最小必要 contract tests，覆盖 native execution、toolkit、budget、observability hook、rollback。

**Non-Goals:**
- 不把前端改成 AgentScope Studio；现有 Web UI 和 SSE 仍是主用户界面。
- 不引入 AgentScope Harness/Sandbox/Filesystem 等长期任务基础设施，除非 native ReActAgent 迁移必须依赖。
- 不改变用户的模型配置方式，继续使用现有 `Model` 表的 `baseUrl`、`apiKey`、`model`。
- 不同时实现动态工作流 fan-out/reviewer/cross-check；本 change 聚焦 native Agent execution。
- 不删除 langchain4j 备份运行时。

## Decisions

### 1. 使用 Native Agent Adapter 包裹 AgentScope ReActAgent

新增 `AgentscopeNativeAgentRuntime` 或重构当前 `AgentscopeJavaAgentRuntime`，负责创建 AgentScope `OpenAIChatModel`、`Toolkit`、`ReActAgent`、middleware/hook。项目 Agent 层通过项目自有接口调用 native adapter，避免直接依赖 AgentScope 类型。

替代方案是继续沿用当前 `ResearchChatClient`，只把 tool schema 传给 `OpenAIChatModel`。该方案无法触发 AgentScope agent/tool lifecycle，因此不满足“原生可观测”目标。

### 2. 以阶段 Agent Factory 创建不同 Agent

为 Scope、Supervisor、Researcher、Search、Report 建立阶段化 Agent factory。每个 factory 输入：

- agent name
- system prompt
- model config
- toolkit
- memory/messages
- execution options
- observability hooks/middleware

输出可运行的 AgentScope Agent wrapper。这样可以保留当前每个 Agent 的 prompt 和状态边界，同时让 AgentScope 通过 `call` / `streamEvents` 捕获每个 Agent 的生命周期事件。

### 3. Toolkit Adapter 保留当前工具合同

当前项目已有 `@ResearchTool`/`ResearchToolSpec`，用于框架无关 tool contract。agentscope-java native 路径新增 `AgentscopeToolkitAdapter`，把项目工具注册成 AgentScope `Toolkit`：

- `thinkTool`
- `conductResearch`
- `researchComplete`
- `tavilySearch`

工具执行仍委托项目服务/Agent 层，以保留 budget 和 SSE 行为；但调用入口必须经过 AgentScope `Toolkit`，让 `onActing` / tracing middleware 能捕获到工具执行生命周期。

### 4. Plan-action loop 逐步迁移

Supervisor/Researcher 当前显式循环调用 chat、解析 tool calls、执行工具、写 tool result。native 迁移应优先让 `ReActAgent` 执行 reasoning/acting；项目只负责阶段终止条件、预算上限和结果提取。

迁移顺序：

1. ReportAgent：无工具、输出格式稳定，最适合作为 native Agent smoke。
2. ScopeAgent：结构化 JSON 输出，需要验证 ReActAgent 能稳定返回文本/JSON。
3. SearchAgent summary：无工具或低工具复杂度。
4. ResearcherAgent：迁移 `tavilySearch` native tool。
5. SupervisorAgent：迁移 `conductResearch`/`researchComplete` native tools。

### 5. 可观测以 AgentScope lifecycle 为主，项目 span 为辅

完成 native 迁移后，AgentScope lifecycle tracing 应覆盖 Agent/model/tool/formatting。项目当前 `ResearchObservation` 只保留业务上下文补充：

- researchId
- userId
- modelId
- budget
- workflow status
- SSE/event IDs

当前 v2 依赖未提供 v1 文档中的 `TelemetryTracer` 或 Java Studio hook 类，因此本 change 不围绕这些类设计。Studio 仅作为 AgentScope 生态外部入口在文档中说明；应用侧的原生可观测主线是 `OtelTracingMiddleware` + OTLP backend，项目 span 只补充业务上下文：

### 6. Runtime rollback 边界

langchain4j 路径继续使用当前 adapter 和手动 tool-call 机制。所有 native AgentScope 类型只能存在于 agentscope-java adapter/toolkit 包内，不进入 `DeepResearchState`、domain、REST DTO、SSE payload 或 langchain4j adapter。

## Risks / Trade-offs

- [Risk] 当前 `agentscope-core:2.0.0-RC1` API 与 v2 文档可能仍有细节差异。 -> 实现前用 jar/source 确认 `ReActAgent`、`Toolkit`、`RuntimeContext`、middleware 和 tracing API；不引用 v1 的 `TelemetryTracer` / Studio hook 类。
- [Risk] ReActAgent 自带循环的终止行为与现有 plan-action loop 不完全一致。 -> 分阶段迁移，先从无工具 Agent 开始；对 Supervisor/Researcher 增加 contract tests 固定预算、工具提醒和结束条件。
- [Risk] 工具经 AgentScope Toolkit 执行后，预算和 SSE 事件可能重复或丢失。 -> Toolkit tool 实现只作为入口，内部仍调用现有服务/Agent 方法；验证 parentEventId、token 和 notes 行为。
- [Risk] native AgentScope message/memory 类型泄漏到项目状态。 -> 保留 project-owned neutral messages，native adapter 内部负责转换。
- [Risk] 真实模型行为变化导致研究质量波动。 -> 加入 offline fake model/tool contract tests；live LLM 测试作为可选验证，不作为 CI 必需。
- [Risk] 工程范围较大。 -> 按 Agent 阶段分批完成，每一步保持 langchain4j rollback 可用。

## Migration Plan

1. 调研并确认本地 AgentScope API，补充必要依赖或版本升级决策。
2. 新增 native Agent adapter、Agent factory、Toolkit adapter、message converter。
3. 迁移 Report/Scope/Search summary 等无工具或低工具 Agent。
4. 迁移 Researcher 的 `tavilySearch` native tool。
5. 迁移 Supervisor 的 `conductResearch`/`researchComplete` native tools。
6. 将 observability 改为 AgentScope lifecycle tracing 为主，项目业务 span 为辅。
7. 更新 README 和 `.env.example`，说明 AgentScope native execution、OTLP 使用方式和 v2 Studio 生态入口。
8. 运行默认 runtime、langchain4j rollback、offline contract tests；可选运行 live LLM/Langfuse 验证。

Rollback 策略：设置 `RESEARCH_AGENT_FRAMEWORK=langchain4j` 回退；如 agentscope native adapter 发生问题，也可以临时保留旧 agentscope chat-only adapter 作为开发期 fallback，直到 native contract 稳定。

## Open Questions

- 是否在后续独立 change 中引入 `agentscope-harness`，利用 v2 Harness 的 Workspace、Session、Plan Mode 和 Subagent 能力进一步演进动态工作流。
- 是否保留旧 agentscope chat-only adapter 作为第三个临时 runtime 值，例如 `agentscope-java-chat`，用于迁移期间对比。
- ReActAgent 对 required tool choice 的精确 API 需要实现前基于源码确认。
