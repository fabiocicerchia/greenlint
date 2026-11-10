@domain:neovim-integration @area:health-and-logging @from:extensions/nvim
Feature: Troubleshooting the Neovim plugin
  Tells a developer whether greenlint can run in their editor and what the plugin has been doing, so setup problems can be fixed without guesswork.

  Background:
    Given the greenlint plugin is installed in Neovim

  @id:neovim-integration.health-and-logging.001 @rule:nvim.health.command-runs @verified @source:extensions/nvim/lua/greenlint/health.lua#check_command @test:extensions/nvim/tests/health_spec.lua#errors, with the install advice, when the command is not executable @test:extensions/nvim/tests/health_spec.lua#errors with the exit code when the command runs and fails @test:extensions/nvim/tests/health_spec.lua#warns when the command runs but is not greenlint @test:extensions/nvim/tests/health_spec.lua#counts the rules the command reports, first line included
  Scenario Outline: The health check reports whether the configured command is a working greenlint
    Given the plugin's command is <cmd>
    When the developer runs :checkhealth greenlint
    Then the report shows <level> "<message>"

    Examples:
      | cmd                               | level                                        | message                                       |
      | a program that is not installed   | an error, with pip install and setup advice, | `greenlint-missing` is not executable         |
      | a program that exits 3            | an error                                     | `<cmd> --list-rules` exited 3                 |
      | a program that prints hello       | a warning                                    | `<cmd>` ran, but does not look like greenlint |
      | greenlint listing GL001 and GL002 | OK                                           | `<cmd>` runs — 2 rules                        |

  @id:neovim-integration.health-and-logging.002 @rule:nvim.health.project-context @verified @source:extensions/nvim/lua/greenlint/health.lua#M.check @test:extensions/nvim/tests/health_spec.lua#reports the project root it will scan @test:extensions/nvim/tests/health_spec.lua#explains the temp-file cost of on_type only when on_type is set
  Scenario: The health check reports the editor, project root and project files that shape a scan
    Given the project root holds .greenlint.toml but no baseline
    And the run mode is on_type
    When the developer runs :checkhealth greenlint
    Then it reports whether Neovim is 0.11 or newer
    And it reports "project root: <root>"
    And it reports that .greenlint.toml was found and its opt-outs apply
    And it reports "baseline: none"
    And it notes that on_type scans write the buffer to a temp file

  @id:neovim-integration.health-and-logging.003 @rule:nvim.log.recent-activity @verified @source:extensions/nvim/lua/greenlint/log.lua#M.add @test:extensions/nvim/tests/commands_spec.lua#opens a float of the log, one timestamped line per event @test:extensions/nvim/tests/commands_spec.lua#shows the run it logged once something has been scanned
  Scenario: The log shows the plugin's recent activity, timestamped and bounded
    Given the plugin has run scans this session
    When the developer runs :GreenlintLog
    Then a window lists one "[HH:MM:SS]" line per event, including each greenlint command line the plugin ran
    And only the latest 500 lines are kept
