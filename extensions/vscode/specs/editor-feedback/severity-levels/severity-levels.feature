@domain:editor-feedback @area:severity-levels @from:src/config
Feature: Showing finding severities in the editor
  Gives developers a consistent editor severity for every greenlint finding, so energy issues show up as hints and warnings rather than build-breaking errors.

  Background:
    Given the greenlint extension is enabled

  @id:vscode.editor-feedback.severity-levels.001 @rule:editor-feedback.severity.greenlint-severity-maps-to-editor-severity @inferred @source:extensions/vscode/src/config.ts#SEVERITY_LEVELS
  Scenario Outline: Each greenlint severity is shown at a fixed editor severity
    Given a file has a finding of greenlint severity "<severity>"
    When the developer opens the file
    Then the finding is shown in the editor and Problems panel as a <editor severity>

    Examples:
      | severity | editor severity |
      | high     | Warning         |
      | medium   | Information     |
      | low      | Hint            |
