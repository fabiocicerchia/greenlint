@domain:code-energy-rules @area:python-idioms @from:greenlint/pyrules
Feature: Flagging wasteful Python idioms in loops
  Lets developers find Python loops that pay for work they throw away, half-used dict items and exceptions raised on ordinary input, while leaving legitimate error handling alone.

  Background:
    Given a project containing Python source files

  @id:code-energy-rules.python-idioms.001 @rule:code-energy.python-idioms.half-used-dict-items-flagged @verified @source:greenlint/pyrules.py#_ast_dict_iterator_findings @test:tests/test_greenlint.py#test_detects_dict_items_discarding_key_or_value @test:tests/test_greenlint.py#test_dict_items_using_both_key_and_value_not_flagged
  Scenario Outline: Iterating dict items while discarding the key or the value is reported
    Given a Python file with the loop `for <target> in d.items():`
    When the developer scans the project
    Then <outcome>

    Examples:
      | target | outcome                                                                         |
      | _, v   | a GL030 finding "dict .items() iteration discards the key or value" is reported |
      | k, _   | a GL030 finding "dict .items() iteration discards the key or value" is reported |
      | k, v   | no GL030 finding is reported                                                    |

  @id:code-energy-rules.python-idioms.002 @rule:code-energy.python-idioms.exception-as-loop-control-flow-flagged @verified @source:greenlint/pyrules.py#_ast_try_in_loop_findings @test:tests/test_greenlint.py#test_detects_lookup_guarded_by_except_in_loop @test:tests/test_greenlint.py#test_detects_int_conversion_used_as_a_type_test
  Scenario Outline: A lookup or number conversion guarded by a swallowed exception inside a loop is reported
    Given a Python loop whose `try` holds only <guarded>
    And its handler only does `continue` or `pass`
    When the developer scans the project
    Then a GL031 finding "exception swallowed every iteration (exceptions as control flow)" is reported at the `try` line

    Examples:
      | guarded      |
      | `v = d[k]`   |
      | `n = int(s)` |

  @id:code-energy-rules.python-idioms.003 @rule:code-energy.python-idioms.legitimate-error-handling-in-loops-not-flagged @verified @source:greenlint/pyrules.py#_has_cheap_alternative @test:tests/test_greenlint.py#test_swallowed_io_error_in_loop_not_flagged @test:tests/test_greenlint.py#test_retry_loop_handler_not_flagged @test:tests/test_greenlint.py#test_per_item_error_collector_not_flagged @test:tests/test_greenlint.py#test_handler_that_breaks_not_flagged @test:tests/test_greenlint.py#test_try_except_around_loop_not_flagged
  Scenario Outline: Error handling that does real work or guards real I/O in a loop is not reported
    Given a Python file with <code>
    When the developer scans the project
    Then no GL031 finding is reported

    Examples:
      | code                                                          |
      | a loop that opens and parses files and continues on `OSError` |
      | a retry loop whose handler checks a deadline and sleeps       |
      | a loop that records each failure message in a results list    |
      | a read loop that breaks on `OSError`                          |
      | a `try` around the whole loop that passes on `KeyError`       |
