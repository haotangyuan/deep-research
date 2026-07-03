## Context

The Python backend preserves the existing REST/SSE/MySQL/Redis contracts while AgentScope 2.0.3 supplies persistent agents, isolated state, native tasks, middleware, and tracing. The frontend currently renders every normalized runtime call in the conversational timeline, has fixed-width navigation, and treats the final report as generic Markdown. Observability already initializes one OpenTelemetry SDK provider and exports it to Langfuse; AgentScope `TracingMiddleware` uses that same global provider.

## Goals / Non-Goals

**Goals:**
- Make workspace layout and titles manageable without changing persisted research semantics.
- Separate user-facing workflow progress from diagnostic runtime detail.
- Make AgentScope team lifecycle explicit and keep Agent Flow useful at high event counts.
- Make completed Markdown reports readable and portable.
- Prove that workflow, stage, model/tool, and AgentScope spans share one export pipeline.

**Non-Goals:**
- Replacing the workflow state machine with AgentScope orchestration.
- Adding a server-side document conversion service or PDF dependency.
- Changing research budgets, prompts beyond source formatting, or database schema.
- Exposing raw Langfuse credentials or full model input/output in the UI.

## Decisions

1. **Persist sidebar width in localStorage and keep it component-local.** Desktop width is constrained to 240-440px and changed through an accessible separator; mobile remains an overlay drawer and ignores the stored desktop width. This avoids a global layout store for one preference.
2. **Hide `agent_call` and `team_task` diagnostics from the main timeline.** Existing workflow events remain the readable progress narrative. New `team_lifecycle` events provide one start and one completion row, while Agent Flow retains detailed AgentScope activity.
3. **Publish team lifecycle from `AgentScopeResearchTeam.execute`.** The event is emitted where task count, concurrency, and completion status are authoritative, rather than inferred by the frontend.
4. **Use an authenticated PATCH title endpoint.** The backend trims and validates a 1-200 character title, verifies ownership, updates MySQL, and returns the persisted title. Frontend editing updates the page and history through the existing history event.
5. **Normalize only the final report's source section.** The rendering helper inserts Markdown paragraph boundaries before numbered references under source/reference headings. The report prompt also requires one source per line, improving new reports while keeping old reports readable.
6. **Export Markdown in the browser.** Completed report content is already persisted in the message timeline, so a Blob download avoids a redundant backend endpoint and new dependencies.
7. **Share one OpenTelemetry provider.** The existing provider creates `workflow -> stage -> model/tool` spans and AgentScope `TracingMiddleware` adds native `invoke_agent`, `chat`, and `execute_tool` spans through the same global provider. Verification uses a direct OTLP export result and focused span-shape tests.
8. **Preserve the initial question as the title.** Normalize whitespace and retain up to the existing 200-character title limit; safely backfill local legacy rows only when their 20-character title exactly matches the first user message prefix.
9. **Separate fenced and inline code styling.** Scope the inline-code decoration override to `.markdown-content pre code`, keeping the block transparent, readable, and horizontally scrollable without adding a syntax-highlighting dependency.

## Risks / Trade-offs

- [Old reports use inconsistent source headings] -> Match Chinese and English source/reference headings and test representative formats.
- [Runtime details become less visible in chat] -> Preserve all events in the API and Agent Flow; only the main timeline filters diagnostics.
- [Long titles can still dominate narrow screens] -> Wrap the header title and truncate history labels with a native tooltip.
- [Long code lines exceed narrow report cards] -> Keep overflow inside the code block instead of expanding the page width.
- [Browser-only Markdown export depends on client capabilities] -> Use standard Blob/ObjectURL APIs and verify a real download.
- [Langfuse availability is external] -> Report direct exporter success separately from local span-structure tests.

## Migration Plan

No schema migration is required. Deploy backend and frontend together because the frontend title action depends on the new endpoint and username field. Rollback consists of reverting the endpoint/UI additions; existing research rows and events remain compatible.

## Open Questions

None. PDF export can be added later if styled pagination becomes a product requirement.
