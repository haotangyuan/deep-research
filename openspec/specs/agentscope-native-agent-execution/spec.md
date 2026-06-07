# agentscope-native-agent-execution Specification

## Purpose
TBD - created by archiving change migrate-agent-execution-to-agentscope-native-agents. Update Purpose after archive.
## Requirements
### Requirement: Native AgentScope agent construction
The system SHALL construct AgentScope native agents for the agentscope-java runtime path.

#### Scenario: Native agent created for each workflow stage
- **WHEN** a research workflow runs with `research.agent.framework=agentscope-java`
- **THEN** Scope, Supervisor, Researcher, Search, and Report stages SHALL execute through AgentScope native agent abstractions or stage-specific wrappers backed by AgentScope native agents.

#### Scenario: Existing model configuration reused
- **WHEN** a native AgentScope agent is created
- **THEN** it SHALL use the existing model record's OpenAI-compatible `baseUrl`, `apiKey`, and model name without requiring a new user-facing model configuration flow.

#### Scenario: Native agent names are stable
- **WHEN** AgentScope tracing middleware or event streaming observes the workflow
- **THEN** each stage SHALL use stable agent names matching the Deep Research stages: `ScopeAgent`, `SupervisorAgent`, `ResearcherAgent`, `SearchAgent`, and `ReportAgent`.

### Requirement: Native Toolkit tool execution
The system SHALL expose Deep Research delegated tools through AgentScope native Toolkit execution in the agentscope-java runtime path.

#### Scenario: Supervisor toolkit registered
- **WHEN** `SupervisorAgent` runs in the agentscope-java runtime path
- **THEN** its AgentScope Toolkit SHALL expose `thinkTool`, `conductResearch`, and `researchComplete` with names, descriptions, required fields, and argument names equivalent to the existing tool contract.

#### Scenario: Researcher toolkit registered
- **WHEN** `ResearcherAgent` runs in the agentscope-java runtime path
- **THEN** its AgentScope Toolkit SHALL expose `thinkTool` and `tavilySearch` with names, descriptions, required fields, and argument names equivalent to the existing tool contract.

#### Scenario: Tool lifecycle observable
- **WHEN** an AgentScope native tool executes
- **THEN** AgentScope tracing middleware or tracer SHALL be able to observe the tool execution lifecycle including tool name, success/failure, and latency.

### Requirement: Native workflow semantics parity
The native AgentScope execution path SHALL preserve the current Deep Research workflow semantics.

#### Scenario: Scope requires clarification
- **WHEN** the native Scope agent determines clarification is needed
- **THEN** the workflow SHALL set status `NEED_CLARIFICATION`, publish the same clarification SSE/message behavior, and SHALL NOT start Supervisor research.

#### Scenario: Supervisor delegates research
- **WHEN** the native Supervisor agent calls `conductResearch`
- **THEN** the workflow SHALL delegate to the native Researcher stage, append the result to supervisor notes, and publish the same parent-child SSE event relationship as the current workflow.

#### Scenario: Researcher delegates search
- **WHEN** the native Researcher agent calls `tavilySearch`
- **THEN** the workflow SHALL delegate to the native Search stage, append search notes, and return a tool result to the Researcher agent.

#### Scenario: Research completes
- **WHEN** the native Supervisor agent calls `researchComplete`
- **THEN** the workflow SHALL proceed to native Report generation and produce a final Markdown report compatible with the current frontend.

### Requirement: Budget enforcement in native tools
The native AgentScope tool path SHALL enforce the same research budget rules as the current workflow.

#### Scenario: Conduct budget reached
- **WHEN** `conductResearch` is requested after `maxConductCount` has been reached
- **THEN** the AgentScope native tool SHALL return the same quota guidance behavior and SHALL NOT invoke another Researcher run.

#### Scenario: Search budget reached
- **WHEN** `tavilySearch` is requested after `maxSearchCount` has been reached
- **THEN** the AgentScope native tool SHALL return the same quota guidance behavior and SHALL NOT invoke Tavily or SearchAgent again.

#### Scenario: Budget counters updated
- **WHEN** a native delegated tool executes successfully
- **THEN** the workflow SHALL update the same conduct/search counters in `DeepResearchState` used by status and token persistence.

### Requirement: Native execution verification
The migration SHALL include verification for native AgentScope execution without requiring live LLM credentials.

#### Scenario: Offline native adapter tests
- **WHEN** the backend test suite runs
- **THEN** it SHALL verify native agent factory, toolkit adapter, message conversion, budget enforcement, and tool delegation using fake model/tool components.

#### Scenario: Optional live native workflow
- **WHEN** live LLM credentials and explicit integration flags are provided
- **THEN** a minimal research workflow SHALL be executable through the AgentScope native runtime and SHALL emit observable Agent/model/tool lifecycle events.

