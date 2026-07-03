## ADDED Requirements

### Requirement: Native lifecycle event bridge
The system SHALL translate relevant AgentScope reply, model, tool, task, and worker lifecycle activity into stable project events without changing existing SSE event names.

#### Scenario: Runtime activity
- **WHEN** an AgentScope agent reasons, calls a model, executes a tool, or updates a task
- **THEN** the bridge SHALL emit normalized metadata suitable for persistence, tracing, and frontend visualization

### Requirement: Frontend compatibility
The frontend SHALL continue to render existing workflow events and SHALL display optional AgentScope task and worker metadata when present.

#### Scenario: Older event payload
- **WHEN** an event does not contain AgentScope metadata
- **THEN** the frontend SHALL render the same timeline and Agent Flow behavior as before

#### Scenario: Native task metadata
- **WHEN** an event contains AgentScope task or worker metadata
- **THEN** the Agent Flow SHALL show the corresponding task or worker node and state without duplicate or unstable nodes

### Requirement: Native observability integration
The system SHALL combine durable workflow spans with AgentScope-native agent, model, and tool tracing and SHALL preserve sensitive-data redaction.

#### Scenario: Observability enabled
- **WHEN** OTLP or Langfuse export is enabled
- **THEN** a research trace SHALL include workflow and stage spans plus AgentScope runtime spans correlated by research, user, model, budget, stage, task, and worker identifiers

### Requirement: Event volume control
The bridge SHALL avoid persisting high-frequency token delta events as separate workflow records.

#### Scenario: Streaming model response
- **WHEN** AgentScope emits multiple text delta events
- **THEN** the system SHALL stream or aggregate them as appropriate without creating one database workflow event per delta

