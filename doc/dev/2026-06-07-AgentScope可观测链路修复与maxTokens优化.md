# 2026-06-07 AgentScope 可观测链路修复与 maxTokens 优化

## 背景

Langfuse 中 SupervisorAgent 下看不到 ResearcherAgent 和 SearchAgent 的 span，子 Agent 的 span 变成了独立的根 trace，无法正确展示多级嵌套调用链。同时 MiMo 模型因 reasoning 消耗所有 token 导致 content 为空，研究任务在 ScopeAgent 阶段解析失败。

## 方案

### 1. 新增 FixedOtelTracingMiddleware

AgentScope v2 内置的 `OtelTracingMiddleware` 使用 `try-with-resources` 管理 OTel Scope，在 `next.apply(input)` 返回后立即关闭。但返回的 `Flux` 是惰性的，实际事件处理（包括工具回调和子 Agent 执行）要等到被订阅时才执行，此时 Scope 已关闭。

修复方案：
- 使用 `ThreadLocal<Deque<Scope>>` 栈管理 Scope 生命周期
- `onAgent` / `onActing` 将 Scope 压入栈，在 `doFinally` 中结束 span
- 在 `AgentscopeJavaChatClient.runAgent()` 的 `block()` 后调用 `closeAllScopes()` 同步关闭当前线程的所有 Scope
- 利用 OTel 线程本地上下文传播：工具回调和子 Agent 都在同一个 boundedElastic 线程执行，`Span.current()` 能正确获取父 span

### 2. 设置 maxTokens(16384)

MiMo 模型的 reasoning 消耗了所有 token，导致 content 为空。在 `AgentscopeJavaAgentRuntime.createChatClient()` 的 `GenerateOptions` 中显式设置 `maxTokens(16384)`。

## 影响范围

**新增文件：**
- `src/main/java/.../runtime/agentscope/FixedOtelTracingMiddleware.java` — 自定义 OTel 中间件

**修改文件：**
- `src/main/java/.../runtime/agentscope/AgentscopeJavaChatClient.java` — 使用 FixedOtelTracingMiddleware 替代原生 OtelTracingMiddleware，block() 后调用 closeAllScopes()
- `src/main/java/.../runtime/agentscope/AgentscopeJavaAgentRuntime.java` — 添加 maxTokens(16384)
- `README.md` — 更新技术亮点和可观测链路章节
- `CLAUDE.md` — 新建项目指导文件

**无数据库变更、无配置项变更。**

## 测试

1. 启动应用，确认 `ObservabilityConfiguration` 日志显示 `export enabled: provider=langfuse`
2. 发起研究任务，等待完成（MiMo API 较慢，单次研究约 15-25 分钟）
3. 在 Langfuse 中验证：
   - `deep_research.workflow` 为根 span
   - `deep_research.stage SupervisorAgent` 的 parent 是 workflow（而非 chat span）
   - `invoke_agent ResearcherAgent` 和 `invoke_agent SearchAgent` 正确嵌套在 SupervisorAgent 下
   - `execute_tool conductResearch` 和 `execute_tool tavilySearch` span 存在

4. 验证结果：span 层级在 Langfuse 中正确展示，多级嵌套调用链完整

## 遗留问题

- MiMo API 响应较慢（单次调用 5-10 分钟），不适合快速迭代测试
- `FixedOtelTracingMiddleware` 的 `closeAllScopes()` 在嵌套调用时需要确保每个线程独立管理自己的 Scope 栈（当前通过 ThreadLocal 已实现）
- AgentScope v2 后续版本可能修复内置 `OtelTracingMiddleware` 的问题，届时可考虑移除自定义中间件
