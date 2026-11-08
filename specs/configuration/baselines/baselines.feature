@domain:configuration @area:baselines @from:greenlint/baselines
Feature: Accepting existing findings with a baseline
  Lets a team adopting greenlint record today's findings as accepted so that scans, and the CI gate, only surface waste introduced afterwards.

  Background:
    Given a project whose scan reports a SELECT * finding in src/q.sql

  @id:configuration.baselines.001 @rule:config.baselines.write-records-current-findings @verified @source:greenlint/baselines.py#write_baseline @test:tests/test_greenlint.py#test_cli_writes_and_then_honours_a_baseline @test:tests/test_e2e.py#test_a_written_baseline_silences_the_gate_on_the_next_run @test:tests/test_greenlint.py#test_baseline_accepts_current_findings_and_still_reports_new_ones
  Scenario: Writing a baseline records every current finding as accepted
    Given no baseline has been recorded yet
    When the operator runs greenlint with --write-baseline
    Then a .greenlint-baseline.json file is written in the working directory
    And the output reads "greenlint: 1 finding(s) accepted in .greenlint-baseline.json"
    And the command exits 0 without printing the findings

  @id:configuration.baselines.002 @rule:config.baselines.accepted-findings-hidden @verified @source:greenlint/baselines.py#apply_baseline @test:tests/test_greenlint.py#test_cli_writes_and_then_honours_a_baseline @test:tests/test_e2e.py#test_a_written_baseline_silences_the_gate_on_the_next_run @test:tests/test_greenlint.py#test_baseline_accepts_current_findings_and_still_reports_new_ones
  Scenario: Findings accepted by the baseline are no longer reported
    Given a baseline that accepts the SELECT * finding in src/q.sql
    When the operator runs greenlint with --fail-on-findings
    Then the SELECT * finding in src/q.sql is not listed
    And the summary reads "greenlint: 0 finding(s) (1 accepted by .greenlint-baseline.json)"
    And the command exits 0

  @id:configuration.baselines.003 @rule:config.baselines.new-findings-still-reported @verified @source:greenlint/baselines.py#apply_baseline @test:tests/test_greenlint.py#test_baseline_accepts_current_findings_and_still_reports_new_ones
  Scenario: Findings the baseline never saw are still reported
    Given a baseline that accepts the SELECT * finding in src/q.sql
    And src/other.sql has since gained a SELECT * query
    When the operator runs greenlint
    Then the SELECT * finding in src/other.sql is listed
    And the SELECT * finding in src/q.sql is not listed

  @id:configuration.baselines.004 @rule:config.baselines.survives-line-moves @verified @source:greenlint/baselines.py#fingerprint @test:tests/test_greenlint.py#test_fingerprint_survives_edits_above_the_finding
  Scenario: An accepted finding stays accepted when lines above it change
    Given a baseline that accepts the SELECT * finding on line 1 of src/q.sql
    And two comment lines have since been added above the query, moving it to line 3
    When the operator runs greenlint
    Then the SELECT * finding in src/q.sql is not listed

  @id:configuration.baselines.005 @rule:config.baselines.one-acceptance-per-file-and-rule @inferred @source:greenlint/baselines.py#fingerprint
  Scenario: Accepting a rule in a file also accepts later occurrences of it in that file
    Given a baseline that accepts the SELECT * finding in src/q.sql
    And a second SELECT * query has since been added to src/q.sql
    When the operator runs greenlint
    Then neither SELECT * finding in src/q.sql is listed
    And the summary reads "greenlint: 0 finding(s) (2 accepted by .greenlint-baseline.json)"

  @id:configuration.baselines.006 @rule:config.baselines.shared-across-path-styles @verified @source:greenlint/baselines.py#fingerprint @test:tests/test_greenlint.py#test_fingerprint_is_the_same_for_absolute_and_relative_paths
  Scenario: The same baseline is honoured whether files are reported by relative or absolute path
    Given a baseline written from the project root that accepts the SELECT * finding in src/q.sql
    When the editor scans /home/dev/proj/src/q.sql by its absolute path, running greenlint from the project root
    Then the SELECT * finding in src/q.sql is not reported

  @id:configuration.baselines.007 @rule:config.baselines.named-baseline-must-exist @verified @source:greenlint/cli.py#_resolve_baseline @test:tests/test_greenlint.py#test_cli_rejects_a_baseline_path_that_is_not_there
  Scenario: A baseline named on the command line that does not exist is refused
    Given no file named missing.json exists
    When the operator runs greenlint with --baseline missing.json
    Then greenlint stops with "greenlint: no such baseline: missing.json"
    And the command exits 1 without reporting findings

  @id:configuration.baselines.008 @rule:config.baselines.unreadable-baseline-reports-everything @verified @source:greenlint/baselines.py#load_baseline @test:tests/test_greenlint.py#test_a_missing_or_broken_baseline_reports_everything @questionable
  Scenario Outline: An unreadable baseline accepts nothing, so every finding is reported
    Given the baseline file <state>
    When the operator runs greenlint
    Then the SELECT * finding in src/q.sql is listed
    And no accepted count is shown in the summary

    Examples:
      | state                                        |
      | is absent                                    |
      | contains text that is not JSON               |
      | is a JSON object without a fingerprints list |
