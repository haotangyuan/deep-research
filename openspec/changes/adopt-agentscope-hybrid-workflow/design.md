## Context

The FastAPI backend already has a durable workflow, MySQL/Redis persistence, HITL, cancellation, bounded concurrency, search caching, fallbacks, SSE replay, and frontend workflow visualization. AgentScope currently creates a fresh `Agent` for each model call, so native state, context compression, tasks, middleware, and team semantics are not retained across a research run. AgentScope App provides a broader service stack, but replacing the existing FastAPI service would duplicate user/session/storage contracts and violate compatibility constraints.

## Goals / Non-Goals

**Goals:**

- Make AgentScope the runtime owner for long-lived agents, runtime state, task tracking, context compression, middleware, and execution events.
- Represent Supervisor and Researcher execution as an in-process AgentScope research team using public APIs.
- Keep the existing outer workflow deterministic, durable, recoverable, and protocol-compatible.
- Preserve existing concurrency, budget, cache, timeout, fallback, and observability guarantees.
- Surface native runtime task and lifecycle metadata in the existing frontend Agent Flow.

**Non-Goals:**

- Replacing FastAPI, MySQL, Redis, JWT, the public REST/SSE protocol, or the frontend application.
- Adopting private `agentscope.app._*` team APIs or replacing the service with AgentScope App.
- Making the Leader model solely responsible for enforcing budgets, HITL, cancellation, or durable state transitions.
- Adding unrelated MCP servers, RAG, or sandboxed code execution in this change.

## Decisions

### Retain a thin durable workflow coordinator

`AgentPipeline` remains the source of truth for QUEUE, SCOPE, AWAITING_DIRECTION_CONFIRM, IN_RESEARCH, IN_REPORT, COMPLETED, FAILED, and CANCELLED transitions. AgentScope owns execution inside each cognitive phase. This preserves deterministic recovery while avoiding a second service/session model.

### Use a per-research AgentScope runtime session

`ModelHandler` will manage a runtime session instead of only a chat client. The session caches long-lived stage/worker `Agent` instances, their `AgentState`, toolkits, and middleware for the lifetime of an active research. Agent instances are keyed by stable role/worker identifiers. Runtime state is serializable into the existing checkpoint and can be rehydrated without changing database schemas.

### Use public AgentScope APIs for the research team

An `AgentScopeResearchTeam` will coordinate a Supervisor Leader and budget-bounded Researcher Workers. It will use `AgentState.tasks_context` and native `Task` records for task lifecycle, while the existing semaphore remains the hard concurrency guard. Private AgentScope App team tools are excluded because their storage, message bus, and service assumptions do not match the existing application boundary.

### Bridge events instead of changing SSE contracts

AgentScope reply, model, text, tool, and task lifecycle events will be normalized into project runtime events. The bridge will publish optional structured metadata through existing workflow event content and tracing attributes. Existing event names and response shapes remain valid, so old frontend behavior continues to work while the Agent Flow can display native runtime nodes when metadata is present.

### Combine native and business observability

Agents receive AgentScope `TracingMiddleware` plus project middleware for context and lifecycle callbacks. Existing workflow/stage spans remain because they carry durable business semantics; AgentScope middleware supplies internal agent/model/tool spans. Duplicate manual model/tool spans will be avoided where native spans are active.

### Preserve performance controls outside model discretion

Budgets, worker count, semaphore limits, Tavily and summary caches, timeouts, input truncation, and report material bounds remain enforced in code. AgentScope context compression supplements these protections but does not replace deterministic input limits.

## Risks / Trade-offs

- [Risk] AgentScope runtime state is not JSON-compatible. → Persist only an explicitly versioned runtime snapshot containing task and summary/context fields; reconstruct agents and toolkits from project configuration.
- [Risk] Long-lived Agent state leaks messages across parallel workers. → Allocate one stable state per stage/worker and never share mutable worker context.
- [Risk] Native tracing duplicates current spans. → Keep workflow/stage spans and suppress project model/tool spans when AgentScope middleware is active.
- [Risk] AgentScope release APIs change. → Pin the tested patch version and isolate all framework types in the infrastructure runtime module.
- [Risk] Runtime events increase SSE volume. → Publish summarized lifecycle events and keep token deltas internal rather than sending every text delta as a workflow event.
- [Risk] Native context compression changes report quality or latency. → Keep existing report/search bounds and add regression assertions around token usage and final report persistence.

## Migration Plan

1. Upgrade and verify AgentScope in the existing Conda environment.
2. Add runtime session, middleware, event bridge, AgentState snapshots, and tests behind the current `agentscope-python` runtime value.
3. Migrate Supervisor tasks and worker execution to `AgentScopeResearchTeam` without changing outer state transitions.
4. Extend frontend event parsing and visualization for optional task/runtime metadata.
5. Run contract, SSE, HITL, cancellation/resume, live Mimo workflow, frontend build, and browser QA.
6. Roll back by reverting the runtime session/team adapter; existing database and Redis structures remain compatible.

