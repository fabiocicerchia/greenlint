# Specifications of greenlint / extensions/vscode

What this code does, one atomic Gherkin scenario per behaviour, read from the code by code-atlas.
Tags: `@verified` a test asserts it · `@inferred` read from the code only · `@gap` an entry point no test covers · `@human` written or amended by a person, never rewritten.

## Configuration and baselines

Letting users tune what greenlint flags and accept the findings they already have.

- **Baselines**: [Accepting current findings as a baseline](configuration/baselines/writing-a-baseline.feature) (3)
- **Extension settings**: [Configuring the greenlint extension](configuration/extension-settings/extension-settings.feature) (2)

## In-editor feedback

Showing each finding where the code is, with an explanation of the waste and how to fix it.

- **Hover explanations**: [Explaining a finding on hover](editor-feedback/hover-explanations/hover-explanations.feature) (3)
- **Inline diagnostics**: [Showing greenlint findings as editor problems](editor-feedback/inline-diagnostics/problems-panel-diagnostics.feature) (4)
- **Rule documentation links**: [Linking findings to their rule documentation](editor-feedback/rule-documentation/rule-documentation-links.feature) (1)
- **Severity levels**: [Ordering findings by severity](editor-feedback/severity-levels/finding-order.feature) (4)

## Findings explorer

A sidebar view for browsing every finding in the current file or the whole project.

- **Grouping**: [Arranging the Findings panel](findings-explorer/grouping/findings-panel-layout.feature) (1)

## Reporting

Producing a readable report of the workspace's findings.

- **Report content**: [Reading a greenlint report](reporting/report-content/report-content.feature) (7)
- **Report panel**: [Viewing the greenlint report in an editor panel](reporting/report-panel/report-panel.feature) (1)

## Scan engine connection

Finding, starting and talking to the greenlint installation that does the actual analysis.

- **Installation and compatibility**: [Loading a compatible greenlint engine](scan-engine/install-and-compatibility/greenlint-engine-compatibility.feature) (3), [Installing greenlint from the failure notification](scan-engine/install-and-compatibility/install-greenlint-from-notification.feature) (2)
- **Interpreter discovery**: [Finding the Python and greenlint to scan with](scan-engine/interpreter-discovery/interpreter-discovery.feature) (6)
- **Memory footprint**: [Keeping large result sets light without changing what findings say](scan-engine/memory-footprint/shared-finding-text.feature) (2)
- **Request protocol**: [Talking to the scan server](scan-engine/request-protocol/scan-request-protocol.feature) (6)

## Scanning

Finding energy-wasteful patterns in the code the user is editing, file by file or across the whole workspace.

- **Exclusions**: [Skipping what the editor already excludes](scanning/exclusions/editor-excludes-excludes.feature) (5), [Honouring the editor's excludes](scanning/exclusions/editor-excludes.feature) (2)
- **Result caching**: [Reusing scan results for unchanged files](scanning/result-caching/reusing-unchanged-results.feature) (3)
- **Scan cancellation**: [Cancelling a workspace scan](scanning/scan-cancellation/cancelling-a-scan.feature) (2)
- **Workspace scan**: [Keeping the project's findings current](scanning/workspace-scan/keeping-findings-current.feature) (1), [Summarising a workspace scan](scanning/workspace-scan/workspace-scan-summary.feature) (3)

## Status and troubleshooting

Keeping the user informed about what greenlint is doing and why something went wrong.

- **Error notifications**: [Telling the user about scan failures without flooding them](status-and-troubleshooting/error-notifications/scan-failure-notifications.feature) (3)
- **Status bar**: [Seeing greenlint's state and finding counts in the status bar](status-and-troubleshooting/status-bar/status-bar-summary.feature) (5)
