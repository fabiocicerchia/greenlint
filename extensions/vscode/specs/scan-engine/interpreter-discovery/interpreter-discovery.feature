@domain:scan-engine @area:interpreter-discovery @from:src/interpreters
Feature: Finding the Python and greenlint to scan with
  Serves VS Code users who installed greenlint (often with pipx) or are editing its rules, so the extension finds the greenlint they mean without setup and never quietly uses one they did not ask for.

  Background:
    Given the output log lists, in order, every interpreter and greenlint the extension will try before it starts the scan server

  @id:vscode.scan-engine.interpreter-discovery.001 @rule:engine.discovery.configured-greenlint-path-is-exclusive @inferred @source:extensions/vscode/src/interpreters.ts#candidates
  Scenario Outline: A configured greenlint path is the only greenlint tried
    Given greenlint.greenlintPath is set to "/home/dev/src/greenlint"
    And greenlint.pythonPath is <python_path>
    And the workspace also holds a greenlint checkout and greenlint is installed as a package
    When the extension looks for greenlint
    Then the output log lists only: <tried>
    And neither the workspace checkout nor the installed package is tried

    Examples:
      | python_path              | tried                                                               |
      | /opt/py311/bin/python    | /opt/py311/bin/python + /home/dev/src/greenlint                     |
      | empty, on Linux or macOS | python3 + /home/dev/src/greenlint, python + /home/dev/src/greenlint |

  @id:vscode.scan-engine.interpreter-discovery.002 @rule:engine.discovery.workspace-checkout-before-installed-release @inferred @source:extensions/vscode/src/interpreters.ts#workspaceGreenlintModules
  Scenario Outline: A greenlint checkout in the workspace is tried before the installed release
    Given no greenlint path or Python interpreter is configured
    And a workspace root "/home/dev/greenlint" contains <layout>
    And greenlint is also installed as a package
    When the extension looks for greenlint
    Then the first candidates in the output log are "python3 + /home/dev/greenlint" and then "python + /home/dev/greenlint"
    And only after those does the log list interpreters with "installed package"

    Examples:
      | layout                                      |
      | a greenlint package folder with __init__.py |
      | a single greenlint.py file                  |

  @id:vscode.scan-engine.interpreter-discovery.003 @rule:engine.discovery.default-interpreters-per-platform @inferred @source:extensions/vscode/src/interpreters.ts#candidates @questionable
  Scenario Outline: Without a configured interpreter the platform's usual Python commands are tried in order
    Given no greenlint path or Python interpreter is configured
    And no greenlint checkout is in the workspace and no greenlint command is on PATH
    And the editor runs on <platform>
    When the extension looks for greenlint
    Then the output log lists: <tried>

    Examples:
      | platform       | tried                                                   |
      | Linux or macOS | python3 + installed package, python + installed package |
      | Windows        | python + installed package, py + installed package      |

  @id:vscode.scan-engine.interpreter-discovery.004 @rule:engine.discovery.finds-pipx-and-console-script-installs @inferred @source:extensions/vscode/src/interpreters.ts#interpretersOwningGreenlint
  Scenario Outline: A greenlint installed in its own virtualenv is found without configuration
    Given no greenlint path or Python interpreter is configured
    And greenlint is not importable from the python3 on PATH
    And <install>
    When the extension looks for greenlint
    Then the output log lists "<interpreter> + installed package" after python3 and python

    Examples:
      | install                                                                        | interpreter                                      |
      | the greenlint command on PATH starts with "#!/home/dev/.venvs/gl/bin/python3"  | /home/dev/.venvs/gl/bin/python3                  |
      | pipx installed greenlint into its standard venv under the home folder on Linux | /home/dev/.local/pipx/venvs/greenlint/bin/python |

  @id:vscode.scan-engine.interpreter-discovery.005 @rule:engine.discovery.shell-shims-are-not-interpreters @inferred @source:extensions/vscode/src/interpreters.ts#interpretersOwningGreenlint
  Scenario: A greenlint command whose first line names a shell does not add an interpreter
    Given no greenlint path or Python interpreter is configured
    And the greenlint command on PATH is a pyenv shim starting with "#!/usr/bin/env bash"
    And greenlint has no pipx venv
    When the extension looks for greenlint
    Then the output log lists only python3 and python with the installed package
    And no bash or env entry appears among the candidates

  @id:vscode.scan-engine.interpreter-discovery.006 @rule:engine.discovery.configured-interpreter-is-exclusive @inferred @source:extensions/vscode/src/interpreters.ts#candidates
  Scenario: A configured Python interpreter is the only interpreter tried
    Given greenlint.pythonPath is set to "/opt/py311/bin/python" and greenlint.greenlintPath is empty
    And the workspace root "/home/dev/greenlint" contains a greenlint checkout
    And the greenlint command on PATH belongs to a pipx venv
    When the extension looks for greenlint
    Then the output log lists: "/opt/py311/bin/python + /home/dev/greenlint, /opt/py311/bin/python + installed package"
    And the pipx interpreter is not tried
