@domain:scan-engine @area:install-and-compatibility @from:server/greenlint-api
Feature: Loading a compatible greenlint engine
  Serves extension users and rule contributors: the scan server runs the greenlint they meant to use, and if that greenlint is too old it refuses to start and explains how to upgrade, rather than failing partway through a scan.

  Background:
    Given the VS Code extension starts the scan server with a candidate Python interpreter

  @id:vscode.scan-engine.install-and-compatibility.001 @rule:engine.loading.configured-checkout-preferred @inferred @source:extensions/vscode/server/greenlint_api.py#load_greenlint
  Scenario Outline: A configured greenlint checkout is used instead of the installed release
    Given greenlint is installed on the interpreter
    And the extension points the scan server at a greenlint checkout given as <configured path>
    When the scan server starts
    Then the rules from the checkout in <loaded directory> are the ones that run
    And the installed greenlint release is not used

    Examples:
      | configured path                                                         | loaded directory |
      | /work/greenlint (the directory holding the package)                     | /work/greenlint  |
      | /work/greenlint/greenlint.py (an existing single-file module)           | /work/greenlint  |
      | /work/greenlint/greenlint.py (stale default, the file no longer exists) | /work/greenlint  |

  @id:vscode.scan-engine.install-and-compatibility.002 @rule:engine.compatibility.refuse-outdated-greenlint @verified @source:extensions/vscode/server/greenlint_api.py#missing_api @test:tests/test_vscode_server.py#test_missing_api_names_what_an_older_greenlint_lacks @test:tests/test_vscode_server.py#test_an_old_greenlint_refuses_to_start_and_says_why
  Scenario Outline: A greenlint too old for the extension is refused at startup and the user is told how to upgrade
    Given the greenlint found is missing <capability>
    When the scan server starts
    Then the scan server stops with a fatal error before taking any scan request
    And the error says the greenlint version and location are too old for this extension
    And the error names <named as> as missing
    And the error suggests `pip install -U git+https://github.com/fabiocicerchia/greenlint`, `pipx install --force`, or pointing `greenlint.greenlintPath` at a checkout

    Examples:
      | capability                                                      | named as         |
      | the project file walker                                         | iter_files       |
      | baseline support                                                | write_baseline   |
      | scanning unsaved editor text (scan_file without a text keyword) | scan_file(text=) |

  @id:vscode.scan-engine.install-and-compatibility.003 @rule:engine.compatibility.reported-version @inferred @source:extensions/vscode/server/greenlint_api.py#greenlint_version @questionable
  Scenario Outline: The engine reports its greenlint version, or "unknown" when it cannot tell
    Given the loaded greenlint <declares>
    And the interpreter <installed>
    When the extension asks the scan server for its identity
    Then the reported greenlint version is <reported version>

    Examples:
      | declares                  | installed                     | reported version |
      | a version of 0.4.0 itself | has greenlint 0.3.0 installed | 0.4.0            |
      | no version of its own     | has greenlint 0.3.0 installed | 0.3.0            |
      | no version of its own     | has no greenlint installed    | unknown          |
