@domain:status-and-troubleshooting @area:error-notifications @from:src/notify
Feature: Telling the user about scan failures without flooding them
  Developers using the greenlint VS Code extension need to learn that scanning failed, once, without a toast for every re-scan that fails the same way, while the full detail stays in the log.

  Background:
    Given the greenlint extension is active in VS Code

  @id:vscode.status-and-troubleshooting.error-notifications.001 @rule:troubleshooting.errors.repeat-failure-shown-once @inferred @source:extensions/vscode/src/notify.ts#ErrorNotifier
  Scenario Outline: A failure that repeats is shown once but logged every time
    Given a scan has failed and the user was shown "greenlint: <headline>"
    When the next scan fails with the same error
    Then no new error notification appears
    And the greenlint output log gains another line "[greenlint] <headline>"

    Examples:
      | headline                        |
      | scan server exited unexpectedly |

  @id:vscode.status-and-troubleshooting.error-notifications.002 @rule:troubleshooting.errors.alternating-failures-reshown @inferred @source:extensions/vscode/src/notify.ts#ErrorNotifier @questionable
  Scenario: A failure is shown again once a different failure came between
    Given the user was shown the failure "greenlint: server timed out"
    And the user was then shown the failure "greenlint: invalid response"
    When a scan fails again with "server timed out"
    Then an error notification "greenlint: server timed out" appears again

  @id:vscode.status-and-troubleshooting.error-notifications.003 @rule:troubleshooting.errors.toast-shows-headline-with-log-link @inferred @source:extensions/vscode/src/notify.ts#ErrorNotifier
  Scenario: A failure notification shows only its first line and offers the log
    Given a scan fails, for a reason other than greenlint not being installed, with a multi-line error whose first line is "scan failed"
    When the user is notified of the failure
    Then the notification reads "greenlint: scan failed" without the remaining lines
    And the notification offers "Show Log"
    And choosing "Show Log" opens the greenlint output log holding the full error
