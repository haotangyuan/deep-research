## Context

Deep Research 当前已经通过 `AgentRuntime` 将 Agent 业务逻辑与 agentscope-java/langchain4j 运行时解耦。研究请求从 `ResearchServiceImpl.sendMessage` 构造 `DeepResearchState`，再由 `AgentPipeline.run` 依次执行 Scope、Supervisor、Researcher/Search、Report。系统已有 SSE 事件、数据库 token 汇总和日志，但缺少外部可观测平台可消费的 trace。

AgentScope Java 官方可观测能力包括两类：Studio 用于开发期 Web 可视化调试；OpenTelemetry tracing 可以捕获 agent call、model call、tool execution、formatting 等活动，并导出到 Langfuse、Jaeger 或其他 OTLP 后端。当前项目使用的 `agentscope-core:2.0.0-RC1` 与 v1 文档 API 存在差异：本地依赖未提供 `TelemetryTracer` 和 Studio 类，但 `OpenAIChatModel` 仍通过 `TracerRegistry` 包裹 model call。因此实现上需要按当前依赖实际 API 注册 AgentScope tracing bridge，并结合项目内的手动上下文/span 属性补充。

## Goals / Non-Goals

**Goals:**
- 通过配置开启/关闭 OpenTelemetry trace 导出，默认本地无 OTLP 后端时不影响启动和研究流程。
- 对每次研究请求建立可关联的 trace，覆盖 researchId、userId、modelId、budget、runtime framework、agent name、workflow stage 等属性。
- 记录 Agent 阶段、LLM 调用、工具调用的耗时、token 用量、错误状态和必要输入输出摘要。
- 支持 Langfuse OTLP 接入，同时保持对 Jaeger/其他 OTLP 后端的通用兼容。
- 支持可选 AgentScope Studio 调试配置，用于开发环境查看消息流和 trace。
- 保持 REST API、SSE payload、数据库业务表和前端流程不变。

**Non-Goals:**
- 不自建 Langfuse 或 Jaeger 服务。
- 不新增前端可观测页面。
- 不把完整 prompt、API key、用户敏感内容默认写入 trace。
- 不要求 langchain4j 回退运行时使用 agentscope-java tracing；回退路径只需保持可运行，并可记录项目自有手动 span。
- 不恢复此前已移除的大量测试文件；验证以最小必要测试和配置/编译检查为主。

## Decisions

### 1. 使用配置驱动的可观测初始化组件

新增 `ResearchObservabilityProps`，配置前缀为 `research.observability`。核心字段包括：

- `enabled`
- `provider` 或 `exporter`，支持 `otlp`、`langfuse`、`none`
- `endpoint`
- `headers`
- `langfuse.public-key`
- `langfuse.secret-key`
- `langfuse.ingestion-version`
- `capture-input-output`
- `input-output-max-chars`
- `studio.enabled`
- `studio.url`
- `studio.project`

新增 `ObservabilityConfiguration` 在应用启动时读取配置。如果 `enabled=false` 或没有 endpoint，则不注册 exporter，只记录 debug/info 日志。如果启用 Langfuse，则生成 Basic Authorization header，并补充 `x-langfuse-ingestion-version` header。这样本地开发无需额外服务，生产环境可通过环境变量接入。

替代方案是直接在 `AgentscopeJavaAgentRuntime` 构造函数中注册 tracer。该方案耦合 runtime 创建与全局 tracer 生命周期，不利于配置校验和回退路径，因此不采用。

### 2. 自动 tracing 与手动上下文补充并用

AgentScope tracing bridge 注册后可覆盖 AgentScope Java 内部支持的 model call，但 Deep Research 的 workflow stage、researchId、budget、userId 等业务语义不属于 AgentScope 默认上下文。新增 `ResearchObservation` 工具，在 `AgentPipeline.run` 入口建立 research 级上下文，并在每个 Agent run、tool delegation、LLM chat 调用前后补充 span 或 attributes。

最小实现优先级：

