## 1. Backend Contracts

- [x] 1.1 Add username to the authenticated user response with contract coverage
- [x] 1.2 Add an ownership-checked research-title update endpoint with validation and API smoke coverage
- [x] 1.3 Publish AgentScope research-team start/completion lifecycle events and cover their metadata

## 2. Workspace Experience

- [x] 2.1 Implement bounded, persisted desktop sidebar resizing without changing the mobile drawer
- [x] 2.2 Filter low-level AgentScope call/task rows from the main timeline and render concise team lifecycle progress
- [x] 2.3 Add title editing, long-title wrapping/tooltips, and synchronized header/history updates
- [x] 2.4 Display the authenticated username in the lower-left account control
- [x] 2.5 Preserve initial research titles up to 200 characters and backfill unambiguously truncated local titles

## 3. Report Experience

- [x] 3.1 Normalize numbered report references into one visual item per line and strengthen new-report prompt formatting
- [x] 3.2 Add completed-report Markdown download with a sanitized filename
- [x] 3.3 Isolate fenced-code styles from inline-code decoration and keep long code locally scrollable

## 4. Observability and Documentation

- [x] 4.1 Verify the shared OpenTelemetry provider, AgentScope native tracing middleware, and Langfuse OTLP export
- [x] 4.2 Document AgentScope's current role, differences from the prior integration, and five canonical resume bullets in README
- [x] 4.3 Update architecture and observability documentation for runtime-event presentation and trace ownership

## 5. Verification

- [x] 5.1 Run Python compilation, unit/contract tests, API/SSE smoke tests, and frontend production build
- [x] 5.2 Run desktop/mobile browser QA for resizing, title editing, lifecycle visibility, username display, reference layout, and Markdown download
- [x] 5.3 Audit adjacent workspace flows and fix any reproducible regressions found during QA
- [x] 5.4 Verify long initial titles and fenced/inline code on desktop and mobile viewports
