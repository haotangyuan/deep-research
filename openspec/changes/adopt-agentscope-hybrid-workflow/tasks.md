## 1. Runtime Foundation

- [x] 1.1 Upgrade and lock AgentScope, synchronize the Conda environment, and verify public APIs used by the hybrid runtime
- [x] 1.2 Add per-research runtime sessions with long-lived stage/worker agents, isolated `AgentState`, and context compression
- [x] 1.3 Add versioned AgentScope runtime snapshot serialization, checkpoint integration, restoration, and cleanup

## 2. Native Runtime Integration

- [x] 2.1 Implement AgentScope middleware for research context, budget enforcement, lifecycle callbacks, and native tracing
- [x] 2.2 Implement an AgentScope event bridge that normalizes model/tool/reply/task activity without changing SSE contracts
- [x] 2.3 Replace custom Supervisor task lifecycle tracking with AgentScope `TaskContext` records
- [x] 2.4 Implement the budget-constrained `AgentScopeResearchTeam` Leader/Worker execution path with deterministic result ordering and failure isolation

## 3. Frontend Integration

- [x] 3.1 Extend workflow event DTO handling for optional AgentScope runtime metadata
- [x] 3.2 Render AgentScope task and worker state in the existing Agent Flow without regressing legacy events

## 4. Compatibility and Documentation

- [x] 4.1 Update backend and root documentation for the hybrid workflow, AgentScope boundary, configuration, and rollback behavior
- [x] 4.2 Add focused unit and contract tests for runtime sessions, state isolation, task transitions, event normalization, budgets, and snapshots

## 5. End-to-End Verification

- [x] 5.1 Run Python compilation, unit/contract tests, API/SSE smoke tests, and frontend production build
- [x] 5.2 Verify register/login, model management, HITL approve/revise, cancellation, resume, Agent Flow, and observability behavior
- [x] 5.3 Run the full database-backed Mimo research workflow and verify completion, persisted report, token usage, performance controls, and runtime cleanup
- [x] 5.4 Perform desktop and mobile browser QA with screenshots, DOM checks, console checks, and a primary interaction path
