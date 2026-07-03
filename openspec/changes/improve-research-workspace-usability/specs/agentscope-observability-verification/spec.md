## ADDED Requirements

### Requirement: Unified OpenTelemetry trace chain
The backend SHALL use one OpenTelemetry provider for application workflow/stage spans and AgentScope native agent/model/tool spans and SHALL export that provider to the configured Langfuse OTLP endpoint.

#### Scenario: AgentScope tracing enabled
- **WHEN** observability is enabled and an AgentScope agent is created
- **THEN** `TracingMiddleware` uses the initialized SDK provider and emits native lifecycle spans under the active workflow/stage context

#### Scenario: Langfuse export
- **WHEN** valid Langfuse credentials and endpoint are configured
- **THEN** a test span batch receives a successful OTLP export result without exposing credentials

### Requirement: Maintainable resume description
The root README SHALL contain five resume-ready project bullets that accurately describe the current Python hybrid architecture and SHALL identify AgentScope's concrete responsibilities.

#### Scenario: Framework evolves
- **WHEN** AgentScope responsibilities or project architecture change
- **THEN** collaborators can update the canonical five bullets in README without consulting obsolete Java documentation
