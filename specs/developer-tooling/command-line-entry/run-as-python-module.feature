@domain:developer-tooling @area:command-line-entry @from:greenlint/greenlint
Feature: Running greenlint from a checkout
  Lets an operator, a CI job or an editor plugin run greenlint with `python -m greenlint` when the `greenlint` command is not installed, and get the same report and exit status.

  Background:
    Given a project tree that contains the example file examples/basic/sample.py with a busy loop and a SELECT * query

  @id:developer-tooling.command-line-entry.007 @rule:cli.entry.module-invocation-matches-command @verified @source:greenlint/__main__.py#main @test:tests/test_e2e.py#test_scanning_the_example_reports_what_its_readme_promises @test:tests/test_e2e.py#test_json_output_is_machine_readable
  Scenario: Running greenlint as a Python module scans and reports like the greenlint command
    Given greenlint is importable but the greenlint command is not installed
    When the operator runs `python -m greenlint examples/basic`
    Then the report lists findings tagged [GL001/ and [GL005/
    And the last line of the output starts with "greenlint: "
    And the process exits with status 0

  @id:developer-tooling.command-line-entry.008 @rule:cli.entry.module-invocation-propagates-exit-status @verified @source:greenlint/__main__.py#main @test:tests/test_e2e.py#test_fail_on_findings_gates_a_dirty_tree_but_not_a_clean_one @test:tests/test_e2e.py#test_a_written_baseline_silences_the_gate_on_the_next_run
  Scenario Outline: Running greenlint as a Python module exits with the scan's status so a pipeline can gate on it
    Given greenlint is run through `python -m greenlint`
    When the CI job scans <tree> with --fail-on-findings
    Then the process exits with status <status>

    Examples:
      | tree                                        | status |
      | examples/basic (has findings)               | 1      |
      | a directory holding only ok.py with `x = 1` | 0      |
