## ADDED Requirements

### Requirement: Native AgentScope lifecycle observability
Agent observability SHALL use AgentScope native lifecycle events as the primary tracing source when the agentscope-java native runtime is selected.

#### Scenario: Native agent call traced
- **WHEN** a native AgentScope agent executes a workflow stage
- **THEN** AgentScope tracing middleware or tracer SHALL emit an agent call span/event for that stage.

#### Scenario: Native model call traced
- **WHEN** a native AgentScope agent invokes the configured model
- **THEN** AgentScope tracing middleware or tracer SHALL emit a model call span/event including model name, latency, finish reason, and token usage when available.

#### Scenario: Native tool call traced
- **WHEN** a native AgentScope toolkit tool executes
- **THEN** AgentScope tracing middleware or tracer SHALL emit a tool execution span/event including tool name, success/failure, and latency.

### Requirement: Business context on native traces
The system SHALL enrich native AgentScope traces with Deep Research business context.

#### Scenario: Research context attached
- **WHEN** native AgentScope tracing emits spans/events for a research workflow
- **THEN** the trace SHALL include or be correlated with `research.id`, `user.id`, `model.id`, `budget.level`, and `agent.framework`.

#### Scenario: Existing SSE context preserved
- **WHEN** native AgentScope observability is enabled
- **THEN** the existing SSE workflow events SHALL remain unchanged and SHALL continue to include the same parent-child event relationships.

### Requirement: V2 native tracing middleware integration
The native AgentScope runtime SHALL use the AgentScope v2 tracing middleware available in the installed dependency instead of v1-only tracer or Studio hook classes.

#### Scenario: Otel tracing middleware available
- **WHEN** observability is enabled and the AgentScope Java dependency provides `OtelTracingMiddleware`
- **THEN** each native AgentScope agent SHALL attach the middleware so lifecycle spans/events are emitted through the AgentScope v2 middleware stack.

#### Scenario: RuntimeContext carries business trace context
- **WHEN** a native AgentScope agent call is started
- **THEN** the runtime SHALL pass Deep Research business identifiers through `RuntimeContext` so middleware and tools can correlate spans with the workflow.