1. research workflow span：从 `AgentPipeline.run` 开始到完成/失败/澄清结束。
2. agent stage span：Scope、Supervisor、Researcher、Search、Report。
3. chat/model span 属性：modelId、modelName、runtime、inputTokens、outputTokens、finishReason、latency。
4. tool span 属性：toolName、stage、success/error、latency。

如果 AgentScope 自动 span 与手动 span 重叠，手动 span 只作为父级业务 span 或补充属性，不重复记录完整输入输出。

### 3. 敏感内容默认不进入 trace

默认 `capture-input-output=false`。开启后只记录截断后的摘要，最大长度由 `input-output-max-chars` 控制。API key、Authorization header、模型密钥、JWT 不得进入 span attributes 或 logs。错误信息可以记录异常类型、阶段和脱敏 message。

替代方案是默认记录完整 prompt 和 response，以获得 Langfuse 风格完整回放。该方案风险较高，容易泄露用户研究内容和密钥，因此不作为默认行为。

### 4. 保持 runtime 回退边界

agentscope-java 路径注册当前版本可用的 AgentScope tracing bridge。langchain4j 回退路径不得依赖 AgentScope 的 runtime 类型，也不得因为 tracing 配置失败而无法启动。公共的 observation 工具可以用于两个 runtime 的业务 span，但 AgentScope 原生 model tracing 只在 agentscope-java 可用路径生效。

### 5. 文档优先描述可观测后端接入

README 和 `.env.example` 增加最小可运行配置示例：

- 默认关闭或无 endpoint 时不导出。
- Langfuse Cloud/self-hosted 的 OTLP endpoint、public/secret key。
- Jaeger 本地 OTLP endpoint 示例。
- AgentScope Studio 的开发调试开关。

## Risks / Trade-offs

- [Risk] AgentScope Java 版本的 tracing API 与文档存在差异，或依赖未传递 OTLP exporter。 -> 已用本地 jar 确认当前版本 API，采用 `TracerRegistry` bridge，并补充最小 OpenTelemetry SDK/exporter 依赖。
- [Risk] trace 内容过多导致成本和性能开销。 -> 默认关闭输入输出采集，限制字符串长度，并允许按配置关闭 tracing。
- [Risk] 全局 `TracerRegistry` 重复注册导致测试或热重启行为异常。 -> 初始化组件需要幂等，避免重复注册；测试中使用禁用配置。
- [Risk] 手动 span 与 AgentScope 自动 span 重复。 -> 手动 span 聚焦业务 workflow/stage 属性，自动 span 负责 AgentScope 内部模型和工具调用。
- [Risk] 异步队列导致 trace context 丢失。 -> 在构建 `DeepResearchState` 或 pipeline 入口显式携带 research trace metadata，并在异步执行线程重新建立 context。
- [Risk] Langfuse header 配置错误导致导出失败。 -> 启动时只校验必要配置，导出失败不影响业务流程；文档提供正确 header 和 endpoint 示例。

## Migration Plan

1. 新增可观测配置类和初始化组件，默认关闭或无 endpoint 时 no-op。
2. 在 agentscope-java runtime 路径注册 AgentScope tracing bridge，并补充 OTLP/Langfuse headers。
3. 在 `DeepResearchState` 或 pipeline 入口绑定 research trace metadata。
4. 为 AgentPipeline、Agent run、chat/model 调用、tool execution 增加业务 span/attributes。
5. 更新 `.env.example` 和 README 可观测说明。
6. 运行 `./mvnw test` 和至少一次本地禁用配置启动/编译验证。

Rollback 策略：设置 `RESEARCH_OBSERVABILITY_ENABLED=false` 或移除 endpoint 即可关闭导出；如生产发生异常，可回退到无 tracing 的 runtime 行为，REST/SSE/数据库合同不受影响。

## Open Questions

- AgentScope Java 当前依赖包不包含 v1 文档中的 `TelemetryTracer` 和 Studio 类；实现采用 2.0-RC1 可用的 `TracerRegistry` bridge，并补充 OTLP exporter 依赖。
- 是否需要将 traceId 持久化到 `research_session`，便于从业务页面跳转到 Langfuse；当前提案先不修改数据库。
- 是否将输入输出摘要默认对管理员环境开启；当前提案默认关闭。
