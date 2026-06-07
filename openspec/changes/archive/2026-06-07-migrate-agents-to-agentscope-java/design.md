## Context

The backend is a Spring Boot 3.2.12, Java 21 application. Its current LLM runtime is langchain4j 1.8.0 with `langchain4j` and `langchain4j-open-ai` dependencies. The project uses low-level `ChatModel.chat(ChatRequest)` calls, `ToolSpecification`, `ToolChoice.REQUIRED`, `ToolExecutionRequest`, `ToolExecutionResultMessage`, `MessageWindowChatMemory`, and `TokenUsage`. It does not use langchain4j AiServices, RAG, embeddings, vector stores, or document loaders.

The existing workflow is already project-owned:

- `AgentPipeline`: Scope -> Supervisor -> Report, with Researcher/Search delegated inside Supervisor/Researcher tool actions.
- `ScopeAgent`: turns chat history into clarification and research-brief JSON.
- `SupervisorAgent`: runs a manual plan-action loop with required tools, delegates `conductResearch` to `ResearcherAgent`, and stops on `researchComplete`.
- `ResearcherAgent`: runs a manual plan-action loop with required tools, delegates `tavilySearch` to `SearchAgent`, then compresses research notes.
- `SearchAgent`: calls Tavily directly and uses the LLM only for webpage summarization.
- `ReportAgent`: generates the final Markdown report.

AgentScope Java 2.0 documentation says the current latest Maven version is `2.0.0-RC1`, requires JDK 17+, and can be added via `io.agentscope:agentscope-core` when only a bare ReAct/model runtime is needed. The v2 model layer has `OpenAIChatModel`, supports OpenAI-compatible endpoints through `baseUrl`, returns `ChatResponse` with `ChatUsage`, and accepts messages, tools, and `GenerateOptions`. Its tool layer exposes JSON schemas through `AgentTool`/`ToolBase` or `@Tool`/`@ToolParam`, and its message layer represents text, tool calls, tool results, and token usage as typed blocks. Official references used:

- AgentScope Java quickstart: https://java.agentscope.io/v2/en/docs/quickstart.html
- AgentScope Java model docs: https://java.agentscope.io/v2/en/docs/building-blocks/model.html
- AgentScope Java tool docs: https://java.agentscope.io/v2/en/docs/building-blocks/tool.html
- AgentScope Java agent docs: https://java.agentscope.io/v2/en/docs/building-blocks/agent.html
- AgentScope Java message/event docs: https://java.agentscope.io/v2/en/docs/building-blocks/message-and-event.html
- LangChain4j chat model docs: https://docs.langchain4j.dev/tutorials/chat-and-language-models/
- LangChain4j tool docs: https://docs.langchain4j.dev/tutorials/tools/

Assumption: the migration should make agentscope-java the primary runtime after parity is verified, while keeping langchain4j as a selectable backup runtime in the same application.

## Goals / Non-Goals

**Goals:**

- Preserve the five-agent collaboration architecture and existing plan-action control flow.
- Preserve REST APIs, SSE payloads, database writes, frontend behavior, budget limits, and final report format.
- Add agentscope-java as a first-class runtime using the existing OpenAI-compatible model configuration (`baseUrl`, `apiKey`, `model`).
- Keep langchain4j runnable as a backup backend through configuration, not as dead source copies.
- Remove direct framework types from shared workflow state and agent business logic.
- Preserve tool names, argument names, required-tool behavior, tool result feedback, and token accounting.
- Add tests that verify the same workflow contracts for both runtimes without requiring real LLM calls.

**Non-Goals:**

- No frontend rewrite.
- No database schema change.
- No RAG, embeddings, vector store, MCP, A2A, Harness workspace, or long-term memory adoption in this migration.
- No change to Tavily search behavior beyond framework-neutral tool delegation.
- No attempt to make langchain4j and agentscope-java outputs byte-for-byte identical from live models; acceptance is based on unchanged prompts, control flow, schemas, report contract, and deterministic adapter tests.

## Decisions

### 1. Introduce a framework-neutral runtime boundary

Add an internal runtime package, for example `application.agent.runtime`, with framework-neutral contracts:

