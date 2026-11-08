@domain:configuration @area:baselines @from:server/server-ops
Feature: Accepting current findings as a baseline
  Lets a developer accept today's findings in a workspace folder so that greenlint reports only new ones, in the editor and in CI.

  Background:
    Given a workspace folder containing files with greenlint findings

  @id:vscode.configuration.baselines.001 @rule:baselines.writing.accepts-every-finding-in-folder @verified @source:extensions/vscode/server/server_ops.py#op_write_baseline @test:tests/test_vscode_server.py#test_write_baseline_quietens_the_findings_it_recorded @test:extensions/vscode/src/test/engine.test.ts#a written baseline silences what it accepted on disk, and only that
  Scenario: Writing a baseline accepts every current finding in the folder
    Given the folder has 1 finding, a busy loop in busy.py
    When the developer writes a baseline for the folder
    Then a file named .greenlint-baseline.json is written at the root of the folder
    And the developer is told that 1 finding was accepted and where the baseline was written

  @id:vscode.configuration.baselines.002 @rule:baselines.writing.records-files-on-disk @inferred @source:extensions/vscode/server/server_ops.py#op_write_baseline
  Scenario: The baseline records the files as saved on disk, not what the editor is showing
    Given busy.py is saved with no findings
    And the developer has an unsaved edit in busy.py that adds a busy loop
    When the developer writes a baseline for the folder
    Then the baseline accepts 0 findings
    And the busy loop in the unsaved edit is still reported

  @id:vscode.configuration.baselines.003 @rule:baselines.writing.ignores-max-file-size-setting @inferred @source:extensions/vscode/server/server_ops.py#op_write_baseline @questionable
  Scenario: A baseline never accepts findings in files over 1 MB, whatever the file size limit is set to
    Given the developer has raised the maximum file size to scan to 5 MB
    And the folder contains a 2 MB file big.sql with a SELECT *
    When the developer writes a baseline for the folder
    Then the SELECT * in big.sql is not accepted
    And the SELECT * in big.sql is still reported by the next workspace scan
