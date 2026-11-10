@domain:code-energy-rules @area:algorithmic-waste @from:greenlint/pyrules
Feature: Flagging quadratic work in Python
  Lets developers find Python code that does O(n²) work (sequences rebuilt every pass, all-pairs rescans, hand-written swap sorts) without being flooded by idiomatic code that only looks similar.

  Background:
    Given a project containing Python source files

  @id:code-energy-rules.algorithmic-waste.001 @rule:code-energy.algorithmic-waste.python-sequence-rebuild-in-loop-flagged @verified @source:greenlint/pyrules.py#_ast_quadratic_rebuild_findings @test:tests/test_greenlint.py#test_detects_string_concat_in_loop @test:tests/test_greenlint.py#test_detects_quadratic_list_rebuild @test:tests/test_greenlint.py#test_bytes_accumulation_of_a_call_result_is_still_flagged @test:tests/test_greenlint.py#test_byte_accumulation_is_still_flagged @test:tests/test_greenlint.py#test_tuple_unpacked_list_still_detects_rebuild @test:tests/test_greenlint.py#test_assignment_of_a_list_expression_still_detects_rebuild @test:tests/test_greenlint.py#test_string_accumulator_is_still_flagged_when_the_scope_does_arithmetic
  Scenario Outline: Growing a string, bytes or list by copying it each loop pass is reported
    Given a Python file with the loop <code>
    When the developer scans the project
    Then a GL007 finding "quadratic rebuild in a loop (whole sequence copied each iteration)" with severity low is reported
    And the finding points at the line of the accumulation

    Examples:
      | code                                                                             |
      | `s = ''` then `s += w` for each word                                             |
      | `out = []` then `out = out + [i]` for each i                                     |
      | `data = b''` then `data += conn.recv(10)` inside `while True:`                   |
      | `s = ''` then `s += w`, in a function that also computes `n - 1` on another name |

  @id:code-energy-rules.algorithmic-waste.002 @rule:code-energy.algorithmic-waste.python-linear-accumulation-not-flagged @verified @source:greenlint/pyrules.py#_is_sequence_rebuild @test:tests/test_greenlint.py#test_append_in_loop_is_not_flagged @test:tests/test_greenlint.py#test_counter_increment_in_loop_is_not_flagged @test:tests/test_greenlint.py#test_numeric_accumulation_is_not_flagged @test:tests/test_greenlint.py#test_tuple_unpacked_counters_are_not_flagged @test:tests/test_greenlint.py#test_list_extend_via_augmented_assign_is_not_flagged @test:tests/test_greenlint.py#test_list_extend_with_comprehension_is_not_flagged @test:tests/test_greenlint.py#test_extend_of_a_name_known_to_be_a_list_is_not_flagged @test:tests/test_greenlint.py#test_cursor_seeded_from_arithmetic_is_not_flagged @test:tests/test_greenlint.py#test_coordinate_seeded_from_a_parameter_is_not_flagged @test:tests/test_greenlint.py#test_rebinding_from_other_names_is_not_flagged
  Scenario Outline: Appending, extending a list, adding up numbers or rebinding from other names in a loop are not reported as rebuilds
    Given a Python file with the loop <code>
    When the developer scans the project
    Then no GL007 finding is reported

    Examples:
      | code                                                             |
      | `out = []` then `out.append(i)`                                  |
      | `total = 0` then `total += 1`                                    |
      | `kwh += r.hours * r.watts / 1000` and `seen += len(r.data)`      |
      | `mwh, grams = 0.0, 0.0` then `mwh += r` and `grams += r`         |
      | `xs = []` then `xs += [g.a, g.b]`                                |
      | `lines = []` then `lines += render(g)`                           |
      | `day = start - (start % DAY)` then `day += DAY`                  |
      | `y = top` then `y += height(row) + gap`, with `y - gap` returned |
      | `z = x + y`                                                      |

  @id:code-energy-rules.algorithmic-waste.003 @rule:code-energy.algorithmic-waste.python-rebuild-evidence-is-per-function @verified @source:greenlint/pyrules.py#_ast_quadratic_rebuild_findings @test:tests/test_greenlint.py#test_quadratic_rebuild_name_bindings_are_per_scope @test:tests/test_greenlint.py#test_numeric_evidence_does_not_leak_across_scopes
  Scenario: A counter in one function does not hide a rebuild of the same name in another
    Given a Python file where function `a` uses `total` as a number
    And function `b` builds a string `total` with `+=` in a loop on line 9
    When the developer scans the project
    Then exactly one GL007 finding is reported, on line 9

  @id:code-energy-rules.algorithmic-waste.004 @rule:code-energy.algorithmic-waste.python-nested-scan-of-same-collection-flagged @verified @source:greenlint/pyrules.py#_ast_nested_loop_findings @test:tests/test_greenlint.py#test_detects_nested_loop_over_same_collection @test:tests/test_greenlint.py#test_nested_loop_over_different_collections_not_flagged
  Scenario Outline: A loop nested inside a loop over the same collection is reported as an all-pairs scan
    Given a Python file with `for i in items:` enclosing `for j in <inner>:`
    When the developer scans the project
    Then <outcome>

    Examples:
      | inner  | outcome                                                                                                                 |
      | items  | a GL018 finding "nested loop iterating over the same collection (possible O(n²) pattern)" is reported at the inner loop |
      | others | no GL018 finding is reported                                                                                            |

  @id:code-energy-rules.algorithmic-waste.005 @rule:code-energy.algorithmic-waste.python-hand-written-swap-sort-flagged @verified @source:greenlint/pyrules.py#_ast_bubble_sort_findings @test:tests/test_greenlint.py#test_detects_manual_bubble_sort @test:tests/test_greenlint.py#test_builtin_sorted_not_flagged
  Scenario Outline: A hand-written swap sort is reported, the built-in sort is not
    Given a Python function that <code>
    When the developer scans the project
    Then <outcome>

    Examples:
      | code                                                                                     | outcome                                                                                                 |
      | swaps `a[j], a[j + 1] = a[j + 1], a[j]` inside a `for` loop nested in another `for` loop | a GL023 finding "nested loop with an element swap (manual O(n²) sort)" with severity medium is reported |
      | returns `sorted(a)`                                                                      | no GL023 finding is reported                                                                            |
