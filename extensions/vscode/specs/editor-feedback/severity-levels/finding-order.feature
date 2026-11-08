@domain:editor-feedback @area:severity-levels @from:src/types
Feature: Ordering findings by severity
  Developers see the most severe energy problems first, in the same order the greenlint CLI prints them, wherever the extension lists findings.

  Background:
    Given the greenlint scan engine is connected

  @id:vscode.editor-feedback.severity-levels.002 @rule:editor-feedback.ordering.severity-then-file-then-line @verified @source:extensions/vscode/src/types.ts#compareFindings @test:extensions/vscode/src/test/types.test.ts#orders by severity, then file, then line
  Scenario Outline: Findings are listed by severity, then file, then line
    Given the engine ranks severities high, medium, low
    And the project has findings <findings>
    When the developer views the project's findings
    Then the findings are listed in the order <order>

    Examples:
      | findings                                                                | order                                                                   |
      | low a.py:1, high z.py:99, medium b.py:20, medium b.py:2, medium a.py:50 | high z.py:99, medium a.py:50, medium b.py:2, medium b.py:20, low a.py:1 |
      | medium b.py:3, medium B.py:9                                            | medium B.py:9, medium b.py:3                                            |

  @id:vscode.editor-feedback.severity-levels.003 @rule:editor-feedback.ordering.engine-published-severity-order @verified @source:extensions/vscode/src/types.ts#useSeverityOrder @test:extensions/vscode/src/test/types.test.ts#sorts by the order the scan server published
  Scenario: The severity order is the one the scan engine publishes
    Given the engine ranks severities critical, high, medium, low
    When the developer views findings of severities low, critical, medium and high
    Then the findings are listed critical, high, medium, low

  @id:vscode.editor-feedback.severity-levels.004 @rule:editor-feedback.ordering.unranked-severity-last @verified @source:extensions/vscode/src/types.ts#compareFindings @test:extensions/vscode/src/test/types.test.ts#sorts a severity the server did not mention last, not at random
  Scenario: A severity the engine did not rank is listed last
    Given the engine ranks severities high, medium, low
    When the developer views findings of severities nonsense, low and high
    Then the findings are listed high, low, nonsense

  @id:vscode.editor-feedback.severity-levels.005 @rule:editor-feedback.ordering.default-severity-order @verified @source:extensions/vscode/src/types.ts#useSeverityOrder @test:extensions/vscode/src/test/types.test.ts#keeps the fallback when the server publishes no order
  Scenario: Without a published order, findings are ranked high, medium, low
    Given the engine has published no severity order
    When the developer views findings of severities low, high and medium
    Then the findings are listed high, medium, low
