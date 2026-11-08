@domain:scanning @area:result-caching @from:server/scan-cache
Feature: Reusing scan results for unchanged files
  Developers rescanning a workspace get answers without paying again, in time or energy, for files whose contents have not changed, and still see fresh findings for files they edited.

  Background:
    Given Given a workspace containing the file "q.sql" with the text "SELECT * FROM t;"
    And And the workspace has been scanned once, reporting the GL005 finding in "q.sql"

  @id:vscode.scanning.result-caching.001 @rule:scanning.result-caching.untouched-file-not-reread @verified @source:extensions/vscode/server/scan_cache.py#FindingCache @test:tests/test_vscode_server.py#test_second_project_scan_reads_nothing @test:tests/test_vscode_server.py#test_scan_file_reuses_findings_while_the_stat_is_unchanged @test:tests/test_vscode_server.py#test_one_warm_process_answers_over_real_pipes
  Scenario: An untouched file is answered from the previous scan without being read
    Given And "q.sql" has not been modified since that scan
    When When the developer scans the workspace again
    Then Then the GL005 finding in "q.sql" is reported again
    And And the scan reports 0 files read and scanned
    And And every walked file is counted as reused from cache

  @id:vscode.scanning.result-caching.002 @rule:scanning.result-caching.identical-content-not-rescanned @verified @source:extensions/vscode/server/scan_cache.py#FindingCache @test:tests/test_vscode_server.py#test_rewriting_a_file_with_the_same_bytes_costs_a_read_not_a_scan
  Scenario: A file rewritten with identical contents is not rescanned
    Given And "q.sql" has been saved again with exactly the same text, giving it a new modification time
    When When the developer scans "q.sql" again
    Then Then the GL005 finding in "q.sql" is reported again
    And And the file is reported as reused by its content rather than scanned
    And And a further scan of the unchanged file is answered without reading it

  @id:vscode.scanning.result-caching.003 @rule:scanning.result-caching.edited-file-rescanned @verified @source:extensions/vscode/server/scan_cache.py#FindingCache @test:tests/test_vscode_server.py#test_editing_a_file_rescans_it
  Scenario: An edited file is scanned afresh and reports its new findings
    Given And "q.sql" has been changed to "SELECT id FROM t;"
    When When the developer scans "q.sql" again
    Then Then the file is reported as scanned
    And And no findings are reported for "q.sql"
