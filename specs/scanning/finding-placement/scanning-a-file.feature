@domain:scanning @area:finding-placement @from:greenlint/scanning
Feature: Scanning a file for energy waste
  Developers and CI operators rely on each scanned file yielding only findings from the rules that apply to its language, its role (test or production) and the project's opt-outs, so reports stay trustworthy.

  Background:
    Given greenlint is run on a project

  @id:scanning.finding-placement.005 @rule:scanning.files.untargeted-language-yields-nothing @verified @source:greenlint/scanning.py#scan_file @test:tests/test_greenlint.py#test_a_file_no_rule_targets_is_not_even_read @test:tests/test_greenlint.py#test_scan_file_text_override_still_picks_language_from_the_path @test:tests/test_greenlint.py#test_scannable_matches_whether_scan_file_can_find_anything
  Scenario Outline: A file no rule targets produces no findings
    Given the project contains a file "<file>" whose contents read "SELECT * FROM t;"
    When the developer scans the project
    Then greenlint reports no findings for "<file>"

    Examples:
      | file            |
      | logo.png        |
      | Dockerfile.prod |
      | notes.md        |

  @id:scanning.finding-placement.006 @rule:scanning.files.unsaved-contents-scanned-by-name @verified @source:greenlint/scanning.py#scan_file @test:tests/test_greenlint.py#test_scan_file_accepts_text_instead_of_reading_the_file @test:tests/test_greenlint.py#test_scan_file_text_override_still_picks_language_from_the_path
  Scenario Outline: Unsaved contents are judged by the language of the name they will be saved under
    Given the editor holds unsaved contents "SELECT * FROM users;" for "<name>", which does not exist on disk
    When the editor asks greenlint to scan those contents
    Then the findings are "<rules>"
    And each finding names the file "<name>"

    Examples:
      | name     | rules |
      | q.sql    | GL005 |
      | notes.md | none  |

  @id:scanning.finding-placement.007 @rule:scanning.files.test-code-exempt-from-loop-rules @verified @source:greenlint/scanning.py#scan_file @test:tests/test_greenlint.py#test_short_sleep_in_a_test_file_is_not_flagged @test:tests/test_greenlint.py#test_short_sleep_in_production_code_is_still_flagged
  Scenario Outline: Test code is not flagged for tight waits, busy loops or per-iteration rebuilds
    Given the project contains "<file>" with a 10 ms sleep
    When the developer scans the project
    Then no GL002 sub-100ms polling finding is reported for "<file>"
    And the busy-loop rule GL001 and the rebuild-in-loop rule GL007 are likewise not applied to "<file>"
    And every other enabled rule still applies to "<file>"

    Examples:
      | file           |
      | proxy_test.go  |
      | test_proxy.py  |
      | tests/proxy.go |
      | spec/proxy.rb  |
      | proxy.spec.js  |

  @id:scanning.finding-placement.008 @rule:scanning.rules.disabled-rule-never-reported @verified @source:greenlint/scanning.py#scan_file @test:tests/test_greenlint.py#test_config_disables_rule @test:tests/test_greenlint.py#test_ast_busy_loop_respects_disable
  Scenario Outline: A rule the project opted out of is never reported
    Given the project opts out of rule "<rule>"
    And the project contains "<file>" that would trigger "<rule>"
    When the developer scans the project
    Then no "<rule>" finding is reported

    Examples:
      | rule  | file                                            |
      | GL005 | q.sql containing SELECT * FROM users;           |
      | GL001 | a.py containing a while True loop without sleep |

  @id:scanning.finding-placement.009 @rule:scanning.matching.prose-is-not-code @verified @source:greenlint/scanning.py#scan_file @test:tests/test_greenlint.py#test_pattern_in_a_comment_is_not_a_finding @test:tests/test_greenlint.py#test_pattern_in_a_docstring_is_not_a_finding @test:tests/test_greenlint.py#test_pattern_in_a_real_string_is_still_a_finding
  Scenario Outline: A pattern written in a comment or docstring is not a finding, but one in a string literal is
    Given the project contains "<file>" with "<contents>"
    When the developer scans the project
    Then the GL005 finding is "<reported>"

    Examples:
      | file  | contents                                | reported |
      | b.sql | -- bad: SELECT * FROM users;            | absent   |
      | a.py  | # never write SELECT * FROM users       | absent   |
      | a.py  | """Never write SELECT * FROM orders.""" | absent   |
      | a.py  | q = "SELECT * FROM users"               | present  |

  @id:scanning.finding-placement.010 @rule:scanning.files.unreadable-file-silently-skipped @inferred @source:greenlint/scanning.py#scan_file @questionable
  Scenario: A file that cannot be read is left out of the report without a warning
    Given the project contains "q.sql" with "SELECT * FROM users;" that the scanning user cannot read
    When the developer scans the project
    Then no finding is reported for "q.sql"
    And no warning names "q.sql" as skipped
