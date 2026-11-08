@domain:editor-feedback @area:hover-explanations @from:src/diagnostics
Feature: Explaining a finding on hover
  Developers hovering a flagged line learn what was found, what to do instead and roughly what it costs, without leaving the editor.

  Background:
    Given the file "src/poller.js" is open in the editor

  @id:vscode.editor-feedback.hover-explanations.001 @rule:editor.hover.finding-card-content @inferred @source:extensions/vscode/src/diagnostics.ts#describe
  Scenario: Hovering a flagged line explains the finding, the fix and its rough cost
    Given greenlint reports finding GL002 "sub-100ms polling interval" with severity low on line 4
    And its suggestion is "tight polling burns CPU; prefer push/webhooks or longer intervals"
    And its CO2e estimate is "~10-40 gCO2e/day per instance (wake-ups blocking CPU idle states)"
    When the developer hovers over line 4
    Then the hover shows an info icon and the bold message "sub-100ms polling interval"
    And the hover shows "GL002" linked to its rules reference section, followed by "low severity · greenlint"
    And the hover shows "Do instead: tight polling burns CPU; prefer push/webhooks or longer intervals"
    And the hover shows "Rough cost: ~10-40 gCO2e/day per instance (wake-ups blocking CPU idle states)"

  @id:vscode.editor-feedback.hover-explanations.002 @rule:editor.hover.cost-omitted-when-unknown @inferred @source:extensions/vscode/src/diagnostics.ts#describe
  Scenario: A finding without a cost estimate shows no cost line
    Given greenlint reports a finding on line 9 whose rule has no CO2e estimate
    When the developer hovers over line 9
    Then the hover shows the message, the linked rule id and the "Do instead" suggestion
    And the hover shows no "Rough cost" line

  @id:vscode.editor-feedback.hover-explanations.003 @rule:editor.hover.one-card-per-finding-on-line @inferred @source:extensions/vscode/src/diagnostics.ts#GreenlintHoverProvider
  Scenario Outline: Every finding on the hovered line gets its own card, and unflagged lines show none
    Given greenlint reports two findings on line 4
    And greenlint reports no finding on line 5
    When the developer hovers over line <line>
    Then the hover shows <cards> greenlint cards

    Examples:
      | line | cards |
      | 4    | 2     |
      | 5    | 0     |
