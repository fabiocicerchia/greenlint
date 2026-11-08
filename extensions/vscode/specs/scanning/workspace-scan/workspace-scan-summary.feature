@domain:scanning @area:workspace-scan @from:server/scan-cache
Feature: Summarising a workspace scan
  Developers scanning a whole workspace get one set of totals for the entire walk, so they can judge how much energy-wasteful code there is without counting findings themselves.

  Background:
    Given a workspace with 20 SQL files that each contain "SELECT * FROM t;" (GL005, medium)
    And a CI workflow "ci.yml" scheduled every minute (GL003, high)

  @id:vscode.scanning.workspace-scan.001 @rule:scanning.workspace-scan.summary-covers-whole-scan @verified @source:extensions/vscode/server/scan_cache.py#RunningSummary @test:tests/test_vscode_server.py#test_the_summary_is_the_whole_scan_not_a_batch
  Scenario: The scan summary totals the whole workspace by severity, rule and file
    When the developer scans the workspace
    Then the summary reports 21 findings in 21 files
    And the summary reports 1 high, 20 medium and 0 low
    And the per-rule counts list GL005 before GL003, busiest rule first and ties in rule order

  @id:vscode.scanning.workspace-scan.002 @rule:scanning.workspace-scan.summary-has-no-co2e-total @inferred @source:extensions/vscode/server/scan_cache.py#RunningSummary
  Scenario: The scan summary never adds up CO2e estimates
    When the developer scans the workspace
    Then the summary contains only finding counts: total, per severity, per rule and files
    And no combined CO2e figure is reported

  @id:vscode.scanning.workspace-scan.003 @rule:scanning.workspace-scan.findings-delivered-once @verified @source:extensions/vscode/server/scan_cache.py#ProjectScan @test:tests/test_vscode_server.py#test_streaming_delivers_findings_in_batches_as_they_are_made @test:tests/test_vscode_server.py#test_a_non_streaming_scan_still_returns_everything
  Scenario Outline: A workspace scan hands over each finding exactly once
    When the developer scans the workspace with streaming <streaming>
    Then the progress updates carry <batched> findings in total
    And the final result carries <final> findings and is marked streamed <streamed>
    And the final summary reports 21 findings

    Examples:
      | streaming | batched | final | streamed |
      | on        | 21      | 0     | true     |
      | off       | 0       | 21    | false    |
