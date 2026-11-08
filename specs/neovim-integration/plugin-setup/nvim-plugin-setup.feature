@domain:neovim-integration @area:plugin-setup @from:extensions/nvim
Feature: Configuring the Neovim plugin
  Lets a Neovim user decide how greenlint runs in their editor, and refuses settings it cannot honour instead of silently misbehaving.

  Background:
    Given Given the greenlint plugin is installed in Neovim

  @id:neovim-integration.plugin-setup.001 @rule:nvim.setup.defaults-without-options @verified @source:extensions/nvim/lua/greenlint/config.lua#M.defaults @test:extensions/nvim/tests/config_spec.lua#resolves without options @test:extensions/nvim/tests/config_spec.lua#scans on save by default, not on every keystroke
  Scenario Outline: Without options the plugin runs greenlint on save and groups the report by file
    Given the developer has not configured the plugin
    When the developer runs a greenlint command
    Then the plugin starts with <option> set to <value>

    Examples:
      | option                  | value     |
      | cmd                     | greenlint |
      | run                     | on_save   |
      | grouping                | file      |
      | debounce_ms             | 400       |
      | max_file_bytes          | 1000000   |
      | scan_project_on_startup | true      |
      | diagnostics.enabled     | true      |

  @id:neovim-integration.plugin-setup.002 @rule:nvim.setup.invalid-options-refused @verified @source:extensions/nvim/lua/greenlint/config.lua#M.validate @test:extensions/nvim/tests/config_spec.lua#rejects an empty cmd @test:extensions/nvim/tests/config_spec.lua#rejects a run mode it does not have @test:extensions/nvim/tests/config_spec.lua#rejects a debounce short enough to scan per keystroke @test:extensions/nvim/tests/config_spec.lua#rejects a grouping the report cannot do @test:extensions/nvim/tests/config_spec.lua#rejects a file cap below a kilobyte
  Scenario Outline: A setting the plugin cannot honour is refused at setup
    Given the developer configures the plugin with <option> = <value>
    When the developer sets up the plugin
    Then setup fails with an error naming <option>
    And the error says it expects <expected>

    Examples:
      | option                    | value     | expected                                  |
      | cmd                       | {}        | a non-empty list of strings               |
      | run                       | onType    | one of: on_save, on_type, manual          |
      | debounce_ms               | 5         | a number >= 100                           |
      | max_file_bytes            | 10        | a number >= 1024                          |
      | grouping                  | ecosystem | one of: severity, file, rule              |
      | diagnostics.severity.high | 42        | false, or a vim.diagnostic.severity value |

  @id:neovim-integration.plugin-setup.003 @rule:nvim.setup.disabled-plugin-stays-quiet @verified @source:extensions/nvim/lua/greenlint/init.lua#M.setup @test:extensions/nvim/tests/init_spec.lua#does nothing at all when the plugin is disabled @test:extensions/nvim/tests/init_spec.lua#leaves the autocmds it already attached inert once disabled @questionable
  Scenario: A disabled plugin clears its diagnostics and never scans
    Given the plugin had shown findings in an open file
    When the developer sets up the plugin with enabled = false
    Then every greenlint diagnostic disappears from the editor
    And saving or opening a file starts no scan
    And scan commands start no scan
