@domain:scan-engine @area:request-protocol @from:src/protocol
Feature: Talking to the scan server
  Serves extension users whose scans run in a long-lived greenlint server: a slow scan keeps going, a stuck or dead server fails with a reason they can read, and findings arrive while a project scan is still walking.

  Background:
    Given the scan server is running for the open workspace

  @id:vscode.scan-engine.request-protocol.001 @rule:scan-engine.request-protocol.timeout-measures-silence @inferred @source:extensions/vscode/src/protocol.ts#LineProtocol
  Scenario Outline: A request times out only after two minutes with no word from the scan server
    Given the user has asked for a <operation>
    And the scan server <behaviour>
    When two minutes pass with the request still unanswered
    Then the request <outcome>

    Examples:
      | operation       | behaviour                                        | outcome                                                        |
      | project scan    | reports progress at least once every two minutes | is still running and has not failed                            |
      | project scan    | has said nothing since the request was sent      | fails with "scanProject timed out after 120s with no progress" |
      | saved-file scan | has said nothing since the request was sent      | fails with "scanFile timed out after 120s with no progress"    |

  @id:vscode.scan-engine.request-protocol.002 @rule:scan-engine.request-protocol.findings-stream-during-project-scan @verified @source:extensions/vscode/src/protocol.ts#LineProtocol @test:extensions/vscode/src/test/engine.test.ts#a project scan streams its findings and ends with the totals
  Scenario: A project scan delivers findings in batches while it is still running
    Given the workspace holds busy.py with a busy loop and nightly.yml with an every-minute cron
    When the user scans the whole project
    Then findings for GL001 and GL003 arrive before the scan finishes
    And each update carries the number of files walked so far and the number of findings so far
    And the finished scan reports a total of 2 findings

  @id:vscode.scan-engine.request-protocol.003 @rule:scan-engine.request-protocol.server-error-reported-verbatim @inferred @source:extensions/vscode/src/protocol.ts#ScanServerError
  Scenario: An error the scan server reports reaches the user in its own words, without an install offer
    Given the scan server cannot complete the request and answers with the error "cannot read /proj/src/locked.py"
    When the user scans the current file
    Then the scan fails
    And the user sees "greenlint: cannot read /proj/src/locked.py" with only a Show Log action
    And the user is not offered to install greenlint

  @id:vscode.scan-engine.request-protocol.004 @rule:scan-engine.request-protocol.start-refusal-reason-surfaces @inferred @source:extensions/vscode/src/protocol.ts#LineProtocol
  Scenario: A scan server that refuses to start says why
    Given the scan server is starting
    And it reports that it cannot start because "greenlint 0.1.0 is too old"
    When the extension waits for the scan server to come up
    Then starting with that interpreter fails with "greenlint 0.1.0 is too old"
    And the failure reason is not a generic "scan server exited" message

  @id:vscode.scan-engine.request-protocol.005 @rule:scan-engine.request-protocol.outstanding-requests-fail-when-server-goes @inferred @source:extensions/vscode/src/protocol.ts#LineProtocol
  Scenario Outline: When the scan server exits or is stopped, every scan still waiting fails with the reason
    Given a project scan and a file scan are both waiting on the scan server
    When the scan server <event>
    Then both scans fail with "<message>"
    And neither scan stays waiting

    Examples:
      | event                       | message                                  |
      | exits with code 1           | scan server exited (code 1, signal null) |
      | is stopped by the extension | scan server stopped                      |

  @id:vscode.scan-engine.request-protocol.006 @rule:scan-engine.request-protocol.garbled-output-logged-and-ignored @inferred @source:extensions/vscode/src/protocol.ts#LineProtocol
  Scenario: Output from the scan server that is not a valid message is logged and does not break scanning
    Given the scan server prints the line "DeprecationWarning: something" to its output
    When the extension reads that line
    Then the output log shows "[greenlint] unparsable line from the scan server: DeprecationWarning: something"
    And scans in progress go on and are answered
