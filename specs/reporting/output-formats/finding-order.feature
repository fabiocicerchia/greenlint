@domain:reporting @area:output-formats @from:greenlint/baselines
Feature: Ordering findings by what is worth fixing first
  Shows developers the most severe waste first, in the same order from the CLI and the editor.

  @id:reporting.output-formats.001 @rule:reporting.ordering.most-severe-first @verified @source:greenlint/baselines.py#finding_sort_key @test:tests/test_greenlint.py#test_finding_sort_key_orders_high_severity_first
  Scenario: Findings are listed high severity first, then by file and line
    Given a CI workflow file with an every-minute cron (high) and a full-history clone (medium)
    When the developer runs greenlint on the project
    Then the every-minute cron finding is listed before the full-history clone finding
    And findings of equal severity are listed by file path, then by line
