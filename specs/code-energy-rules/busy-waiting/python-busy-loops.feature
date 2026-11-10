@domain:code-energy-rules @area:busy-waiting @from:greenlint/pyrules
Feature: Flagging Python busy loops
  Lets developers find `while True:` loops in Python that can never wait or leave, which keep a CPU core at full load for as long as the process runs.

  Background:
    Given a project containing Python source files

  @id:code-energy-rules.busy-waiting.001 @rule:code-energy.busy-waiting.python-endless-loop-without-wait-flagged @verified @source:greenlint/pyrules.py#_ast_busy_loop_findings @test:tests/test_greenlint.py#test_ast_busy_loop_ignores_unrelated_sleep_elsewhere_in_file @test:tests/test_greenlint.py#test_break_in_a_nested_loop_does_not_exonerate @test:tests/test_greenlint.py#test_busy_loop_found_despite_return_in_nested_function
  Scenario Outline: A Python loop that never sleeps and has no way out is reported as a busy loop
    Given a Python file with the loop <loop>
    When the developer scans the project
    Then a GL001 finding "busy loop without sleep" with severity medium is reported
    And the finding points at the line of the `while True:`

    Examples:
      | loop                                                                                                   |
      | `while True:` that only calls `check()`, while another function in the same file calls `time.sleep(1)` |
      | `while True:` whose only `break` sits inside a nested `for` loop                                       |
      | `while True:` whose only `return` sits inside a callback defined in the loop                           |

  @id:code-energy-rules.busy-waiting.002 @rule:code-energy.busy-waiting.python-loop-that-waits-or-exits-not-flagged @verified @source:greenlint/pyrules.py#_ast_busy_loop_findings @test:tests/test_greenlint.py#test_ast_busy_loop_not_flagged_when_loop_actually_sleeps @test:tests/test_greenlint.py#test_paginator_loop_not_flagged @test:tests/test_greenlint.py#test_read_until_eof_loop_not_flagged @test:tests/test_greenlint.py#test_loop_returning_a_value_not_flagged
  Scenario Outline: A Python loop that sleeps or can stop on what it receives is not a busy loop
    Given a Python file with the loop <loop>
    When the developer scans the project
    Then no GL001 finding is reported

    Examples:
      | loop                                                                          |
      | `while True:` that calls `time.sleep(1)` in its body                          |
      | `while True:` draining a paginated API that breaks when there is no next page |
      | `while True:` reading a socket that breaks at end of input                    |
      | `while True:` that returns a value once a condition holds                     |
      | `while True:` that raises an error on an unexpected response                  |

  @id:code-energy-rules.busy-waiting.003 @rule:code-energy.busy-waiting.python-only-literal-true-loops-checked @inferred @source:greenlint/pyrules.py#_ast_busy_loop_findings @questionable
  Scenario Outline: Only loops written as `while True:` are checked for busy waiting
    Given a Python file with `<loop>` whose body only calls `check()`
    When the developer scans the project
    Then <outcome>

    Examples:
      | loop           | outcome                      |
      | while True:    | a GL001 finding is reported  |
      | while 1:       | no GL001 finding is reported |
      | while running: | no GL001 finding is reported |
