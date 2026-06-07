## 1. AgentScope API and Dependency Verification

- [x] 1.1 Inspect AgentScope Java v2 docs and the installed jar/source for `ReActAgent`, `RuntimeContext`, `Toolkit`, `@Tool`, `@ToolParam`, middleware, tracing, and event APIs.
- [x] 1.2 Decide whether to keep `agentscope-core:2.0.0-RC1` or add v2 modules such as `agentscope-harness`; document why v1-only `TelemetryTracer` / Java Studio hook classes are not implementation targets.
- [x] 1.3 Add or adjust Maven dependencies for AgentScope v2 native agent execution and observability without breaking langchain4j rollback.

## 2. Test and Contract Baseline

- [x] 2.1 Restore minimal runtime contract tests for `agentscope-java` and `langchain4j` framework selection.
- [x] 2.2 Add fake-model/fake-tool tests for native AgentScope adapter behavior without live LLM credentials.
- [x] 2.3 Add contract tests for tool names, argument schemas, required fields, and stage grouping parity.
- [x] 2.4 Add budget tests for `conductResearch` and `tavilySearch` limits through the native toolkit path.

## 3. Native Adapter Infrastructure

- [x] 3.1 Add an AgentScope native agent factory that builds stage agents with name, system prompt, model, toolkit, memory/messages, middleware, maxIters, and RuntimeContext support.
- [x] 3.2 Add message conversion between project-owned `ResearchMessage` and AgentScope `Msg`/content blocks without leaking AgentScope types into `DeepResearchState`.
- [x] 3.3 Add a toolkit adapter that converts project `ResearchToolSpec`/executors into AgentScope `Toolkit` tools.
- [x] 3.4 Add execution result extraction for text, tool results, finish reason, and token usage from native AgentScope agent/model outputs.

## 4. Stage-by-Stage Native Migration

- [x] 4.1 Migrate `ReportAgent` to native AgentScope execution and verify final Markdown output compatibility.
- [x] 4.2 Migrate `ScopeAgent` to native AgentScope execution and verify clarification/research brief JSON parsing behavior.
- [x] 4.3 Migrate `SearchAgent` summarization calls to native AgentScope execution and verify fallback behavior on invalid JSON.
- [x] 4.4 Migrate `ResearcherAgent` plan/action loop to native `ReActAgent` + `tavilySearch` toolkit execution.
- [x] 4.5 Migrate `SupervisorAgent` plan/action loop to native `ReActAgent` + `conductResearch`/`researchComplete` toolkit execution.

## 5. Workflow Semantics and Compatibility

- [x] 5.1 Verify existing REST API responses, SSE event shapes, parent event IDs, and replay behavior remain unchanged.
- [x] 5.2 Verify `DeepResearchState` budget counters, notes, token totals, and final status transitions match current behavior.
- [x] 5.3 Verify model configuration still uses existing `Model` records and OpenAI-compatible endpoint values.
- [x] 5.4 Verify `RESEARCH_AGENT_FRAMEWORK=langchain4j` rollback still executes without AgentScope native classes in its adapter path.

## 6. Native Observability Integration

- [x] 6.1 Attach AgentScope tracing middleware/tracer to native agents so agent/model/tool/format spans are emitted by AgentScope lifecycle hooks.
- [x] 6.2 Pass Deep Research business identifiers through AgentScope `RuntimeContext` so v2 middleware and tools can correlate lifecycle spans/events.
- [x] 6.3 Reduce project manual spans to business context enrichment only: researchId, userId, modelId, budget, framework, workflow status.
- [x] 6.4 Verify Langfuse/Jaeger traces show AgentScope native agent calls, model calls, and toolkit tool executions when an OTLP backend is configured.

## 7. Documentation and Cleanup

- [x] 7.1 Update README to explain AgentScope v2 native execution, Langfuse/OTLP setup, v2 Studio ecosystem notes, and langchain4j rollback.
- [x] 7.2 Update `.env.example` with any new AgentScope native/observability configuration.
- [x] 7.3 Remove obsolete chat-only agentscope adapter code after native runtime parity is verified, or mark it as temporary fallback if retained.
- [x] 7.4 Update OpenSpec task notes if implementation discovers AgentScope API differences from the current design.

## 8. Verification

- [x] 8.1 Run `./mvnw test` with default agentscope-java native runtime.
- [x] 8.2 Run `./mvnw test -Dresearch.agent.framework=langchain4j` for rollback.
- [x] 8.3 Run optional live LLM smoke test for a minimal research request through native AgentScope execution.
- [x] 8.4 Run optional Langfuse/OTLP manual verification and confirm native Agent/model/tool lifecycle visibility.
- [x] 8.5 Run `openspec validate migrate-agent-execution-to-agentscope-native-agents --strict`.