- `AgentFramework`: `AGENTSCOPE_JAVA`, `LANGCHAIN4J`
- `AgentRuntime`: creates per-research model clients and memory objects
- `ResearchChatClient`: sends chat requests and returns normalized responses
- `ResearchChatRequest`: messages, tools, tool choice, and generation options
- `ResearchChatResponse`: assistant message, tool calls, token usage, finish reason
- `ResearchMessage`: role, text content, tool calls, tool results, optional framework metadata
- `ResearchToolSpec`: name, description, JSON-schema parameters
- `ResearchToolCall`: id, name, arguments as `JsonNode` or JSON string
- `ResearchTokenUsage`: input tokens and output tokens

`DeepResearchState` should store `List<ResearchMessage>` instead of `List<dev.langchain4j.data.message.ChatMessage>`. `ResearchServiceImpl` should convert database chat messages into `ResearchMessage`; framework adapters should convert only at the runtime boundary.

Rationale: this keeps the workflow code stable and makes both backends testable. It also avoids leaving langchain4j message types embedded in state while claiming a migration has happened.

Alternatives considered:

- Directly rewrite each agent to AgentScope types. Rejected because the backup runtime would require duplicate agents or framework-specific branches in every agent.
- Keep langchain4j message/tool annotations as the shared contract and only add AgentScope converters. Rejected because agentscope-java would still depend on langchain4j contracts in core business code.

### 2. Keep the manual plan-action loops

Do not replace Supervisor/Researcher with AgentScope `ReActAgent` for the first migration. Use AgentScope's model/tool/message primitives through the neutral adapter:

- Build an `OpenAIChatModel` from the project's existing `Model` entity.
- Use `GenerateOptions` with required tool choice for Supervisor/Researcher calls.
- Pass neutral tool schemas converted to AgentScope tool schemas.
- Collect the final accumulated model response from the returned `Flux<ChatResponse>`.
- Extract `ToolUseBlock` instances into `ResearchToolCall`.
- Add assistant and tool-result messages back into neutral memory exactly as the current loop does.

Rationale: AgentScope `ReActAgent` is designed to run its own reasoning-acting loop. The current product already has explicit loop control, budget checks, delegated sub-agent execution, SSE event publication, and persistence. Reusing AgentScope's primitives gives the migration without changing the workflow.

Alternatives considered:

- Use `ReActAgent` for Supervisor and Researcher. Rejected for the initial migration because it would move budget enforcement and delegated execution into framework behavior and risk changing loop semantics.
- Use `HarnessAgent`. Rejected because Harness adds workspace, session, memory, sandbox, and subagent systems that duplicate project-owned state/SSE/persistence concerns.

### 3. Make langchain4j backup a real runtime

Keep langchain4j dependencies and implement `Langchain4jAgentRuntime` behind the same neutral contracts. Add a property such as:

```yaml
research:
  agent:
    framework: agentscope-java
```

Accepted values should be `agentscope-java` and `langchain4j`. Invalid values should fail fast at startup. The final migration can default to `agentscope-java`; operations can set `research.agent.framework=langchain4j` to roll back without code changes.

Rationale: this satisfies the backup requirement while keeping one application artifact. It also lets tests run the same scenarios against both frameworks.

Alternative considered: Maven profiles that build either framework. Rejected because the user asked for both frameworks to be runnable; compile-time profiles make rollback slower and reduce parity testing.

### 4. Replace framework annotations with project-owned tool metadata

Create project-owned tool annotations or descriptors, for example:

- `@ResearchTool(name, description)`
- `@ResearchToolParam(name, description, required)`

Update the four tool methods to use those annotations. `ToolRegistry` becomes a neutral registry that scans marker annotations (`@SupervisorTool`, `@ResearcherTool`) and project-owned tool metadata, then exposes `ResearchToolSpec` and `ResearchToolExecutor`.

Adapters convert `ResearchToolSpec` into:

- langchain4j `ToolSpecification`
- agentscope-java `ToolSchema` or `ToolBase`/`AgentTool`

Rationale: tool names and schemas remain a project contract, while each framework receives its required representation. The delegated execution model stays unchanged: `conductResearch` and `tavilySearch` are still intercepted by the agent layer to run sub-agents; `thinkTool` and `researchComplete` use normal tool executors.

