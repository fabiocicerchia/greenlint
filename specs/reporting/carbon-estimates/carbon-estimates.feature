@domain:reporting @area:carbon-estimates @from:greenlint/carbon
Feature: Rough carbon cost of each finding
  Gives developers and operators an order-of-magnitude energy/CO2e hint with each finding so they can decide which waste to fix first.

  Background:
    Given greenlint is scanning a project

  @id:reporting.carbon-estimates.001 @rule:reporting.carbon-estimates.every-finding-carries-estimate @verified @source:greenlint/carbon.py#CO2E_HINTS @test:tests/test_greenlint.py#test_findings_carry_a_co2e_estimate @test:tests/test_greenlint.py#test_every_rule_states_its_energy_rationale @test:tests/test_greenlint.py#test_cron_hint_multiplies_out_to_something_sane
  Scenario Outline: Every finding carries the rough CO2e estimate for its rule
    Given the project contains code that triggers rule <rule>
    When the developer scans the project with JSON output
    Then the finding for <rule> has a "co2e_estimate" of "<estimate>"

    Examples:
      | rule  | estimate                                                                            |
      | GL001 | ~150-200 gCO2e/day per instance (one core pegged continuously)                      |
      | GL003 | ~1 gCO2e per 500 core-seconds of runtime; a 2 s job x 1440 runs/day is ~6 gCO2e/day |
      | GL004 | ~15 gCO2e per GB of history; a 200 MB repo is ~3 gCO2e per clone avoided            |
      | GL013 | ~0.5 gCO2e per GB per month left in hot storage                                     |

  @id:reporting.carbon-estimates.002 @rule:reporting.carbon-estimates.hot-path-states-scaling-not-grams @verified @source:greenlint/carbon.py#CO2E_HINTS @test:tests/test_greenlint.py#test_no_hint_quotes_a_fictional_per_call_gram_figure
  Scenario Outline: Per-call costs are described by how they scale, never as grams per call
    Given the project contains code that triggers hot-path rule <rule>
    When the developer scans the project with JSON output
    Then the finding's estimate ends with "negligible per call; ~1 gCO2e per 500 core-seconds of work removed"
    And the estimate does not contain "gCO2e per call" or "gCO2e per iteration"

    Examples:
      | rule  |
      | GL012 |
      | GL020 |
      | GL031 |

  @id:reporting.carbon-estimates.003 @rule:reporting.carbon-estimates.text-report-shows-estimate @inferred @source:greenlint/cli.py#_print_text
  Scenario: The text report shows each finding's rough cost under its suggestion
    Given the project contains a "SELECT * FROM users;" query in q.sql
    When the developer scans the project with text output
    Then the line after the suggestion reads "    ~ ~15 gCO2e per GB of columns never read; negligible per call; ~1 gCO2e per 500 core-seconds of work removed"
