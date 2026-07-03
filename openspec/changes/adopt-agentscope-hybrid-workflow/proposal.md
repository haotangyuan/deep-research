## Why

The current backend uses AgentScope mainly as a per-call ReAct/model adapter while task planning, runtime state, event translation, tracing, and multi-agent execution remain custom. Moving these runtime responsibilities into AgentScope makes the framework choice technically meaningful while retaining the deterministic business state machine required for API, persistence, HITL, recovery, and performance compatibility.

## What Changes

- Upgrade and lock the Python AgentScope dependency to the current compatible 2.0 release.
- Introduce long-lived per-research AgentScope runtime sessions backed by `AgentState` and native context compression.
- Use AgentScope task state to represent Supervisor research tasks and worker progress.
- Execute research branches as a budget-constrained AgentScope research team while retaining deterministic concurrency limits and result ordering.
- Add AgentScope middleware and event bridging for tracing, token usage, tool/model lifecycle, and frontend workflow visualization.
- Preserve all existing REST, SSE, MySQL, Redis, HITL, cancellation, resume, fallback, and frontend contracts.
- Extend backend, frontend, integration, and browser tests to cover the hybrid workflow.

## Capabilities

### New Capabilities

- `agentscope-hybrid-workflow`: AgentScope-native runtime state, tasks, team execution, middleware, and events inside the existing durable research workflow.
- `agentscope-event-bridge`: Stable translation of AgentScope runtime activity into existing workflow events, SSE payloads, traces, and frontend Agent Flow data.

### Modified Capabilities

None.

## Impact

- Backend runtime, agents, state, pipeline, observability, event publishing, dependencies, and tests.
- Frontend workflow event interpretation and Agent Flow visualization when new runtime metadata is present.
- Conda environment and Python documentation.
- No breaking API, schema, Redis-key, or user-visible workflow changes are permitted.
