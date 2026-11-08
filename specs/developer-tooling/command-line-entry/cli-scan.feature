@domain:developer-tooling @area:command-line-entry @from:greenlint/cli
Feature: Running a scan from the command line
  Gives developers and CI operators one greenlint command that scans a tree, reports energy waste in the format their tool reads, and can fail a pipeline on it.

  Background:
    Given a project tree containing source and config files

  @id:developer-tooling.command-line-entry.001 @rule:reporting.ci-gate.fail-on-findings-exit-code @verified @source:greenlint/cli.py#main @test:tests/test_e2e.py#test_fail_on_findings_gates_a_dirty_tree_but_not_a_clean_one @test:tests/test_e2e.py#test_scanning_the_example_reports_what_its_readme_promises
  Scenario Outline: The scan fails the pipeline only when asked to and something is found
    Given the tree has <findings> findings
    When the operator scans the tree <gate>
    Then the command exits with code <exit>

    Examples:
      | findings | gate                       | exit |
      | 2        | with --fail-on-findings    | 1    |
      | 0        | with --fail-on-findings    | 0    |
      | 2        | without --fail-on-findings | 0    |

  @id:developer-tooling.command-line-entry.002 @rule:reporting.text.human-report-with-summary @verified @source:greenlint/cli.py#_print_text @test:tests/test_e2e.py#test_scanning_the_example_reports_what_its_readme_promises @test:tests/test_e2e.py#test_fail_on_findings_gates_a_dirty_tree_but_not_a_clean_one
  Scenario: The human report lists each finding with its advice and ends with a count
    Given the tree has a SELECT * query in q.sql on line 1
    When the operator scans the tree with the default format
    Then the report shows "q.sql:1: [GL005/<severity>] <message>" followed by the rule's suggestion, and a CO2e hint when one exists
    And the last line reads "greenlint: 1 finding(s)"

  @id:developer-tooling.command-line-entry.003 @rule:reporting.json.machine-readable-findings @verified @source:greenlint/cli.py#main @test:tests/test_e2e.py#test_json_output_is_machine_readable
  Scenario: JSON output is a list of findings tooling can parse
    Given the tree has a busy loop and a SELECT * query in sample.py
    When the operator scans the tree with --format json
    Then the output parses as a JSON list of findings
    And each finding names its rule, such as GL001 and GL005, and its file
    And no summary line is printed

  @id:developer-tooling.command-line-entry.004 @rule:reporting.github.workflow-annotations-by-severity @verified @source:greenlint/cli.py#_print_github @test:tests/test_e2e.py#test_json_output_is_machine_readable
  Scenario Outline: GitHub output annotates each finding at a level matching its severity
    Given the tree has a <severity> finding from rule <rule> in <file> on line 1
    When the operator scans the tree with --format github
    Then the output has a line "::<level> file=<file>,line=1,title=greenlint <rule>::<message> — <suggestion>"

    Examples:
      | severity | rule  | file    | level   |
      | high     | GL003 | ci.yml  | error   |
      | medium   | GL005 | q.sql   | warning |
      | low      | GL002 | poll.py | notice  |

  @id:developer-tooling.command-line-entry.005 @rule:configuration.path-exclusion.exclude-flag-adds-to-config @verified @source:greenlint/cli.py#main @test:tests/test_greenlint.py#test_cli_exclude_is_repeatable_and_adds_to_the_config @test:tests/test_greenlint.py#test_cli_exclude_flag_skips_matching_paths
  Scenario: Paths excluded on the command line are skipped on top of the project's ignore list
    Given the project config ignores "*/build/*"
    And the tree has a SELECT * query in each of src/, vendor/, dist/ and build/
    When the operator scans the tree with --exclude "*/vendor/*" --exclude "*/dist/*"
    Then only the finding in src/ is reported
    And the summary reads "greenlint: 1 finding(s)"

  @id:developer-tooling.command-line-entry.006 @rule:reporting.rule-catalogue.list-rules-without-scanning @inferred @source:greenlint/cli.py#_print_rules @questionable
  Scenario: Listing the rules prints the catalogue and scans nothing
    Given greenlint ships its rule catalogue
    When the operator runs greenlint with --list-rules
    Then each rule is printed as "<id> [<severity>] (<languages>): <message>", with the severity padded to six characters and the language tags sorted and comma-separated, for example "GL001 [medium] (.py): busy loop without sleep"
    And no files are scanned
    And the command exits with code 0
