## ADDED Requirements

### Requirement: Runtime observability boundary
The system SHALL integrate Agent observability without breaking runtime framework selection or langchain4j rollback support.

#### Scenario: Agentscope runtime emits native telemetry
- **WHEN** the application runs with `research.agent.framework=agentscope-java` and observability export is enabled
- **THEN** the agentscope-java runtime path SHALL use AgentScope Java tracing integration for supported agent, model, tool, and formatting activities.

#### Scenario: Langchain4j runtime remains available
- **WHEN** the application runs with `research.agent.framework=langchain4j`
- **THEN** the application SHALL start and execute research workflows without requiring AgentScope Java telemetry classes in the langchain4j adapter path.

#### Scenario: Observability disabled for either runtime
- **WHEN** observability is disabled
- **THEN** both `agentscope-java` and `langchain4j` runtime selections SHALL preserve their existing chat, tool-call parsing, token accounting, REST API, and SSE behavior.

#### Scenario: Runtime context attributes are consistent
- **WHEN** either runtime produces a model call span or workflow span
- **THEN** runtime-identifying attributes SHALL use the same `agent.framework` values as startup framework selection.
