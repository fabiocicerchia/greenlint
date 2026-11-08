@domain:configuration @area:baselines @from:greenlint/cli
Feature: Accepting existing findings with a baseline
  Lets a team adopt greenlint on an existing codebase by recording current findings as accepted, so the CI gate only fails on new waste.

  Background:
    Given a project tree with one SELECT * query in q.sql

  @id:configuration.baselines.009 @rule:configuration.baselines.write-records-current-findings @verified @source:greenlint/cli.py#main @test:tests/test_greenlint.py#test_cli_writes_and_then_honours_a_baseline @test:tests/test_e2e.py#test_a_written_baseline_silences_the_gate_on_the_next_run
  Scenario: Writing a baseline records every current finding and does not fail the run
    Given no baseline has been written yet
    When the operator scans the tree with --write-baseline --fail-on-findings
    Then the file .greenlint-baseline.json is created in the current directory
    And the output reads "greenlint: 1 finding(s) accepted in .greenlint-baseline.json"
    And no findings are listed
    And the command exits with code 0

  @id:configuration.baselines.010 @rule:configuration.baselines.accepted-findings-hidden @verified @source:greenlint/cli.py#main @test:tests/test_e2e.py#test_a_written_baseline_silences_the_gate_on_the_next_run @test:tests/test_greenlint.py#test_cli_writes_and_then_honours_a_baseline
  Scenario: Findings in the baseline are hidden and no longer fail the gate
    Given a baseline in the current directory records the finding in q.sql
    When the operator scans the tree with --fail-on-findings
    Then the finding in q.sql is not listed
    And the summary reads "greenlint: 0 finding(s) (1 accepted by .greenlint-baseline.json)"
    And the command exits with code 0

  @id:configuration.baselines.011 @rule:configuration.baselines.named-baseline-must-exist @verified @source:greenlint/cli.py#_resolve_baseline @test:tests/test_greenlint.py#test_cli_rejects_a_baseline_path_that_is_not_there
  Scenario: A named baseline that does not exist is refused
    Given there is no file missing.json
    When the operator scans the tree with --baseline missing.json
    Then the command stops with "greenlint: no such baseline: missing.json"
    And no findings are reported
