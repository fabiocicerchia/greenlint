@domain:status-and-troubleshooting @area:status-bar @from:src/status
Feature: Seeing greenlint's state and finding counts in the status bar
  Gives the developer a one-glance view of whether greenlint has scanned, how many findings sit at each severity, and what the last scan cost, without opening the findings panel.

  Background:
    Given the greenlint extension is active in a workspace

  @id:vscode.status-and-troubleshooting.status-bar.001 @rule:status.status-bar.idle-state-distinguishes-clean-from-unscanned @inferred @source:extensions/vscode/src/status.ts#paintStatus
  Scenario Outline: With no findings the status bar tells a clean scan apart from no scan yet
    Given the workspace has no findings
    And <history>
    When the status bar is refreshed
    Then the status bar reads "<text>"

    Examples:
      | history                   | text                              |
      | no scan has completed yet | $(circle-large-outline) greenlint |
      | a scan has completed      | $(check) greenlint                |

  @id:vscode.status-and-troubleshooting.status-bar.002 @rule:status.status-bar.counts-follow-panel-scope @inferred @source:extensions/vscode/src/status.ts#paintStatus
  Scenario Outline: The status bar shows high, medium and low counts for the findings panel's current scope
    Given the project has findings
    And the findings panel is scoped to <scope>
    And that scope holds <high> high, <medium> medium and <low> low findings
    When the status bar is refreshed
    Then the status bar reads "$(flame) <high> $(warning) <medium> $(info) <low>"

    Examples:
      | scope                   | high | medium | low |
      | the whole project       | 4    | 12     | 30  |
      | the current file app.py | 1    | 2      | 0   |

  @id:vscode.status-and-troubleshooting.status-bar.003 @rule:status.status-bar.clean-file-in-dirty-project-shows-zero-counts @inferred @source:extensions/vscode/src/status.ts#paintStatus @questionable
  Scenario: A clean current file in a project with findings shows zero counts rather than the clean mark
    Given the project has findings in other files
    And the findings panel is scoped to the current file
    And the current file has no findings
    When the status bar is refreshed
    Then the status bar reads "$(flame) 0 $(warning) 0 $(info) 0"
    And the status bar does not show "$(check) greenlint"

  @id:vscode.status-and-troubleshooting.status-bar.004 @rule:status.status-bar.tooltip-shows-scope-and-whole-project-summary @inferred @source:extensions/vscode/src/status.ts#paintStatus
  Scenario Outline: The status bar tooltip describes the current scope and the whole project's last-scan totals
    Given the findings panel is scoped to the current file app.py with 3 findings
    And the last scan found <total> across <files> with <high> high, <medium> medium and <low> low
    When the developer hovers over the status bar
    Then the tooltip starts with "greenlint — app.py — 3 findings (…)"
    And the tooltip reads "Whole project: <total> in <files> — $(flame) <high> · $(warning) <medium> · $(info) <low>"

    Examples:
      | total        | files    | high | medium | low |
      | 412 findings | 57 files | 20   | 150    | 242 |
      | 1 finding    | 1 file   | 1    | 0      | 0   |

  @id:vscode.status-and-troubleshooting.status-bar.005 @rule:status.status-bar.tooltip-shows-last-scan-cost @inferred @source:extensions/vscode/src/status.ts#paintStatus
  Scenario: The status bar tooltip reports how many files the last scan covered, how long it took and how many were reused
    Given the last scan covered 120 files in 850 ms
    And 40 files were scanned and 80 were reused from earlier results
    When the developer hovers over the status bar
    Then the tooltip reads "Last scan: 120 files in 850 ms (40 scanned, 80 cached)"
