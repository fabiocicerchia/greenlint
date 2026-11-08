@domain:developer-tooling @area:examples @from:examples/basic
Feature: Showing what greenlint flags with the basic example
  A new user runs greenlint on the shipped basic example and sees for themselves what kinds of energy waste it reports, as the example's README says they will.

  Background:
    Given the basic example contains a loop that runs forever without sleeping and a query that selects every column

  @id:developer-tooling.examples.001 @rule:examples.basic.reports-promised-findings @verified @source:examples/basic/sample.py#poll_forever @test:tests/test_e2e.py#test_scanning_the_example_reports_what_its_readme_promises @test:tests/test_e2e.py#test_json_output_is_machine_readable
  Scenario: Scanning the basic example reports the busy loop and the SELECT * query
    Given no project config or baseline applies to the scan
    When the user scans the basic example with greenlint
    Then the report includes a GL001 busy-loop finding
    And the report includes a GL005 SELECT * finding
    And every finding points at sample.py
    And the last line of the report is a greenlint summary
    And the command exits with status 0
