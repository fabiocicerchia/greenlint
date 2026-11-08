@domain:scanning @area:python-structure-analysis @from:greenlint/astindex
Feature: Judging Python loops and scopes by their structure
  Developers scanning Python code get busy-loop and in-loop findings that reflect what a loop can actually do, not just how it looks as text, so legitimate drain-until-done loops are not reported and real spins are not excused.

  Background:
    Given a project containing Python source files

  @id:scanning.python-structure-analysis.001 @rule:scanning.python-structure.loop-with-data-dependent-exit-is-not-busy @verified @source:greenlint/astindex.py#_loop_can_exit @test:tests/test_greenlint.py#test_paginator_loop_not_flagged @test:tests/test_greenlint.py#test_read_until_eof_loop_not_flagged @test:tests/test_greenlint.py#test_loop_returning_a_value_not_flagged
  Scenario Outline: An endless loop that can leave on what it receives is not a busy loop
    Given a Python function containing a `while True:` loop that never sleeps
    And the loop body <exit>
    When the developer scans the project
    Then no "busy loop without sleep" (GL001) finding is reported for that loop

    Examples:
      | exit                                                       |
      | breaks out once a paginated API returns no next-page token |
      | breaks out when a socket read returns nothing              |
      | returns a value once it passes a threshold                 |
      | raises an error on an unexpected response                  |

  @id:scanning.python-structure-analysis.002 @rule:scanning.python-structure.only-the-loops-own-exits-count @verified @source:greenlint/astindex.py#_nearest_loop @test:tests/test_greenlint.py#test_break_in_a_nested_loop_does_not_exonerate @test:tests/test_greenlint.py#test_busy_loop_found_despite_return_in_nested_function
  Scenario Outline: An exit that belongs to an inner loop or a nested function does not excuse a busy loop
    Given a Python function containing a `while True:` loop that never sleeps
    And the only exit inside it is <exit>
    When the developer scans the project
    Then a "busy loop without sleep" (GL001) finding is reported at the `while True:` line

    Examples:
      | exit                                                      |
      | a `break` inside a `for` loop nested in the body          |
      | a `return` inside a callback function defined in the body |

  @id:scanning.python-structure-analysis.003 @rule:scanning.python-structure.names-judged-per-function @verified @source:greenlint/astindex.py#_walk_own_loops @test:tests/test_greenlint.py#test_quadratic_rebuild_name_bindings_are_per_scope
  Scenario: A variable in one function does not change how the same name is judged in another
    Given function `a` sets `total = 0` and adds numbers to it in a loop
    And function `b` sets `total = ''` and appends strings to it in a loop at line 9
    When the developer scans the project
    Then exactly one quadratic rebuild (GL007) finding is reported
    And it is at line 9

  @id:scanning.python-structure-analysis.004 @rule:scanning.python-structure.unparseable-file-gets-no-structural-findings @inferred @source:greenlint/astindex.py#_parse_python @questionable
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