Alternative considered: dual-annotate each method with both frameworks' annotations. Rejected because it leaks both frameworks into business tools and creates schema drift risk.

### 5. Preserve structured JSON handling before adopting AgentScope structured output

Keep the existing prompt + Jackson parsing path for `ScopeAgent` and `SearchAgent` during the migration. The adapters should support plain text JSON responses and return the same text extraction behavior as langchain4j.

AgentScope structured output can be evaluated later, but it should not be introduced in this change unless tests prove it preserves the exact expected `ScopeSchema` and `SummarySchema` field contracts.

Rationale: structured output is a behavior-affecting improvement. The requested change is a framework migration, so the minimal safe path is to keep existing schema prompts and parsing semantics.

### 6. Token usage remains a workflow-level invariant

Every LLM call must map framework usage metadata to `ResearchTokenUsage` and add it to `DeepResearchState.totalInputTokens` and `totalOutputTokens`. For agentscope-java, use `ChatUsage` from the final `ChatResponse` or assistant `Msg` where available. For langchain4j, use `ChatResponse.tokenUsage()`.

If a provider omits usage, the adapter should return zero counts and log a warning with the framework and model id. It should not break the workflow solely because usage metadata is absent.

### 7. Verification is contract-first

Use fake runtime clients for deterministic tests:

- Adapter tests: neutral request -> framework request, framework response -> neutral response.
- Tool registry tests: each stage exposes the expected tool names and JSON parameters.
- Agent loop tests: Supervisor and Researcher honor required tools, reminders, budget limits, tool-result memory, and completion.
- Workflow tests: Scope clarification path, full research path, failure path, token accumulation, and SSE event publication.

Add a parameterized contract test suite that runs with `agentscope-java` and `langchain4j` runtime implementations. Live model integration tests should be opt-in through environment variables because they require external credentials.

## Risks / Trade-offs

- AgentScope Java 2.0 is currently `2.0.0-RC1` -> Pin the version, isolate it behind adapters, and keep langchain4j rollback available.
- AgentScope API differences or breaking changes -> Keep all direct AgentScope imports in adapter packages and avoid leaking them into state, tools, controllers, or domain objects.
- Required tool behavior may differ by provider -> Preserve the existing reminder loop for missing tool calls and test `ToolChoice.Required` mapping in the AgentScope adapter.
- Tool schema drift -> Generate both framework schemas from one project-owned `ResearchToolSpec` and assert the four tool contracts in tests.
- Live LLM outputs can differ despite identical prompts -> Keep prompts and loop semantics unchanged, validate schema/report contracts, and use deterministic fake clients for regression tests.
- Reactor blocking in queued workers -> Block only inside the existing queued background execution path, and configure model execution timeout consistently with the current `llm.timeout`.
- Token usage may not be returned by all OpenAI-compatible providers -> Treat missing usage as zero with a warning, while preserving session completion.
- Migration touches cross-cutting code -> Implement in layers: neutral contracts first, langchain4j adapter second, agentscope adapter third, then agent code migration.

## Migration Plan

1. Capture the current langchain4j runtime as `Langchain4jAgentRuntime` behind neutral contracts and verify existing tests still pass with `research.agent.framework=langchain4j`.
2. Replace `DeepResearchState.chatHistory`, `AgentAbility`, and `MemoryUtil` usages with neutral message/memory contracts.
3. Convert tool annotations and `ToolRegistry` to project-owned tool specs and executors; add schema tests.
4. Add agentscope-java dependency (`io.agentscope:agentscope-core:2.0.0-RC1`) and implement `AgentscopeJavaAgentRuntime`.
5. Wire framework selection through Spring configuration and make `agentscope-java` the default only after contract tests pass.
6. Run unit and workflow contract tests for both frameworks.
7. Update README/startup documentation with both runtime choices and rollback instructions.

Rollback: set `research.agent.framework=langchain4j` and restart the backend. Because API, database, frontend, and workflow state contracts remain unchanged, rollback does not require data migration.

## Open Questions

- None blocking. The implementation should confirm the exact AgentScope Maven artifact names and API signatures against `2.0.0-RC1` during dependency integration, then adjust only adapter code if the published API differs from the documentation.
