@domain:reporting @area:report-content @from:src/report
Feature: Reading a greenlint report
  Gives developers and reviewers one readable page summarising every energy-wasteful finding in the chosen scope, with why it matters and what to do instead.

  Background:
    Given a greenlint report is generated for a scope such as "whole project"

  @id:vscode.reporting.report-content.001 @rule:reporting.content.finding-shows-location-rule-advice-and-cost @verified @source:extensions/vscode/src/report.ts#fileSection @test:extensions/vscode/src/test/report.test.ts#reports each finding with its rule, suggestion and cost
  Scenario: Each finding is listed under its file with its location, rule, advice and CO2e estimate
    Given the project has a finding of rule GL005 at line 44 of src/db.py with message "SELECT * query", suggestion "fetch only needed columns" and CO2e estimate "~15 gCO2e per GB"
    When the developer opens the report
    Then a section headed "src/db.py" shows a count of 1
    And the finding reads "src/db.py:44" with rule "GL005" and message "SELECT * query"
    And below it the suggestion "↳ fetch only needed columns" is shown
    And below that the estimate "~ ~15 gCO2e per GB" is shown, and no estimate line appears for findings without one

  @id:vscode.reporting.report-content.002 @rule:reporting.content.headline-scope-and-finding-count @verified @source:extensions/vscode/src/report.ts#renderReport @test:extensions/vscode/src/test/report.test.ts#counts one finding without the plural @test:extensions/vscode/src/test/report.test.ts#says so when there is nothing to report
  Scenario Outline: The report headline names the scope and how many findings it holds
    Given the report covers <scope> with <count> findings
    When the developer opens the report
    Then the headline reads "<headline>"

    Examples:
      | scope         | count | headline                    |
      | whole project | 0     | whole project — 0 findings  |
      | src/db.py     | 1     | src/db.py — 1 finding       |
      | whole project | 12    | whole project — 12 findings |

  @id:vscode.reporting.report-content.003 @rule:reporting.content.empty-report-says-nothing-found @verified @source:extensions/vscode/src/report.ts#renderReport @test:extensions/vscode/src/test/report.test.ts#says so when there is nothing to report
  Scenario: A report with no findings says nothing was found
    Given the scope has no findings
    When the developer opens the report
    Then the report shows "Nothing found"
    And no by-rule summary and no file sections are shown

  @id:vscode.reporting.report-content.004 @rule:reporting.content.rule-summary-ordered-by-count @inferred @source:extensions/vscode/src/report.ts#ruleSummary
  Scenario: The by-rule summary lists the most frequent rules first
    Given the scope has 3 findings of rule GL002 and 3 of GL001 and 1 of GL005
    When the developer opens the report
    Then a "By rule" table lists GL001 (3), then GL002 (3), then GL005 (1)
    And each row shows the rule's message and its finding count

  @id:vscode.reporting.report-content.005 @rule:reporting.content.scan-metadata-line @inferred @source:extensions/vscode/src/report.ts#scanCost
  Scenario Outline: The report states when it was generated, by which greenlint version, and what the scan cost
    Given the report was generated with greenlint version <version>
    And the scan covered 120 files in 340 ms: 20 scanned, 90 reused by modification time, 5 reused by content, 5 skipped
    When the developer opens the report
    Then the meta line shows the generation time in the developer's locale
    And the meta line shows "<version_text>"
    And the meta line shows "120 files in 340 ms (20 scanned, 95 reused from cache, 5 skipped)"

    Examples:
      | version   | version_text         |
      | 0.9.0     | · greenlint 0.9.0    |
      | (unknown) | no greenlint version |

  @id:vscode.reporting.report-content.006 @rule:reporting.content.finding-text-cannot-inject-markup @verified @source:extensions/vscode/src/report.ts#escapeHtml @test:extensions/vscode/src/test/report.test.ts#escapes findings into the page rather than through it
  Scenario: File names and finding text are shown as text and can never inject markup into the report
    Given a file on disk is named "<img src=x onerror=alert(1)>.py"
    And a finding in it has the message "a & b"
    When the developer opens the report
    Then the file name is displayed literally as "<img src=x onerror=alert(1)>.py"
    And the message is displayed literally as "a & b"
    And no image or other element is created from the file name

  @id:vscode.reporting.report-content.007 @rule:reporting.content.report-runs-no-script @verified @source:extensions/vscode/src/report.ts#renderReport @test:extensions/vscode/src/test/report.test.ts#ships no script, so the webview needs no script-src
  Scenario: The report cannot run any script
    Given the scope has findings
    When the developer opens the report
    Then the report contains no script
    And the report's content policy forbids everything except inline styles
