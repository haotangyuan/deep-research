## ADDED Requirements

### Requirement: Runtime framework selection
The system SHALL support selecting the Deep Research agent framework at startup with `agentscope-java` and `langchain4j` as supported values.

#### Scenario: Agentscope runtime selected
- **WHEN** the application starts with the framework configured as `agentscope-java`
- **THEN** Deep Research workflow LLM calls, tool-call parsing, message conversion, and token accounting SHALL use the agentscope-java runtime adapter.

#### Scenario: Langchain4j backup selected
- **WHEN** the application starts with the framework configured as `langchain4j`
- **THEN** Deep Research workflow LLM calls, tool-call parsing, message conversion, and token accounting SHALL use the langchain4j runtime adapter.

#### Scenario: Invalid framework value
- **WHEN** the application starts with an unsupported framework value
- **THEN** startup SHALL fail with a clear configuration error before accepting research requests.

### Requirement: Unchanged API and frontend contracts
The migration SHALL NOT change the public REST API, SSE connection contract, SSE event payload shape, database session update behavior, or frontend interaction flow.

#### Scenario: Research message accepted
- **WHEN** a user sends a research message through the existing message API
- **THEN** the API response SHALL remain compatible with the current `SendMessageRespDTO` contract and the selected runtime SHALL be transparent to the caller.

#### Scenario: Progress events emitted
- **WHEN** any selected runtime executes a research workflow
- **THEN** the existing SSE event types, parent-child event relationships, message publications, heartbeat behavior, and replay behavior SHALL remain compatible with the current frontend.

### Requirement: Preserved multi-agent workflow
The system SHALL preserve the current five-agent collaboration flow: ScopeAgent, SupervisorAgent, ResearcherAgent, SearchAgent, and ReportAgent.

#### Scenario: User needs clarification
- **WHEN** ScopeAgent determines that the user request needs clarification
- **THEN** the workflow SHALL stop before research, set the session status to `NEED_CLARIFICATION`, publish the clarification event, and publish the assistant clarification message.

#### Scenario: Research request is clear
- **WHEN** ScopeAgent produces a research brief
- **THEN** SupervisorAgent SHALL run the research plan-action loop, delegate subtopics to ResearcherAgent, ResearcherAgent SHALL delegate web queries to SearchAgent, and ReportAgent SHALL generate the final Markdown report.

#### Scenario: Budget limits reached
- **WHEN** `maxConductCount` or `maxSearchCount` is reached
- **THEN** the corresponding tool delegation SHALL return the same quota guidance behavior used by the current workflow and SHALL NOT exceed the configured budget.

### Requirement: Tool contract equivalence
The system SHALL expose equivalent tool names, descriptions, argument names, required fields, and stage groupings for both framework runtimes.

#### Scenario: Supervisor tools registered
- **WHEN** SupervisorAgent requests available tools
- **THEN** it SHALL receive `thinkTool`, `conductResearch`, and `researchComplete` tool specifications with the same argument contracts under both runtimes.

#### Scenario: Researcher tools registered
- **WHEN** ResearcherAgent requests available tools
- **THEN** it SHALL receive `thinkTool` and `tavilySearch` tool specifications with the same argument contracts under both runtimes.

#### Scenario: Delegated tool call executed
- **WHEN** the model requests `conductResearch` or `tavilySearch`
- **THEN** the agent layer SHALL intercept the call, enforce budget limits, execute the delegated sub-agent flow, and append a tool-result message back into memory.

#### Scenario: Required tool behavior
- **WHEN** SupervisorAgent or ResearcherAgent asks the model for the next action
- **THEN** the selected runtime SHALL request required tool-call behavior and SHALL preserve the current reminder handling when the model returns no tool calls.

### Requirement: Framework-neutral state and memory
The workflow state SHALL NOT expose langchain4j or agentscope-java message, model, memory, or tool request types outside runtime adapter boundaries.

#### Scenario: Chat history loaded
- **WHEN** stored chat messages are loaded from the database
- **THEN** they SHALL be converted into project-owned neutral messages before entering `DeepResearchState`.

#### Scenario: Memory rendered for prompts
- **WHEN** ScopeAgent renders prior messages into prompt text
- **THEN** the rendered format SHALL preserve the current `Human:`, `AI:`, `System:`, and `Tool:` role prefixes.

### Requirement: Model configuration compatibility
The agentscope-java runtime SHALL use the existing model records and OpenAI-compatible endpoint configuration rather than requiring new user-facing model setup.

#### Scenario: Agentscope model created
- **WHEN** a research session selects a configured model
- **THEN** the agentscope-java runtime SHALL build an OpenAI-compatible chat model using that model's `baseUrl`, `apiKey`, and model name.

#### Scenario: Langchain4j model created
- **WHEN** a research session runs with the backup runtime
- **THEN** the langchain4j runtime SHALL keep using the same `baseUrl`, `apiKey`, model name, timeout, request logging, and response logging settings currently supported.

### Requirement: Structured JSON and report behavior
The migration SHALL preserve the current structured JSON parsing contracts and final report contract.

#### Scenario: Scope JSON parsed
- **WHEN** ScopeAgent asks for clarification or a research brief
- **THEN** the selected runtime's text response SHALL be parsed into the existing `ScopeSchema` classes and failures SHALL preserve the current failed-status behavior.

#### Scenario: Search summary JSON parsed
- **WHEN** SearchAgent summarizes webpage content
- **THEN** the selected runtime's text response SHALL be parsed into `SummarySchema`, and parsing failures SHALL preserve the current fallback summary behavior.

#### Scenario: Final report generated
- **WHEN** ReportAgent completes
- **THEN** the final assistant message SHALL remain a Markdown research report based on the research brief and supervisor notes.

### Requirement: Token accounting parity
The system SHALL continue accumulating input and output token counts for every LLM call where framework/provider usage metadata is available.

#### Scenario: Usage metadata available
- **WHEN** the selected runtime returns token usage metadata
- **THEN** the workflow SHALL add input and output counts to `DeepResearchState` and persist the totals on session update.

#### Scenario: Usage metadata absent
- **WHEN** the selected runtime or provider omits token usage metadata
- **THEN** the workflow SHALL continue safely, count the missing usage as zero, and log the missing metadata.

### Requirement: Verification coverage for both runtimes
The migration SHALL include automated verification that exercises equivalent workflow contracts for `agentscope-java` and `langchain4j`.

#### Scenario: Contract tests run for both runtimes
- **WHEN** the backend test suite runs
- **THEN** adapter, tool registry, agent loop, and workflow contract tests SHALL execute against both supported runtime selections without requiring live LLM credentials.

#### Scenario: Optional live model verification
- **WHEN** live LLM credentials and explicit integration-test flags are provided
- **THEN** optional integration tests SHALL be able to execute a minimal research workflow through the configured OpenAI-compatible endpoint for each selected runtime.
