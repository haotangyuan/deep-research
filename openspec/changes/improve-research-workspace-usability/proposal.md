## Why

The research workspace exposes low-level runtime events without enough user context and lacks basic document-management ergonomics such as resizing, renaming, readable references, and export. These gaps make the AgentScope integration difficult to understand and the completed research difficult to reuse.

## What Changes

- Add a persisted, resizable desktop sidebar while preserving the mobile drawer behavior.
- Replace repetitive AgentScope call rows in the main timeline with concise team lifecycle and task progress summaries; retain detailed model/tool data in Agent Flow.
- Expose explicit AgentScope research-team start and completion events.
- Add authenticated research-title editing with length validation and immediate history/header synchronization; preserve up to 200 characters from the initial research question instead of truncating at 20.
- Render report references one item per line, isolate fenced-code styling from inline code, and allow completed reports to be downloaded as Markdown.
- Return and display the authenticated username in the account menu.
- Verify the shared OpenTelemetry pipeline from workflow spans through AgentScope native tracing to Langfuse, and document the current AgentScope role and five resume-ready project bullets.
- Add regression coverage for APIs, runtime events, report formatting/export, responsive layout, downloads, and observability export.

## Capabilities

### New Capabilities
- `research-workspace-usability`: Sidebar resizing, readable runtime timeline, title editing, username display, and responsive interaction behavior.
- `research-report-portability`: Readable source formatting and local Markdown report export.
- `agentscope-observability-verification`: Verifiable workflow/stage/AgentScope model-tool trace composition and maintainable README resume description.

### Modified Capabilities

None.

## Impact

- Backend research and user DTOs, research API/service methods, and AgentScope team event publication.
- Frontend API contracts, workspace/sidebar/header controls, timeline rendering, report rendering, account menu, and download behavior.
- Unit, API smoke, browser, and observability tests.
- Root README and observability/architecture documentation.
