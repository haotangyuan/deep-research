## ADDED Requirements

### Requirement: Configurable observability startup
The system SHALL support configuration-driven observability initialization for Deep Research Agent execution.

#### Scenario: Observability disabled
- **WHEN** the application starts with observability disabled
- **THEN** the application SHALL NOT register an OpenTelemetry exporter or AgentScope tracing bridge and SHALL continue accepting research requests normally.

#### Scenario: OTLP endpoint configured
- **WHEN** the application starts with observability enabled and an OTLP endpoint configured
- **THEN** the application SHALL initialize OpenTelemetry export with that endpoint and register the current AgentScope Java tracing bridge needed by the selected agentscope-java runtime.

#### Scenario: Langfuse configured
- **WHEN** the application starts with Langfuse public and secret keys configured
- **THEN** the telemetry exporter SHALL include a Basic authorization header and the Langfuse ingestion version header required by Langfuse OTLP ingestion.

#### Scenario: Missing optional backend
- **WHEN** observability is disabled or no export endpoint is configured
- **THEN** backend startup and research workflow execution SHALL NOT require Langfuse, Jaeger, AgentScope Studio, or any external observability service to be reachable.

### Requirement: Research request trace correlation
The system SHALL correlate all observable spans for a research workflow with the originating research request.

#### Scenario: Research workflow starts
- **WHEN** a queued research task begins execution
- **THEN** the root workflow trace or span SHALL include at least `research.id`, `user.id`, `model.id`, `budget.level`, `agent.framework`, and current workflow status attributes when available.

#### Scenario: Async execution continues
- **WHEN** research execution moves from the request thread into the queued asynchronous pipeline
- **THEN** trace correlation SHALL be re-established so subsequent Agent, model, and tool spans remain associated with the same research workflow.

#### Scenario: Workflow completes
- **WHEN** a research workflow completes, fails, or stops for clarification
- **THEN** the root workflow trace or span SHALL record the final status and total input/output token counts accumulated in `DeepResearchState`.

### Requirement: Agent stage tracing
The system SHALL expose observable spans or equivalent trace events for each major Agent workflow stage.

#### Scenario: Scope stage runs
- **WHEN** `ScopeAgent` analyzes a user request
- **THEN** the trace SHALL include a Scope stage entry with latency, status, and error information if the stage fails.

#### Scenario: Research stage delegates work
- **WHEN** `SupervisorAgent` delegates to `ResearcherAgent` or `ResearcherAgent` delegates to `SearchAgent`
- **THEN** the trace SHALL include stage/tool delegation entries that identify the source agent, target agent or tool, and execution latency.

#### Scenario: Report stage runs
- **WHEN** `ReportAgent` generates the final Markdown report
- **THEN** the trace SHALL include a Report stage entry with latency, status, and token usage produced by the report model call when available.

### Requirement: Model and token telemetry
The system SHALL record model-call latency and token usage for every LLM call where metadata is available.

#### Scenario: Model call succeeds with token usage
- **WHEN** an Agent runtime receives a successful model response containing input and output token usage
- **THEN** the corresponding trace span SHALL include input token count, output token count, total token count, model name, runtime framework, finish reason, and latency.

#### Scenario: Model call succeeds without token usage
- **WHEN** an Agent runtime receives a successful model response without usage metadata
- **THEN** the workflow SHALL continue and the trace SHALL record that token usage was unavailable rather than failing the research request.

#### Scenario: Model call fails
- **WHEN** a model call throws an exception or times out
- **THEN** the corresponding trace span SHALL be marked as failed and SHALL include the sanitized exception type and message.

### Requirement: Tool execution telemetry
The system SHALL record tool execution observability for Deep Research delegated tools.

#### Scenario: Tool call succeeds
- **WHEN** `thinkTool`, `conductResearch`, `researchComplete`, or `tavilySearch` executes successfully
- **THEN** the trace SHALL include the tool name, owning agent stage, latency, success status, and sanitized result summary when configured.

#### Scenario: Tool call blocked by budget
- **WHEN** a delegated tool call is rejected because the configured research budget has been reached
- **THEN** the trace SHALL record the budget limit, current count, tool name, and non-error quota outcome.

#### Scenario: Tool call fails
- **WHEN** a delegated tool throws an exception
- **THEN** the corresponding trace span SHALL be marked as failed and SHALL include the sanitized exception type and message.

### Requirement: Safe input and output capture
The system SHALL protect sensitive data when exporting trace content.

#### Scenario: Input output capture disabled
- **WHEN** input/output capture is disabled
- **THEN** traces SHALL NOT include full prompt text, full model response text, API keys, JWT tokens, Authorization headers, or model secret values.

#### Scenario: Input output capture enabled
- **WHEN** input/output capture is explicitly enabled
- **THEN** traces MAY include sanitized and length-limited prompt, response, tool argument, and tool result summaries according to the configured maximum character limit.

### Requirement: Optional Studio integration
The system SHALL support optional AgentScope Studio integration for local debugging without making Studio a production dependency.

#### Scenario: Studio disabled
- **WHEN** Studio observability is disabled
- **THEN** the application SHALL NOT attempt to connect to AgentScope Studio.

#### Scenario: Studio enabled
- **WHEN** Studio observability is enabled with a Studio URL and project name
- **THEN** agentscope-java execution SHALL initialize Studio integration so developers can inspect multi-Agent message flow in Studio.

#### Scenario: Studio unavailable
- **WHEN** Studio integration is enabled but the Studio server is unavailable
- **THEN** the application SHALL log the connection failure and SHALL NOT fail research request execution solely because Studio is unavailable.

### Requirement: Documentation for observability backends
The project documentation SHALL explain how to configure and operate Agent observability.

#### Scenario: Environment examples documented
- **WHEN** a developer reads `.env.example` or README observability docs
- **THEN** they SHALL find configuration examples for disabling observability, exporting to Langfuse, exporting to a generic OTLP backend, and enabling Studio for local debugging.

#### Scenario: Sensitive capture documented
- **WHEN** input/output capture settings are documented
- **THEN** the documentation SHALL state that full prompt/response capture is disabled by default and explain the privacy trade-off of enabling it.
