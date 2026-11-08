@domain:scan-engine @area:server-lifecycle @from:server/greenlint-server
Feature: Running the scan server for an editor session
  Serves the VS Code extension: one long-running scan server per session announces when it is ready, refuses a greenlint it cannot work with and keeps answering when a single request fails.

  @id:vscode.scan-engine.server-lifecycle.001 @rule:scan-engine.server.refuses-incompatible-greenlint @verified @source:extensions/vscode/server/greenlint_server.py#main @test:tests/test_vscode_server.py#test_an_old_greenlint_refuses_to_start_and_says_why
  Scenario: A greenlint too old for the extension is refused at startup, with upgrade instructions
    Given the greenlint the server finds is missing part of the editor API (for example iter_files)
    When the extension starts the scan server
    Then the server writes one fatal line with id 0, ok false and fatal true
    And the error names the greenlint version and location, says it is too old and lists what it lacks
    And the error says to upgrade with pip install -U or pipx install --force, or to point greenlint.greenlintPath at a checkout
    And the server exits with status 1 and answers no requests
