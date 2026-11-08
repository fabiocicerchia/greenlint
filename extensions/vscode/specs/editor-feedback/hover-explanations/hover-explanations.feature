@domain:editor-feedback @area:hover-explanations @from:src/diagnostics
Feature: Explaining a finding on hover
  Developers hovering a flagged line learn what was found, what to do instead and roughly what it costs, without leaving the editor.

  Background:
    Given the file "src/poller.js" is open in the editor

  @id:vscode.editor-feedback.hover-explanations.001 @rule:editor.hover.finding-card-content @inferred @source:extensions/vscode/src/diagnostics.ts#describe
  Scenario: Hovering a flagged line explains the finding, the fix and its rough cost
    Given greenlint reports finding GL002 "sub-100ms polling interval" with severity high on line 4
    And its suggestion is "Poll every 1s or use an event/push mechanism"
    And its CO2e estimate is "~0.2 kg CO2e/year per instance"
    When the developer hovers over line 4
    Then the hover shows a flame icon and the bold message "sub-100ms polling interval"
    And the hover shows "GL002" linked to its rules reference section, followed by "high severity · greenlint"
    And the hover shows "Do instead: Poll every 1s or use an event/push mechanism"
    And the hover shows "Rough cost: ~0.2 kg CO2e/year per instance"

  @id:vscode.editor-feedback.hover-explanations.002 @rule:editor.hover.cost-omitted-when-unknown @inferred @source:extensions/vscode/src/diagnostics.ts#describe
  Scenario: A finding without a cost estimate shows no cost line
    Given greenlint reports finding GL005 on line 9 with no CO2e estimate
    When the developer hovers over line 9
    Then the hover shows the message, the linked rule id and the "Do instead" suggestion
    And the hover shows no "Rough cost" line

  @id:vscode.editor-feedback.hover-explanations.003 @rule:editor.hover.one-card-per-finding-on-line @inferred @source:extensions/vscode/src/diagnostics.ts#GreenlintHoverProvider
  Scenario Outline: Every finding on the hovered line gets its own card, and unflagged lines show none
    Given greenlint reports findings GL001 and GL002 on line 4
    And greenlint reports no finding on line 5
    When the developer hovers over line <line>
    Then the hover shows <cards> greenlint cards

    Examples:
      | line | cards |
      | 4    | 2     |
      | 5    | 0     |
