## Why

当前 Deep Research 只在底层使用 agentscope-java 的 `OpenAIChatModel`，Agent 编排、工具执行和消息流仍由项目自定义循环完成，因此 AgentScope v2 的 `Agent` / `ReActAgent`、`Toolkit`、`RuntimeContext`、类型化事件和 Middleware 生命周期无法完整捕获 Agent 执行过程。为了真正使用 AgentScope Java v2 的原生执行与可观测链路，需要把 Agent 执行层迁移到 AgentScope 原生 `ReActAgent` / `Toolkit` / Middleware 体系。

## What Changes

- 将 agentscope-java runtime 从“只包装 ChatModel”升级为“构建并驱动 AgentScope 原生 Agent 执行”。
- 为 Scope、Supervisor、Researcher、Search、Report 建立 AgentScope 原生 Agent 或等价封装，保留现有五 Agent 协作语义。
- 将 `thinkTool`、`conductResearch`、`researchComplete`、`tavilySearch` 迁移为 AgentScope 原生 `Toolkit` 工具，使用 AgentScope tool schema 和 tool execution 生命周期。
- 将当前 required tool-call plan-action 循环映射到 AgentScope `ReActAgent` 推理/行动循环，保留预算限制、工具委托、无工具调用提醒、最终报告格式。
- 在 AgentScope Agent 构建阶段挂载 v2 原生 observability：`OtelTracingMiddleware`，并通过 `RuntimeContext` 传递 researchId、userId、modelId、budget 等业务上下文。
- 保留 `langchain4j` 回退运行时，允许通过 `RESEARCH_AGENT_FRAMEWORK=langchain4j` 回退到现有备份实现。
- 保持现有 REST API、SSE payload、数据库业务表、前端交互和研究输出格式不变。
- 更新 OpenSpec、README 和 `.env.example`，说明原生 AgentScope 执行模式与可观测启动方式。

## Capabilities

### New Capabilities
- `agentscope-native-agent-execution`: 使用 AgentScope Java v2 原生 Agent、Toolkit、RuntimeContext、Middleware 和类型化事件承载 Deep Research 多 Agent 执行链路。

### Modified Capabilities
- `agent-framework-runtime`: agentscope-java runtime 的语义从 ChatModel adapter 升级为 AgentScope native Agent runtime，同时保留 langchain4j 备份运行时和外部 API 兼容性。
- `agent-observability`: 原可观测链路需要从手动 span 为主调整为 AgentScope native lifecycle tracing 为主，项目业务 span 只补充 researchId、用户、预算、SSE 等业务上下文。

## Impact

- 后端 Agent 层：Scope/Supervisor/Researcher/Search/Report 的执行方式会重构为 AgentScope native Agent 调用。
- 工具系统：项目自有 `ResearchToolSpec` 仍可作为兼容层，但 agentscope-java 路径需要注册 AgentScope `Toolkit` 工具。
- runtime adapter：新增或重构 `AgentscopeNativeAgentRuntime`、Agent factory、Toolkit adapter、message converter。
- observability：`OtelTracingMiddleware` 在 AgentScope Agent 创建时注入；Studio 作为 AgentScope 生态外部查看入口记录在文档中，不依赖 v1 Java hook 类。
- 测试：需要恢复一组最小 contract tests，验证 API 不变、预算不变、工具委托不变、langchain4j 回退可用。
- 文档：README 需要区分“AgentScope native execution”与“langchain4j rollback”。
