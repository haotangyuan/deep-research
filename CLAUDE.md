# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**开始任何开发工作前，必须先阅读 [doc/rules/开发者准则.md](doc/rules/开发者准则.md)。**

## Build & Run

```bash
# Build
mvn clean package -DskipTests

# Run (requires .env with DB, Redis, Tavily, LLM credentials)
java -jar target/researcher-0.0.1-SNAPSHOT.jar

# All-in-one local dev (checks deps, creates DB, builds, starts)
cp .env.example .env && vim .env && ./start.sh

# Docker
docker compose up -d

# Frontend dev
cd frontend && npm install && npm run dev  # http://localhost:5173
```

Prerequisites: Java 21, Maven 3.8+, MySQL 8.0+, Redis 6.0+.

Tests: No test sources currently exist under `src/test/`. Live integration tests require `DEEP_RESEARCH_LIVE_LLM_TESTS=true` plus model credentials.

## Architecture

Spring Boot 3.2.12 backend + React/Vite frontend. Multi-agent pipeline for automated deep research.

### Agent Pipeline (3 stages, sequential)

```
AgentPipeline.run()
  ├── ScopeAgent        → clarify user intent, produce ResearchBrief
  ├── SupervisorAgent   → plan research, call conductResearch tool repeatedly
  │     └── ResearcherAgent → execute sub-topic research
  │           └── SearchAgent → Tavily web search + webpage summarization
  └── ReportAgent       → generate final Markdown report
```

### Runtime SPI

Agents depend on `AgentRuntime` interface, not on any LLM framework directly. Two implementations:

- **agentscope-java** (default): Uses AgentScope v2 `ReActAgent` with native tool loop via `Toolkit`. Each agent stage creates a `ReActAgent` instance with `FixedOtelTracingMiddleware` and `AgentscopeTraceContextMiddleware`. Tools are adapted via `AgentscopeToolkitAdapter`.
- **langchain4j** (backup): Uses langchain4j 1.8.0 OpenAI-compatible model. Agent loop managed externally (default `runAgent()` in `ResearchChatClient`).

Switch via `RESEARCH_AGENT_FRAMEWORK=agentscope-java|langchain4j`.

### Key Classes

| Class | Role |
|---|---|
| `AgentPipeline` | Orchestrates Scope → Supervisor → Report stages |
| `DeepResearchState` | Centralized state: scope, budget counters, token usage, notes |
| `AgentRuntime` / `ResearchChatClient` | SPI for LLM framework abstraction |
| `AgentscopeJavaChatClient` | Creates `ReActAgent` per stage, wraps model in `UsageCollectingModel` |
| `FixedOtelTracingMiddleware` | Custom OTel middleware fixing Reactor async context propagation |
| `ToolRegistry` | Scans `@ResearchTool` annotations, groups by stage (`@SupervisorTool`, `@ResearcherTool`) |
| `ResearchObservation` | Creates workflow/stage OTel spans; skips tool/model spans for agentscope-native |
| `SseHub` | SSE push + Redis ZSet replay for frontend progress |
| `@QueuedAsync` / `ResearchTaskExecutor` | Bounded async task queue (10 threads, 50 capacity) |

### Observability (OpenTelemetry → Langfuse)

Three-layer span hierarchy:
- `deep_research.workflow` (root) → `deep_research.stage <name>` → `invoke_agent <name>` → `chat <model>` / `execute_tool <name>`

`FixedOtelTracingMiddleware` uses Reactor Context (`contextWrite`) + ThreadLocal stack to propagate OTel context across `subscribeOn(Schedulers.boundedElastic())` boundaries. `AgentscopeToolkitAdapter.callAsync()` creates tool spans with explicit parent context.

Config: `RESEARCH_OBSERVABILITY_ENABLED=true`, `RESEARCH_OBSERVABILITY_PROVIDER=langfuse`, `LANGFUSE_PUBLIC_KEY/SECRET_KEY`.

### Tool System

Tools are plain Java methods annotated with `@ResearchTool` + `@ResearchToolParam`, grouped by stage annotations. `ToolRegistry` scans at startup, produces `ResearchToolSpec` per stage. Runtime adapters convert to framework-native format (AgentScope `Toolkit` or langchain4j `ToolSpecification`).

### Budget

Three levels (MEDIUM/HIGH/ULTRA) in `application.yaml` controlling `max-conduct-count`, `max-search-count`, `max-concurrent-units`. Tools check counts before execution and return limit messages when exhausted.

## Environment Variables

See `.env.example`. Key ones:
- `DB_URL`, `DB_USERNAME`, `DB_PASSWORD` — MySQL
- `REDIS_HOST`, `REDIS_PORT` — Redis
- `TAVILY_API_KEY` — Web search
- `RESEARCH_AGENT_FRAMEWORK` — `agentscope-java` (default) or `langchain4j`
- `LLM_TIMEOUT` — Per-model-call timeout in seconds (default 120)
- `RESEARCH_OBSERVABILITY_ENABLED/PROVIDER` + `LANGFUSE_*` — OTel export

## Conventions

- Lombok everywhere (`@Slf4j`, `@RequiredArgsConstructor`, `@Data`)
- MyBatis-Plus for DB access (`BaseMapper`, `LambdaQueryWrapper`)
- All API endpoints under `/api/v1/`, documented via SpringDoc/Scalar at `/scalar/index.html`
- Frontend proxies `/api` to `localhost:8080` via Vite config
- Chinese comments and documentation throughout
