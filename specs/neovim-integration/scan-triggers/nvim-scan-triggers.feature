@domain:neovim-integration @area:scan-triggers @from:extensions/nvim
Feature: Scanning files as you edit
  Keeps a developer's findings current without asking, by scanning on the editor events their chosen run mode allows.

  Background:
    Given the greenlint plugin is set up in a project

  @id:neovim-integration.scan-triggers.001 @rule:nvim.triggers.run-mode-decides-automatic-scans @verified @source:extensions/nvim/lua/greenlint/triggers.lua#on_open @test:extensions/nvim/tests/triggers_spec.lua#scans a file nothing is known about @test:extensions/nvim/tests/triggers_spec.lua#leaves an unknown file alone when scanning is manual
  Scenario Outline: The run mode decides whether saving or opening a file scans it
    Given the run mode is <run>
    And greenlint has not reported anything for app/worker.py yet
    When the developer <event> app/worker.py
    Then app/worker.py <outcome>

    Examples:
      | run     | event | outcome                               |
      | on_save | saves | is scanned and its findings are shown |
      | on_type | saves | is scanned and its findings are shown |
      | manual  | saves | is not scanned                        |
      | on_save | opens | is scanned and its findings are shown |
      | manual  | opens | is not scanned                        |

  @id:neovim-integration.scan-triggers.002 @rule:nvim.triggers.unsaved-text-scanned @inferred @source:extensions/nvim/lua/greenlint/init.lua#M.scan_buffer
  Scenario Outline: Unsaved edits are scanned as they stand, and findings point at the real file
    Given app/worker.py has unsaved edits
    When <trigger>
    Then the unsaved text is scanned with the rules for app/worker.py
    And the findings are shown on app/worker.py
    And a result for text that has since been edited again is discarded

    Examples:
      | trigger                                                     |
      | the developer pauses typing for debounce_ms in on_type mode |
      | the developer runs :GreenlintScan                           |

  @id:neovim-integration.scan-triggers.003 @rule:nvim.triggers.reopen-shows-known-findings @verified @source:extensions/nvim/lua/greenlint/triggers.lua#on_open @test:extensions/nvim/tests/triggers_spec.lua#repaints what is already known rather than scanning again
  Scenario: Reopening a file shows its known findings without scanning it again
    Given greenlint already reported a busy loop in app/worker.py
    And the run mode is on_save
    When the developer opens app/worker.py
    Then the busy loop is shown on app/worker.py
    And greenlint is not run for app/worker.py

  @id:neovim-integration.scan-triggers.004 @rule:nvim.triggers.oversized-file-skipped @verified @source:extensions/nvim/lua/greenlint/init.lua#M.scan_file @test:extensions/nvim/tests/init_spec.lua#skips a file over the byte cap without running greenlint @questionable
  Scenario: A file larger than the size cap is not scanned on save or open
    Given max_file_bytes is 1024
    And vendor/bundle.js on disk is 4096 bytes
    When the developer saves vendor/bundle.js
    Then greenlint is not run for vendor/bundle.js
    And no error is shown

  @id:neovim-integration.scan-triggers.005 @rule:nvim.triggers.project-scan-is-whole-truth @verified @source:extensions/nvim/lua/greenlint/init.lua#M.scan_project @test:extensions/nvim/tests/init_spec.lua#groups findings by file and drops what the walk no longer reports @test:extensions/nvim/tests/init_spec.lua#reports failure without disturbing what is already known @questionable
  Scenario: A whole-project scan replaces every finding in the project
    Given app/old.py and app/new.py both showed findings
    And the developer has since fixed app/old.py
    When the developer runs :GreenlintScanAll
    Then app/old.py shows no findings
    And app/new.py shows its findings

  @id:neovim-integration.scan-triggers.006 @rule:nvim.triggers.project-settings-respected @verified @source:extensions/nvim/lua/greenlint/core.lua#M.scan_argv @test:extensions/nvim/tests/core_spec.lua#passes the project config and baseline when they exist @test:extensions/nvim/tests/core_spec.lua#repeats --exclude rather than joining, since a glob may contain a comma
  Scenario: Editor scans honour the project's config, baseline and editor-only excludes
    Given the nearest folder holding .greenlint.toml, .git or .hg is the project root
    And the project root holds .greenlint.toml and .greenlint-baseline.json
    And the plugin's exclude option lists */dist/*
    When the developer saves a file
    Then rules opted out in .greenlint.toml are not reported
    And findings accepted in the baseline are not reported
    And files matching */dist/* are not scanned

  @id:neovim-integration.scan-triggers.007 @rule:nvim.triggers.failed-scan-explained @verified @source:extensions/nvim/lua/greenlint/init.lua#decode @test:extensions/nvim/tests/init_spec.lua#rejects valid JSON that is not a list of findings
  Scenario Outline: A scan the developer asked for says why it failed
    Given greenlint is configured as <cmd>
    When the developer runs :GreenlintScan
    Then the developer is told "<message>"

    Examples:
      | cmd                                                  | message                                                           |
      | a tool that prints [{"hello": 1}]                    | greenlint: unexpected output — is `cmd` pointing at greenlint?    |
      | a tool that prints nothing and writes boom to stderr | greenlint: boom                                                   |
      | greenlint, not installed, on the first scan this session | greenlint: could not run `greenlint` — see :checkhealth greenlint |
