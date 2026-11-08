@domain:neovim-integration @area:in-editor-diagnostics @from:extensions/nvim
Feature: Seeing findings in the editor
  Shows a developer the energy waste in the file they are editing, right on the offending line, with what to do instead.

  Background:
    Given the greenlint plugin is set up in a project

  @id:neovim-integration.in-editor-diagnostics.001 @rule:nvim.diagnostics.finding-on-its-line @verified @source:extensions/nvim/lua/greenlint/ui.lua#to_diagnostic @test:extensions/nvim/tests/ui_spec.lua#traces the code, not the indentation @test:extensions/nvim/tests/ui_spec.lua#carries the rule as the code and the suggestion in the message @test:extensions/nvim/tests/ui_spec.lua#publishes in severity order, worst first
  Scenario: A finding appears on its line with the rule and the suggestion
    Given greenlint reports GL001 "busy loop without sleep" with suggestion "poll with a backoff" on line 1 of app/worker.py
    And line 1 reads "    while True:"
    When the findings for app/worker.py arrive
    Then a diagnostic from greenlint with code GL001 underlines "while True:" without the indentation
    And its message reads "busy loop without sleep — poll with a backoff"

  @id:neovim-integration.in-editor-diagnostics.002 @rule:nvim.diagnostics.severity-mapping @verified @source:extensions/nvim/lua/greenlint/ui.lua#build_diagnostics @test:extensions/nvim/tests/ui_spec.lua#drops a severity the user mapped to false @test:extensions/nvim/tests/config_spec.lua#lets a severity be silenced
  Scenario Outline: greenlint severities show at the configured editor level, or not at all
    Given greenlint severity <severity> is mapped to <mapping>
    When a <severity> finding arrives for an open file
    Then it is <shown>

    Examples:
      | severity | mapping     | shown                |
      | high     | the default | shown as a warning   |
      | medium   | the default | shown as information |
      | low      | the default | shown as a hint      |
      | medium   | false       | not shown            |

  @id:neovim-integration.in-editor-diagnostics.003 @rule:nvim.diagnostics.past-end-dropped @verified @source:extensions/nvim/lua/greenlint/ui.lua#build_diagnostics @test:extensions/nvim/tests/ui_spec.lua#drops a finding past the end of the buffer rather than clamping it
  Scenario: A finding beyond the end of the edited text is not shown
    Given greenlint reports a finding on line 99 of app/worker.py
    And the open buffer has 1 line
    When the findings for app/worker.py arrive
    Then no diagnostic is shown for that finding

  @id:neovim-integration.in-editor-diagnostics.004 @rule:nvim.diagnostics.can-be-turned-off @verified @source:extensions/nvim/lua/greenlint/ui.lua#M.render @test:extensions/nvim/tests/ui_spec.lua#publishes nothing at all when diagnostics are turned off
  Scenario: With diagnostics turned off no findings are drawn in files
    Given diagnostics.enabled is false
    When findings for an open file arrive
    Then no greenlint diagnostic is shown in that file

  @id:neovim-integration.in-editor-diagnostics.005 @rule:nvim.diagnostics.statusline-counts @verified @source:extensions/nvim/lua/greenlint/init.lua#M.statusline @test:extensions/nvim/tests/init_spec.lua#is empty before setup and when nothing was found @test:extensions/nvim/tests/init_spec.lua#shows high/medium/low once there is something to show
  Scenario Outline: The statusline shows high, medium and low counts only when something was found
    Given the project has <high> high, <medium> medium and <low> low findings
    When the statusline is drawn
    Then the greenlint component reads "<text>"

    Examples:
      | high | medium | low | text    |
      | 1    | 1      | 1   | 󱄅 1/1/1 |
      | 0    | 0      | 0   |         |
