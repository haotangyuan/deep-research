## ADDED Requirements

### Requirement: Readable report references
The completed report SHALL render each numbered reference as a separate visual line even for reports persisted with references in one Markdown paragraph.

#### Scenario: Legacy compact source section
- **WHEN** a report source section contains multiple numbered references on one line
- **THEN** each numbered reference renders on its own line without changing its link target

### Requirement: Markdown report export
The workspace SHALL allow users to download the completed report as a UTF-8 Markdown file named from the sanitized research title.

#### Scenario: Download completed report
- **WHEN** the user activates the Markdown export control on a completed research
- **THEN** the browser downloads a `.md` file containing the full persisted report

### Requirement: Readable Markdown code
The completed report SHALL render fenced code as a scrollable block with readable contrast without inheriting inline-code decoration.

#### Scenario: Fenced and inline code coexist
- **WHEN** a report contains a fenced code block and inline code
- **THEN** the fenced code uses one transparent code surface inside the dark `pre` container while inline code retains its compact light background
