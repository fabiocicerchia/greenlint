@domain:scanning @area:scan-cancellation @from:server/server-ops
Feature: Cancelling a workspace scan
  Lets a developer stop a workspace scan they no longer need, whether it has started or is still waiting, without affecting later scans.

  Background:
    Given the workspace has 200 files with findings

  @id:vscode.scanning.scan-cancellation.001 @rule:scanning.cancellation.cancelled-scan-reports-nothing @verified @source:extensions/vscode/server/server_ops.py#op_cancel @test:tests/test_vscode_server.py#test_cancelling_a_project_scan_stops_the_walk @test:tests/test_vscode_server.py#test_a_scan_cancelled_while_it_is_still_queued_never_walks
  Scenario Outline: A cancelled workspace scan ends with no findings, whether running or still queued
    Given a workspace scan is <state>
    When the developer cancels that scan
    Then the scan ends marked as cancelled
    And the scan reports no findings

    Examples:
      | state                                |
      | running                              |
      | queued behind another workspace scan |

  @id:vscode.scanning.scan-cancellation.002 @rule:scanning.cancellation.late-cancel-has-no-effect @verified @source:extensions/vscode/server/server_ops.py#op_cancel @test:tests/test_vscode_server.py#test_a_cancel_for_a_scan_that_already_finished_is_not_remembered
  Scenario: Cancelling a scan that has already finished does not stop a later scan
    Given a workspace scan has already finished
    When the developer cancels that scan
    Then the cancel reports that nothing is being cancelled
    And a later workspace scan reusing the same scan id completes with its findings
