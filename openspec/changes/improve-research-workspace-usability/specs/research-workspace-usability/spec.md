## ADDED Requirements

### Requirement: Resizable research sidebar
The workspace SHALL allow desktop users to resize the left sidebar between bounded minimum and maximum widths and SHALL persist the selected width locally.

#### Scenario: Resize desktop sidebar
- **WHEN** a desktop user drags the sidebar separator
- **THEN** the sidebar width changes within 240-440px without overlapping the research content

#### Scenario: Mobile workspace
- **WHEN** the viewport is below the desktop breakpoint
- **THEN** the sidebar remains an overlay drawer and the stored desktop width does not reduce the main content width

### Requirement: Understandable AgentScope progress
The main timeline SHALL present concise workflow and AgentScope team lifecycle progress without listing every native agent call, while Agent Flow SHALL retain diagnostic runtime details.

#### Scenario: Research team starts
- **WHEN** the supervisor starts AgentScope research tasks
- **THEN** the user sees one team-start event describing task count and concurrency

#### Scenario: Repeated runtime calls
- **WHEN** multiple SearchAgent model calls complete
- **THEN** the main timeline does not render one row per call and Agent Flow still contains the runtime metadata

### Requirement: Editable and readable research titles
Authenticated owners SHALL be able to rename a research using a trimmed 1-200 character title, and long titles SHALL remain readable in the page header.

#### Scenario: Rename research
- **WHEN** the owner submits a valid title
- **THEN** MySQL, the current header, and the history entry display the new title

#### Scenario: Invalid title
- **WHEN** the owner submits an empty or over-200-character title
- **THEN** the API rejects the update and preserves the previous title

#### Scenario: Initial research title
- **WHEN** a user starts research with a question longer than 20 characters
- **THEN** the normalized question is preserved as the title up to the 200-character limit and the page header wraps without clipping it

### Requirement: Authenticated username display
The user API SHALL return the authenticated username and the account menu SHALL display it.

#### Scenario: Signed-in account menu
- **WHEN** an authenticated user opens the workspace
- **THEN** the lower-left account control shows that user's username instead of a generic label
