@domain:scanning @area:python-structure-analysis @from:greenlint/astindex
Feature: Judging Python loops and scopes by their structure
  Developers scanning Python code get busy-loop and in-loop findings that reflect what a loop can actually do, not just how it looks as text, so legitimate drain-until-done loops are not reported and real spins are not excused.

  Background:
    Given a project containing Python source files

  @id:scanning.python-structure-analysis.004 @rule:scanning.python-structure.unparsable-file-gets-no-structural-findings @inferred @source:greenlint/astindex.py#_parse_python @questionable
  Scenario: A Python file that does not parse gets no structure-based findings
    Given a Python file with a syntax error that also contains a `while True:` loop without a sleep
    When the developer scans the project
    Then no busy loop (GL001), quadratic rebuild (GL007), nested loop (GL018), swap sort (GL023), dict iteration (GL030) or try-in-loop (GL031) finding is reported for that file
    And no warning about the syntax error is shown

  @id:scanning.python-structure-analysis.005 @rule:scanning.python-structure.async-loops-not-analysed @inferred @source:greenlint/astindex.py#index_python @questionable
  Scenario: Async for-loops are not judged by the structure-based loop rules
    Given a Python coroutine that iterates a collection with `async for`
    And inside it, a second `async for` over the same collection
    When the developer scans the project
    Then no nested loop over the same collection (GL018) finding is reported
    And statements inside the `async for` are not treated as being inside a loop
