@domain:scanning @area:comment-and-string-masking @from:greenlint/comments
Feature: Ignoring prose, comments and quoted examples when scanning
  Developers running greenlint need findings only for real code, not for comments, docstrings or quoted samples that merely mention a wasteful pattern, so the linter is not switched off for crying wolf.

  Background:
    Given the developer has a project checked out

  @id:scanning.comment-and-string-masking.001 @rule:scanning.masking.comments-never-produce-findings @verified @source:greenlint/comments.py#_blank_comments @test:tests/test_greenlint.py#test_pattern_in_a_comment_is_not_a_finding @test:tests/test_greenlint.py#test_block_comment_is_blanked @test:tests/test_greenlint.py#test_commented_out_dockerfile_directive_not_flagged
  Scenario Outline: A wasteful pattern written inside a comment is not reported
    Given the file <file> contains only the comment <comment> and otherwise harmless code
    When the developer scans the project
    Then no <rule> finding is reported for <file>

    Examples:
      | file       | comment                                        | rule  |
      | a.py       | # never write SELECT * FROM users              | GL005 |
      | b.sql      | -- bad: SELECT * FROM users;                   | GL005 |
      | c.go       | // avoid time.Sleep(10 * time.Millisecond)     | GL002 |
      | a.go       | /* SELECT * FROM users */ spanning three lines | GL005 |
      | d.yml      | # not a cron: * * * * * schedule               | GL003 |
      | Dockerfile | # FROM ubuntu:22.04                            | GL006 |
      | page.html  | <!-- <img src="old.gif"> -->                   | GL017 |

  @id:scanning.comment-and-string-masking.002 @rule:scanning.masking.python-docstrings-never-produce-findings @verified @source:greenlint/comments.py#_blank_python_docstrings @test:tests/test_greenlint.py#test_pattern_in_a_docstring_is_not_a_finding
  Scenario: A wasteful pattern described in a Python docstring is not reported
    Given a Python module whose docstring reads "Never write SELECT * FROM orders."
    When the developer scans the project
    Then no SELECT * finding (GL005) is reported for that module

  @id:scanning.comment-and-string-masking.003 @rule:scanning.masking.queries-in-string-literals-still-reported @verified @source:greenlint/comments.py#_blank_comments @test:tests/test_greenlint.py#test_pattern_in_a_real_string_is_still_a_finding @test:tests/test_greenlint.py#test_hash_inside_a_string_is_not_a_comment @test:tests/test_greenlint.py#test_embedded_content_rules_still_match_inside_strings
  Scenario Outline: A real query held in a string literal is still reported, even when it starts with a comment marker
    Given the file <file> contains the code <code>
    When the developer scans the project
    Then a SELECT * finding (GL005) is reported for <file>

    Examples:
      | file | code                        |
      | a.py | q = "SELECT * FROM users"   |
      | a.py | q = "# SELECT * FROM users" |
      | q.go | q := "SELECT * FROM users"  |

  @id:scanning.comment-and-string-masking.004 @rule:scanning.masking.code-shape-rules-ignore-quoted-samples @verified @source:greenlint/comments.py#_blank_strings @test:tests/test_greenlint.py#test_code_shaped_rule_ignores_a_match_inside_a_string
  Scenario Outline: A code-shaped pattern quoted inside a string is not reported, while the same code outside a string is
    Given the Go file <file> contains <code>
    When the developer scans the project
    Then a sub-100ms polling finding (GL002) is <outcome> for <file>

    Examples:
      | file | code                                                                 | outcome      |
      | a.go | time.Sleep(10 * time.Millisecond)                                    | reported     |
      | b.go | msg := "time.Sleep(10 * time.Millisecond)"                           | not reported |
      | c.go | s := "he said \"sleep(1)\" loudly"; time.Sleep(1 * time.Millisecond) | reported     |

  @id:scanning.comment-and-string-masking.005 @rule:scanning.masking.contractions-do-not-break-masking @verified @source:greenlint/comments.py#_is_apostrophe @test:tests/test_greenlint.py#test_apostrophe_does_not_unblank_the_rest_of_the_file @test:tests/test_greenlint.py#test_apostrophe_does_not_hide_a_real_finding
  Scenario Outline: An English contraction in code does not unmask later comments or hide later code
    Given a shell script whose first line is: echo don't
    And its second line is <line>
    When the developer scans the project
    Then a sub-100ms polling finding (GL002) is <outcome>

    Examples:
      | line                             | outcome      |
      | # never use sleep 0.01 in a loop | not reported |
      | sleep 0.01                       | reported     |

  @id:scanning.comment-and-string-masking.006 @rule:scanning.masking.line-numbers-unchanged @inferred @source:greenlint/comments.py#_blank_spans
  Scenario: Masking comments and strings does not shift reported line numbers
    Given a Go file whose first two lines are a block comment
    And its third line holds a string literal
    And its fourth line is time.Sleep(10 * time.Millisecond)
    When the developer scans the project
    Then the sub-100ms polling finding (GL002) is reported at line 4

  @id:scanning.comment-and-string-masking.007 @rule:scanning.masking.multiline-strings-stay-visible @inferred @source:greenlint/comments.py#_string_end @questionable
  Scenario: A pattern inside a multi-line string is still reported
    Given a Go file with a multi-line raw string literal whose second line reads time.Sleep(1 * time.Millisecond)
    When the developer scans the project
    Then a sub-100ms polling finding (GL002) is reported for that file

  @id:scanning.comment-and-string-masking.008 @rule:scanning.masking.css-urls-not-mistaken-for-comments @inferred @source:greenlint/comments.py#COMMENT_SYNTAX
  Scenario: A full URL in a stylesheet is not mistaken for a comment
    Given a stylesheet containing .bg { background: url(http://cdn.example.com/loading.gif); }
    When the developer scans the project
    Then a GIF animation finding (GL017) is reported for the stylesheet
