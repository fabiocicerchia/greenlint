@domain:scanning @area:finding-placement @from:greenlint/findings
Feature: Placing findings in files
  Gives the developer reading a greenlint report a complete finding at the right line, without noise from test code where tight waits are deliberate.

  Background:
    Given greenlint is scanning a project

  @id:scanning.finding-placement.001 @rule:scanning.findings.test-code-exempt-from-loop-rules @verified @source:greenlint/findings.py#_is_test_file @test:tests/test_greenlint.py#test_short_sleep_in_a_test_file_is_not_flagged @test:tests/test_greenlint.py#test_short_sleep_in_production_code_is_still_flagged
  Scenario Outline: Test code is not flagged for busy loops, tight sleeps or rebuilt sequences
    Given the file "<path>" contains <wasteful code>
    When the developer scans the project
    Then the report <outcome> a <rule> finding for "<path>"

    Examples:
      | path               | wasteful code                       | rule  | outcome          |
      | proxy_test.go      | a 10 ms sleep                       | GL002 | does not contain |
      | test_poll.py       | a while-True loop with no sleep     | GL001 | does not contain |
      | src/tests/build.py | a list rebuilt with + inside a loop | GL007 | does not contain |
      | web/specs/wait.js  | a 10 ms setInterval                 | GL002 | does not contain |
      | ui/poll.spec.ts    | a 10 ms setInterval                 | GL002 | does not contain |
      | proxy.go           | a 10 ms sleep                       | GL002 | contains         |
      | contest/poll.py    | a while-True loop with no sleep     | GL001 | contains         |
      | latest/proxy.go    | a 10 ms sleep                       | GL002 | contains         |

  @id:scanning.finding-placement.002 @rule:scanning.findings.test-code-keeps-other-rules @inferred @source:greenlint/scanning.py#scan_file
  Scenario: Test code is still checked by every rule other than the loop rules
    Given the file "tests/fixtures.sql" contains "SELECT * FROM users;"
    When the developer scans the project
    Then the report contains a GL005 finding for "tests/fixtures.sql" at line 1

  @id:scanning.finding-placement.003 @rule:scanning.findings.complete-finding-fields @verified @source:greenlint/findings.py#_finding @test:tests/test_greenlint.py#test_findings_carry_a_co2e_estimate
  Scenario: Every finding names its rule, severity, file, line, explanation, suggestion and carbon hint
    Given the file "q.sql" contains "SELECT * FROM users;"
    When the developer scans the project with JSON output
    Then the finding has rule "GL005", the rule's severity, file "q.sql" and line 1
    And the finding carries the rule's message and energy-saving suggestion
    And the finding carries a non-empty CO2e estimate

  @id:scanning.finding-placement.004 @rule:scanning.findings.line-of-match @verified @source:greenlint/findings.py#_LineIndex @test:tests/test_greenlint.py#test_line_numbers_survive_a_match_at_the_start_of_a_line @test:tests/test_greenlint.py#test_line_numbers_are_right_when_a_rule_fires_many_times
  Scenario: A finding is reported at the line where the wasteful code starts
    Given the file "q.sql" has a comment on line 1 and "SELECT *" queries starting on lines 2 and 4
    When the developer scans the project
    Then the report contains GL005 findings for "q.sql" at lines 2 and 4
