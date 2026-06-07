## 1. Baseline Protection

- [x] 1.1 Add characterization tests for current langchain4j message conversion from persisted chat records into workflow chat history.
- [x] 1.2 Add characterization tests for current Supervisor and Researcher budget behavior when `conductResearch` or `tavilySearch` quotas are reached.
- [x] 1.3 Add characterization tests for current tool stage membership and required tool names: `thinkTool`, `conductResearch`, `tavilySearch`, and `researchComplete`.
- [x] 1.4 Add workflow-level fake-model tests for clarification, successful research, and failed JSON parsing paths before changing runtime types.

## 2. Framework-Neutral Runtime Contracts

- [x] 2.1 Create neutral runtime contracts for framework selection, chat requests, chat responses, messages, tool specs, tool calls, tool results, and token usage.
- [x] 2.2 Replace `DeepResearchState.chatHistory` with neutral messages and update state construction in `ResearchServiceImpl`.
- [x] 2.3 Replace `AgentAbility` framework fields with neutral chat client and neutral memory abstractions.
- [x] 2.4 Update `MemoryUtil` to render neutral messages with the existing `Human:`, `AI:`, `System:`, and `Tool:` prefixes.
- [x] 2.5 Add configuration binding and validation for `research.agent.framework` with `agentscope-java` and `langchain4j` as the only accepted values.

## 3. Langchain4j Backup Runtime

- [x] 3.1 Implement `Langchain4jAgentRuntime` behind the neutral runtime contracts using the existing langchain4j model creation behavior.
- [x] 3.2 Implement langchain4j converters for neutral messages, tool specifications, tool calls, tool result messages, and token usage.
- [x] 3.3 Update `ModelFactory` and `ModelHandler` so langchain4j models are created only inside the langchain4j runtime adapter.
- [x] 3.4 Verify the characterization tests pass with `research.agent.framework=langchain4j`.

## 4. Neutral Tool Registry

- [x] 4.1 Create project-owned tool metadata annotations or descriptors for tool names, descriptions, parameters, and required fields.
- [x] 4.2 Update tool detail classes to use project-owned metadata while preserving the exact current tool names and argument names.
- [x] 4.3 Refactor `ToolRegistry` to expose neutral `ResearchToolSpec` and neutral executors grouped by `SupervisorTool` and `ResearcherTool`.
- [x] 4.4 Add tests asserting the neutral registry produces equivalent stage tool contracts for both framework adapters.

## 5. Agent Workflow Refactor

- [x] 5.1 Refactor `ScopeAgent` to use neutral memory and chat calls while preserving existing JSON prompts, Jackson parsing, token accumulation, and clarification events.
- [x] 5.2 Refactor `SupervisorAgent` to use neutral tool specs, required tool choice, neutral tool calls, delegated `conductResearch`, and neutral tool-result messages.
- [x] 5.3 Refactor `ResearcherAgent` to use neutral tool specs, required tool choice, delegated `tavilySearch`, neutral tool-result messages, and existing compression behavior.
- [x] 5.4 Refactor `SearchAgent` to use neutral chat calls for webpage summarization while preserving Tavily search and fallback behavior.
- [x] 5.5 Refactor `ReportAgent` to use neutral chat calls while preserving final Markdown publication behavior.

## 6. Agentscope-Java Runtime

- [x] 6.1 Add pinned agentscope-java dependency properties and `io.agentscope:agentscope-core:2.0.0-RC1` to Maven while retaining langchain4j dependencies.
- [x] 6.2 Implement `AgentscopeJavaAgentRuntime` model creation from existing `Model` records using OpenAI-compatible `baseUrl`, `apiKey`, and model name.
- [x] 6.3 Implement agentscope-java request execution, including message conversion, tool schema conversion, required tool choice mapping, timeout handling, and final response extraction.
- [x] 6.4 Implement agentscope-java response conversion for assistant text, tool calls, tool result blocks, finish reason, and token usage.
- [x] 6.5 Add adapter tests for agentscope-java message conversion, tool-choice mapping, tool-call extraction, and missing-usage handling.

## 7. Dual Runtime Verification

- [x] 7.1 Add Spring wiring so the selected runtime is injected into agents and invalid runtime configuration fails at startup.
- [x] 7.2 Add parameterized workflow contract tests that run against both `agentscope-java` and `langchain4j` fake runtime implementations.
- [x] 7.3 Add optional live integration tests gated by environment variables for a minimal OpenAI-compatible workflow through each runtime.
- [x] 7.4 Update README or startup documentation with runtime selection, agentscope-java default behavior, and langchain4j rollback instructions.
- [x] 7.5 Run the full Maven test suite and record any remaining manual verification steps for live LLM parity.
