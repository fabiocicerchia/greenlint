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

  @id:scanning.finding-placement.010 @rule:scanning.files.unreadable-file-silently-skipped @inferred @source:greenlint/scanning.py#scan_file @questionable
  Scenario: A file that cannot be read is left out of the report without a warning
    Given the project contains "q.sql" with "SELECT * FROM users;" that the scanning user cannot read
    When the developer scans the project
    Then no finding is reported for "q.sql"
    And no warning names "q.sql" as skipped
