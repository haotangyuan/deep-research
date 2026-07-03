## ADDED Requirements

### Requirement: Durable hybrid workflow boundary
The system SHALL retain deterministic project-owned business state transitions while AgentScope owns cognitive stage execution and multi-agent runtime behavior.

#### Scenario: Complete research
- **WHEN** a user starts and approves a research request
- **THEN** the existing workflow statuses, REST responses, SSE completion marker, database records, and Redis keys SHALL remain compatible while AgentScope executes the cognitive phases

### Requirement: Long-lived AgentScope runtime session
The system SHALL maintain isolated AgentScope agents and `AgentState` instances for each active research and stable stage or worker identity.

#### Scenario: Parallel workers
- **WHEN** multiple research workers execute concurrently
- **THEN** each worker SHALL use isolated mutable AgentScope state and SHALL not leak context into another worker

#### Scenario: Workflow cleanup
- **WHEN** research completes, fails, or is cancelled
- **THEN** the active runtime session SHALL be released after any required checkpoint snapshot is saved

### Requirement: Native context and task management
The system SHALL use AgentScope context configuration and native task state to track research task lifecycle without removing deterministic project limits.

#### Scenario: Supervisor creates tasks
- **WHEN** the Supervisor produces valid research tasks
- **THEN** corresponding AgentScope tasks SHALL be created and transition through pending, in-progress, and completed states

#### Scenario: Budget enforcement
- **WHEN** a model attempts work beyond configured conduct, search, concurrency, or token limits
- **THEN** project middleware and code guards SHALL reject or bound the work regardless of Agent decisions

### Requirement: AgentScope research team
The system SHALL execute Supervisor and Researcher collaboration as a budget-constrained in-process AgentScope research team using only public framework APIs.

#### Scenario: Concurrent team execution
- **WHEN** a research plan contains multiple independent tasks
- **THEN** AgentScope worker agents SHALL execute up to `maxConcurrentUnits` tasks concurrently and results SHALL be merged in deterministic task order

#### Scenario: Worker failure
- **WHEN** one worker fails
- **THEN** its native task SHALL record failure metadata, other workers SHALL continue, and the final report SHALL retain the existing degraded-result behavior

### Requirement: Compatibility and recovery
The hybrid runtime SHALL preserve HITL, cancellation, checkpoint resume, cache, timeout, and fallback behavior.

#### Scenario: Direction confirmation
- **WHEN** HITL mode requests direction confirmation
- **THEN** the workflow SHALL persist both business and AgentScope runtime snapshots before waiting and SHALL resume after approval without repeating completed work

#### Scenario: Recover failed research
- **WHEN** a failed or cancelled research is resumed
- **THEN** the system SHALL reconstruct the AgentScope runtime from the compatible checkpoint and continue from the appropriate business phase

