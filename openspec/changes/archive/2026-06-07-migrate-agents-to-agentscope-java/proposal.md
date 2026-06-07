## Why

Deep Research currently couples its agent runtime, model calls, message memory, tool schemas, and token accounting to langchain4j 1.8.0 even though the workflow is manually orchestrated rather than built on langchain4j AiServices. Migrating the runtime boundary to agentscope-java can align the project with a purpose-built multi-agent framework, but the migration must preserve the existing Spring Boot API, SSE progress behavior, research workflow, and report format.

The project also needs a safe rollback path. The existing langchain4j implementation must remain available as a runnable backup while agentscope-java is introduced and verified.

## What Changes

- Add an agentscope-java-backed agent runtime for the existing five-agent workflow: ScopeAgent, SupervisorAgent, ResearcherAgent, SearchAgent, and ReportAgent.
- Keep the current langchain4j-backed runtime in the codebase as an independently runnable backup.
- Add a framework selection mechanism so a deployment can run either `langchain4j` or `agentscope-java` without changing API contracts or frontend behavior.
- Replace direct framework usage in agent orchestration with internal adapters for chat messages, model calls, tool specifications, tool execution requests/results, memory rendering, and token usage.
- Port the existing tool definitions and delegated tool execution model to agentscope-java-compatible tool schemas while preserving tool names and arguments:
  - `thinkTool`
  - `conductResearch`
  - `tavilySearch`
  - `researchComplete`
- Preserve the current budget controls, plan-action loops, structure-output parsing, Tavily search flow, SSE event stream, persistence updates, and final Markdown report shape.
- Add verification coverage that can run the same workflow-level expectations against both framework backends.
- No frontend route, REST API, SSE contract, database schema, or user-facing report contract is intentionally changed.

## Capabilities

### New Capabilities
- `agent-framework-runtime`: Covers framework-selectable Deep Research agent execution, agentscope-java migration behavior, langchain4j backup operation, tool-call equivalence, token accounting, and unchanged API/frontend contracts.

### Modified Capabilities
- None. There are no existing OpenSpec capability specs in `openspec/specs/`; this change records the runtime requirements as a new capability.

## Impact

- Backend dependencies: add agentscope-java artifacts and retain langchain4j dependencies for the backup runtime.
- Agent layer: ScopeAgent, SupervisorAgent, ResearcherAgent, SearchAgent, ReportAgent, AgentAbility, and AgentPipeline runtime wiring.
- Model layer: ModelFactory and ModelHandler need framework-specific model creation or adapter-backed model clients.
- Tool layer: ToolRegistry and tool detail classes need a framework-neutral tool contract plus langchain4j and agentscope-java schema adapters.
- State and memory: DeepResearchState and MemoryUtil currently use langchain4j message types and need neutral internal message handling.
- Tests: add adapter, tool-schema, agent-loop, and workflow contract tests for both runtime choices.
- Operations: add configuration for selecting the runtime and document how to start either backend.
