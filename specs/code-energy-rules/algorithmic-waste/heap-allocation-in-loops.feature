@domain:code-energy-rules @area:algorithmic-waste @from:greenlint/rules
Feature: Flagging heap allocation inside C and C++ loops
  C and C++ developers see where allocator overhead repeats on every iteration instead of happening once.

  @id:code-energy-rules.algorithmic-waste.006 @rule:code-rules.algorithmic-waste.heap-allocation-in-loop-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_malloc_in_loop @questionable
  Scenario: An allocation on the line after a loop header is flagged
    Given a project containing a.c with a for loop whose first line is int *buf = malloc(100);
    When the developer scans the project
    Then greenlint reports GL032 "heap allocation inside a loop" with severity medium

  @id:code-energy-rules.algorithmic-waste.007 @rule:code-rules.algorithmic-waste.allocation-hoisted-out-of-loop-allowed @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_malloc_outside_loop_not_flagged
  Scenario: An allocation made once before the loop is not flagged
    Given a project containing a.c that allocates int *buf = malloc(100 * n); before an empty for loop
    When the developer scans the project
    Then greenlint does not report GL032
