@domain:scan-engine @area:install-and-compatibility @from:src/notify
Feature: Installing greenlint from the failure notification
  Developers who have the extension but not the greenlint scanner get the one install command, and can run or copy it from the notification, so they are unblocked without reading docs.

  Background:
    Given the greenlint extension is active in VS Code
    And the scan server could not be started with any Python interpreter

  @id:vscode.scan-engine.install-and-compatibility.004 @rule:engine.install.notification-offers-install-command @verified @source:extensions/vscode/src/notify.ts#ErrorNotifier @test:extensions/vscode/src/test/engine.test.ts#a workspace greenlint checkout is tried before the installed package
  Scenario Outline: When greenlint cannot be started the notification carries the install command
    Given the interpreters tried did not all fail for the same reason
    When the user is notified that the scan server could not start
    Then the notification reads "greenlint: <headline>" followed by "Install it with: pipx install git+https://github.com/fabiocicerchia/greenlint"
    And the notification offers "Install greenlint", "Copy Command" and "Show Log"

    Examples:
      | headline                                                                                                                   |
      | could not start the scan server — install or upgrade greenlint, or set `greenlint.pythonPath` / `greenlint.greenlintPath`. |

  @id:vscode.scan-engine.install-and-compatibility.005 @rule:engine.install.copy-command @inferred @source:extensions/vscode/src/notify.ts#ErrorNotifier
  Scenario: The install command can be copied from the notification
    Given the user was shown the notification with the install command
    When the user chooses "Copy Command"
    Then the clipboard holds "pipx install git+https://github.com/fabiocicerchia/greenlint"
    And a message reads "Copied: pipx install git+https://github.com/fabiocicerchia/greenlint"
