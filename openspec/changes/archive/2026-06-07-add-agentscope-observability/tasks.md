## 1. Dependencies and Configuration

- [x] 1.1 Verify the current agentscope-java dependency exposes tracing APIs and required OpenTelemetry exporter APIs; add the smallest required Maven dependencies if compilation proves they are not transitive.
- [x] 1.2 Add `ResearchObservabilityProps` with `research.observability.*` configuration for enabled flag, OTLP endpoint, headers, Langfuse keys, input/output capture, and Studio options.
- [x] 1.3 Add `.env.example` entries for disabled/default observability, Langfuse OTLP export, generic OTLP export, and AgentScope Studio local debugging.

## 2. Telemetry Initialization

- [x] 2.1 Implement an observability initialization component that registers the current AgentScope tracing bridge only when observability export is enabled and configured.
- [x] 2.2 Implement Langfuse header construction using public/secret keys and ingestion version without logging secrets.
- [x] 2.3 Ensure missing endpoint, disabled observability, or unavailable Studio results in no-op behavior or warning logs without blocking application startup.
- [x] 2.4 Make tracer/studio initialization idempotent so repeated Spring context creation does not duplicate global registrations.

## 3. Research Trace Context

- [x] 3.1 Add a research trace context helper that carries researchId, userId, modelId, budget, runtime framework, workflow status, and capture policy into asynchronous execution.
- [x] 3.2 Populate trace metadata when `ResearchServiceImpl.sendMessage` creates `DeepResearchState`.
- [x] 3.3 Re-establish trace context at the start of `AgentPipeline.run` so queued async execution is linked to the originating research request.

## 4. Workflow, Agent, Model, and Tool Spans

- [x] 4.1 Add a root workflow span around `AgentPipeline.run` with final status and total token attributes on completion, clarification, or failure.
- [x] 4.2 Add stage spans for Scope, Supervisor, Researcher/Search delegation, and Report with latency, status, and sanitized errors.
- [x] 4.3 Add model call telemetry in the agentscope-java chat client for model name, runtime framework, finish reason, latency, input tokens, output tokens, and missing usage metadata.
- [x] 4.4 Add tool execution telemetry for `thinkTool`, `conductResearch`, `researchComplete`, and `tavilySearch`, including budget-limit outcomes and sanitized errors.
- [x] 4.5 Apply input/output capture policy so prompts, responses, tool arguments, and tool results are omitted by default and only exported as sanitized length-limited summaries when explicitly enabled.

## 5. Runtime Boundary and Rollback

- [x] 5.1 Ensure agentscope-java runtime uses native AgentScope telemetry when enabled.
- [x] 5.2 Ensure langchain4j runtime remains selectable and executable without requiring AgentScope telemetry integration in its adapter path.
- [x] 5.3 Verify observability disabled mode preserves current REST API, SSE, token persistence, and workflow behavior.

## 6. Documentation

- [x] 6.1 Update README with an observability section covering Langfuse, Jaeger/generic OTLP, Studio, disabled mode, and privacy trade-offs.
- [x] 6.2 Document common environment variable combinations for local development, Langfuse Cloud/self-hosted, and local Jaeger.
- [x] 6.3 Document how to find a research request trace using researchId and related span attributes.

## 7. Verification

- [x] 7.1 Run `./mvnw test` with observability disabled and confirm the remaining test suite passes.
- [x] 7.2 Run a compile/startup check with observability enabled but no external backend required, confirming startup does not fail.
- [x] 7.3 If an OTLP backend is available, run a manual research request and verify trace spans include researchId, agent stages, model latency, tool execution, and token attributes. Local OTLP backend was not available; README documents the manual verification path.
- [x] 7.4 Run or document a rollback check with `RESEARCH_OBSERVABILITY_ENABLED=false`.
