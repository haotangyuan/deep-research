## Why

Deep Research 已完成 agentscope-java 运行时迁移，但当前只能通过日志、SSE 事件和最终 token 汇总观察研究过程，缺少跨 Agent、模型调用、工具调用的完整链路追踪。引入 agentscope-java 原生 OpenTelemetry/Studio 能力后，可以获得接近 Langfuse 的研究请求级可观测性，用于定位慢步骤、成本异常、工具循环和模型输出质量问题。

## What Changes

- 增加 agentscope-java 可观测性初始化能力，在应用启动时按当前 AgentScope Java 版本可用的 tracing API 注册 OpenTelemetry bridge，并支持导出到 Langfuse、Jaeger 或其他 OTLP 后端。
- 为每次研究请求建立可关联的 trace 维度，至少包含 researchId、userId、modelId、budget、runtime framework、agent name、workflow stage 等关键属性。
- 记录 Agent 执行、LLM 调用、工具调用、格式化/适配步骤的耗时、token 用量、错误状态和必要的输入输出摘要。
- 增加 Studio 调试集成的可选配置，便于开发环境查看多 Agent 消息流和 trace。
- 保持现有 REST API、SSE、数据库业务表和前端交互不变；可观测链路通过配置开启，默认不影响无 OTLP 后端的本地运行。
- 增加 README/.env 示例与运维说明，描述如何对接 Langfuse/Jaeger/AgentScope Studio。

## Capabilities

### New Capabilities
- `agent-observability`: Deep Research Agent 执行链路的 OpenTelemetry/Studio 可观测能力，包括 trace 初始化、研究请求关联、span 属性、token/耗时/error 记录和可配置导出。

### Modified Capabilities
- `agent-framework-runtime`: 现有 runtime 需要在 agentscope-java 路径上暴露可观测上下文并保证 langchain4j 回退运行时不被强制依赖 agentscope-java tracing。

## Impact

- 后端配置：新增 `research.observability.*` 配置和对应环境变量。
- 后端基础设施：新增可观测初始化组件、trace context 传播工具、可观测属性常量和关闭/降级逻辑。
- Agent runtime：agentscope-java adapter 接入 `TracerRegistry`/`TelemetryTracer`，必要时补充手动 span 或属性绑定。
- Agent workflow：在 researchId/userId/modelId/budget/stage 等上下文进入 Agent 调用前建立关联。
- 文档：更新 README、`.env.example`，新增 Langfuse/Jaeger/Studio 对接说明。
- 依赖：如当前 agentscope-java 依赖未传递所需 OpenTelemetry exporter，则补充最小必要依赖。
