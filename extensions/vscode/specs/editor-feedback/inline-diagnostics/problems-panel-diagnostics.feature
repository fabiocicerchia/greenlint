@domain:editor-feedback @area:inline-diagnostics @from:src/diagnostics
Feature: Showing greenlint findings as editor problems
  Developers see each energy-wasteful pattern underlined on its line and listed in the Problems panel, with its severity and a one-click link to why it matters.

  Background:
    Given greenlint has reported findings for a file in the workspace

  @id:vscode.editor-feedback.inline-diagnostics.001 @rule:editor.diagnostics.underline-traces-code-not-indentation @inferred @source:extensions/vscode/src/diagnostics.ts#rangeFor
  Scenario: A finding in an open file is underlined from the first code character to the end of its line
    Given the file "src/worker.py" is open in the editor
    And line 12 reads "    while True: pass" with four spaces of indentation
    And greenlint reports finding GL001 on line 12
    When the developer looks at the file
    Then line 12 is underlined from column 5 to the end of the line
    And the leading indentation is not underlined

  @id:vscode.editor-feedback.inline-diagnostics.002 @rule:editor.diagnostics.closed-file-whole-line @inferred @source:extensions/vscode/src/diagnostics.ts#rangeFor
  Scenario: A finding in a file that is not open covers its whole line
    Given the file "ci/build.yml" is not open in the editor
    And greenlint reports finding GL004 on line 8 of it
    When the developer views the Problems panel
    Then the Problems panel lists GL004 at line 8 of "ci/build.yml"
    And the problem spans the whole of line 8

  @id:vscode.editor-feedback.inline-diagnostics.003 @rule:editor.severity.greenlint-to-editor-severity @inferred @source:extensions/vscode/src/config.ts#SEVERITY_LEVELS
  Scenario Outline: Each greenlint severity is shown at a fixed editor severity
    Given greenlint reports a finding with severity <greenlint_severity>
    When the developer views the finding in the editor
    Then the problem is shown with editor severity <editor_severity>

    Examples:
      | greenlint_severity | editor_severity |
      | high               | Warning         |
      | medium             | Information     |
      | low                | Hint            |

  @id:vscode.editor-feedback.inline-diagnostics.004 @rule:editor.rule-docs.problem-links-to-rule-reference @inferred @source:extensions/vscode/src/diagnostics.ts#toDiagnostics
  Scenario Outline: Each problem is labelled greenlint and its rule id links to that rule's reference section
    Given greenlint reports finding <rule> with message "<message>"
    When the developer views the finding in the Problems panel
    Then the problem's source is "greenlint"
    And the problem's message is "<message>"
    And the problem's code is "<rule>" and links to "<docs_url>"

    Examples:
      | rule  | message                    | docs_url                                                                                              |
      | GL005 | SELECT * query             | https://github.com/fabiocicerchia/greenlint/blob/main/docs/rules.md#gl005--select--query              |
      | GL002 | sub-100ms polling interval | https://github.com/fabiocicerchia/greenlint/blob/main/docs/rules.md#gl002--sub-100ms-polling-interval |
