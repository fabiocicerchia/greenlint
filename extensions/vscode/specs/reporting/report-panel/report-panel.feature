@domain:reporting @area:report-panel @from:src/reportpanel
Feature: Viewing the greenlint report in an editor panel
  Lets a developer keep a greenlint report open beside their code that stays current with findings without slowing down editing or workspace scans.

  Background:
    Given a workspace with greenlint findings

  @id:vscode.reporting.report-panel.001 @rule:reporting.report-panel.single-panel-beside-editor @inferred @source:extensions/vscode/src/reportPanel.ts#ReportPanel
  Scenario: Opening the report shows one report beside the editor without taking focus
    Given the report may or may not already be open
    When the developer runs "greenlint: Open Report"
    Then a panel titled "greenlint report" with the leaf icon is shown beside the active editor
    And the keyboard focus stays in the editor the developer was using
    And the panel shows the current findings
    And only one report panel exists, even when the command is run again
