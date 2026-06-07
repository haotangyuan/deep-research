## ADDED Requirements

### Requirement: Agentscope native runtime execution
The agentscope-java runtime SHALL execute Deep Research workflow stages through AgentScope native Agent and Toolkit abstractions rather than only calling an AgentScope chat model.

#### Scenario: Agentscope runtime selected
- **WHEN** the application starts with `research.agent.framework=agentscope-java`
- **THEN** the selected runtime SHALL construct native AgentScope agents and toolkits for workflow execution.

#### Scenario: Langchain4j rollback selected
- **WHEN** the application starts with `research.agent.framework=langchain4j`
- **THEN** the application SHALL continue using the langchain4j backup runtime without depending on AgentScope native Agent or Toolkit classes.

#### Scenario: Native types remain inside adapter boundary
- **WHEN** a workflow runs through the agentscope-java native runtime
- **THEN** AgentScope message, agent, toolkit, middleware, hook, and tool request types SHALL NOT be stored in domain entities, REST DTOs, SSE payloads, or `DeepResearchState`.

### Requirement: Runtime tool contract parity under native execution
The agentscope-java native runtime SHALL preserve existing tool contract equivalence.

#### Scenario: Tool names remain compatible
- **WHEN** a model requests a tool in the native agentscope-java runtime
- **THEN** the tool names `thinkTool`, `conductResearch`, `researchComplete`, and `tavilySearch` SHALL remain accepted and semantically equivalent to the current workflow.

#### Scenario: Required tool behavior preserved
- **WHEN** SupervisorAgent or ResearcherAgent asks the native AgentScope agent for the next action
- **THEN** the selected runtime SHALL preserve required tool-call behavior or an equivalent reminder/reprompt strategy when no tool action is produced.

#### Scenario: Token accounting preserved
- **WHEN** native AgentScope model calls return usage metadata
- **THEN** the workflow SHALL continue accumulating input and output token totals in `DeepResearchState` and persist them on session update.
