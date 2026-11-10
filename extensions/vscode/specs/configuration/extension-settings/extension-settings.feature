@domain:configuration @area:extension-settings @from:src/config
Feature: Configuring the greenlint extension
  Lets a developer tune how and when greenlint scans from the editor's settings, and only restarts the scan engine when a setting can't take effect any other way.

  Background:
    Given the greenlint extension is installed in the editor

  @id:vscode.configuration.extension-settings.001 @rule:configuration.settings.unset-settings-use-documented-defaults @inferred @source:extensions/vscode/src/config.ts#readSettings
  Scenario Outline: Settings the developer has not set take their documented defaults
    Given the developer has not set "<setting>"
    When the extension reads its settings
    Then "<setting>" is <default>

    Examples:
      | setting                         | default             |
      | greenlint.enable                | on                  |
      | greenlint.run                   | onType              |
      | greenlint.debounceMs            | 400                 |
      | greenlint.pythonPath            | empty (auto-detect) |
      | greenlint.greenlintPath         | empty (auto-detect) |
      | greenlint.scanProjectOnStartup  | on                  |
      | greenlint.maxFileBytes          | 1000000             |
      | greenlint.respectEditorExcludes | on                  |
      | greenlint.exclude               | no extra globs      |
      | greenlint.trace                 | off                 |

  @id:vscode.configuration.extension-settings.002 @rule:configuration.settings.engine-paths-restart-scan-server @inferred @source:extensions/vscode/src/config.ts#requiresRestart
  Scenario Outline: Changing the Python interpreter or greenlint location restarts the scan engine; other settings do not
    Given the scan engine is running
    And "<setting>" is "<before>"
    When the developer changes "<setting>" to "<after>"
    Then the scan engine is <outcome>

    Examples:
      | setting                 | before           | after                   | outcome       |
      | greenlint.pythonPath    |                  | /usr/bin/python3.12     | restarted     |
      | greenlint.greenlintPath |                  | /home/dev/src/greenlint | restarted     |
      | greenlint.pythonPath    | /usr/bin/python3 |   /usr/bin/python3      | not restarted |
      | greenlint.debounceMs    | 400              | 800                     | not restarted |
      | greenlint.exclude       | []               | ["*/vendor/*"]          | not restarted |
