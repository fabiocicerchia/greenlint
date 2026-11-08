@domain:neovim-integration @area:editor-commands @from:extensions/nvim
Feature: Reviewing and managing findings from Neovim
  Gives a developer commands to read, explain, navigate and accept the findings in their project without leaving the editor.

  Background:
    Given Given the greenlint plugin is set up in a project

  @id:neovim-integration.editor-commands.001 @rule:nvim.commands.report-grouped @verified @source:extensions/nvim/lua/greenlint/core.lua#M.report_lines @test:extensions/nvim/tests/commands_spec.lua#opens a float that leads with the totals @test:extensions/nvim/tests/commands_spec.lua#scans the project first when nothing is known yet @test:extensions/nvim/tests/commands_spec.lua#regroups the report by what was chosen @test:extensions/nvim/tests/commands_spec.lua#offers the three groupings with a blurb each @test:extensions/nvim/tests/core_spec.lua#groups by file @test:extensions/nvim/tests/core_spec.lua#groups by rule @test:extensions/nvim/tests/core_spec.lua#groups by severity, worst first
  Scenario Outline: The report leads with the totals and groups findings as chosen
    Given the project has 1 high finding in app/a.py and 1 medium finding in app/b.py
    And the developer chose to group by <grouping>
    When the developer opens :GreenlintReport
    Then the report's first line reads "2 finding(s) — 1 high · 1 medium · 0 low"
    And findings are grouped <groups>
    And when nothing had been scanned yet, the project is scanned first

    Examples:
      | grouping | groups                                                            |
      | file     | one group per file, headed "app/a.py  (1)"                        |
      | rule     | one group per rule, headed "GL001 — busy loop without sleep  (n)" |
      | severity | high, then medium, then low                                       |

  @id:neovim-integration.editor-commands.002 @rule:nvim.commands.nothing-found @verified @source:extensions/nvim/lua/greenlint/commands.lua#M.list @test:extensions/nvim/tests/commands_spec.lua#says so when there is nothing to report @test:extensions/nvim/tests/commands_spec.lua#says so, and opens nothing, when there is nothing to list @test:extensions/nvim/tests/commands_spec.lua#says so, without an empty menu, when there is nothing to filter
  Scenario Outline: Commands say nothing wasteful was found instead of showing an empty list
    Given a scan of the project found nothing
    When the developer runs <command>
    Then <outcome>

    Examples:
      | command          | outcome                                                                      |
      | :GreenlintReport | the report reads "Nothing wasteful found."                                   |
      | :GreenlintList   | the developer is told "greenlint: nothing wasteful found." and no list opens |
      | :GreenlintFilter | the developer is told "greenlint: nothing wasteful found." and no menu opens |

  @id:neovim-integration.editor-commands.003 @rule:nvim.commands.list-worst-first @verified @source:extensions/nvim/lua/greenlint/ui.lua#M.to_quickfix @test:extensions/nvim/tests/commands_spec.lua#fills the quickfix list with every finding, worst first @test:extensions/nvim/tests/ui_spec.lua#lists findings worst-first, with the rule and the suggestion on the line
  Scenario: Every finding can be walked worst first in the quickfix list
    Given the project has a low finding GL-LOW in app/z.py and a high finding GL-HIGH in app/a.py
    When the developer runs :GreenlintList
    Then a quickfix list titled "greenlint" opens
    And its first entry is "[GL-HIGH] message — suggestion" marked as a warning
    And the low finding follows, marked as information

  @id:neovim-integration.editor-commands.004 @rule:nvim.commands.filter-by-severity @verified @source:extensions/nvim/lua/greenlint/commands.lua#M.filter @test:extensions/nvim/tests/commands_spec.lua#offers only the severities that were actually found, with their counts @test:extensions/nvim/tests/commands_spec.lua#lists only the chosen severity
  Scenario: Filtering offers only the severities found and lists the one chosen
    Given the project has 1 high finding and 2 low findings
    When the developer runs :GreenlintFilter and picks low
    Then the choices offered are "high    1" and "low     2"
    And a quickfix list titled "greenlint: low" opens with only the low findings

  @id:neovim-integration.editor-commands.005 @rule:nvim.commands.hover-explains-finding @verified @source:extensions/nvim/lua/greenlint/core.lua#M.hover_lines @test:extensions/nvim/tests/core_spec.lua#shows the cost as prose, not as a number @test:extensions/nvim/tests/core_spec.lua#leaves the cost line out when a rule has none @test:extensions/nvim/tests/core_spec.lua#builds the anchor the rules reference actually uses @test:extensions/nvim/tests/commands_spec.lua#says so when the cursor is not on a finding
  Scenario Outline: Hovering a finding explains what to do instead, what it costs and where to read more
    Given line 10 of app/db.py has GL005 "SELECT * query" with suggestion "name the columns you need" and estimate "~15 gCO2e per GB of columns never read"
    When the developer runs :GreenlintHover on line <line>
    Then <outcome>

    Examples:
      | line | outcome                                                                                                                                                                         |
      | 10   | a popup shows the message, "Do instead: name the columns you need", "Rough cost: ~15 gCO2e per GB of columns never read" and a link to the GL005 section of the rules reference |
      | 11   | the developer is told "greenlint: no finding on this line."                                                                                                                     |

  @id:neovim-integration.editor-commands.006 @rule:nvim.commands.baseline-write-needs-confirmation @verified @source:extensions/nvim/lua/greenlint/init.lua#M.write_baseline @test:extensions/nvim/tests/commands_spec.lua#runs nothing at all unless the write is confirmed @test:extensions/nvim/tests/core_spec.lua#drops --format when writing a baseline, which does not produce findings @questionable
  Scenario Outline: Accepting current findings as the baseline happens only after confirmation
    Given the editor knows of 3 findings in the project
    When the developer runs :GreenlintBaselineWrite and answers <answer>
    Then they were asked "Accept the 3 current finding(s) as the baseline?"
    And <outcome>

    Examples:
      | answer         | outcome                                                                                                                 |
      | Cancel         | greenlint is not run and no baseline is written                                                                         |
      | Write baseline | .greenlint-baseline.json is written at the project root, greenlint's confirmation is shown and the project is rescanned |

  @id:neovim-integration.editor-commands.007 @rule:nvim.commands.baseline-clear-needs-confirmation @verified @source:extensions/nvim/lua/greenlint/commands.lua#M.clear_baseline @test:extensions/nvim/tests/commands_spec.lua#says so when there is no baseline to clear
  Scenario Outline: Deleting the baseline happens only after confirmation, and every accepted finding returns
    Given <state>
    When the developer runs :GreenlintBaselineClear and answers <answer>
    Then <outcome>

    Examples:
      | state                                    | answer          | outcome                                                                                                                   |
      | the project has no baseline              | (no prompt)     | the developer is told "greenlint: no baseline to clear."                                                                  |
      | the project has .greenlint-baseline.json | Cancel          | the baseline is kept                                                                                                      |
      | the project has .greenlint-baseline.json | Delete baseline | the developer is told "greenlint: deleted .greenlint-baseline.json" and the project is rescanned with every finding shown |

  @id:neovim-integration.editor-commands.008 @rule:nvim.commands.cancel-stops-scans @verified @source:extensions/nvim/lua/greenlint/init.lua#M.cancel @test:extensions/nvim/tests/triggers_spec.lua#stops a debounced on-type scan that has not started @test:extensions/nvim/tests/triggers_spec.lua#says nothing is running when no scan is waiting @test:extensions/nvim/tests/init_spec.lua#says so when there is nothing to stop
  Scenario Outline: Cancelling stops running and waiting scans
    Given <state>
    When the developer runs :GreenlintCancel
    Then the developer is told "<message>"
    And no scan result from before the cancel is shown

    Examples:
      | state                                          | message                       |
      | an on_type scan is waiting for typing to pause | greenlint: stopped 1 scan(s). |
      | nothing is running or waiting                  | greenlint: nothing running.   |
