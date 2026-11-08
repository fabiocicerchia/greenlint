@domain:configuration @area:path-exclusion @from:greenlint/discovery
Feature: Matching ignore globs against scanned paths
  Operators who exclude paths in .greenlint.toml or with --exclude get those paths left out however the scan was invoked, so ignore lists behave as written.

  @id:configuration.path-exclusion.001 @rule:configuration.exclusion.globs-match-relative-scan-paths @verified @source:greenlint/discovery.py#_matches_any @test:tests/test_greenlint.py#test_relative_ignore_glob_applies @test:tests/test_greenlint.py#test_config_ignores_path @test:tests/test_greenlint.py#test_multiline_ignore_array_is_parsed
  Scenario Outline: An anchored ignore glob excludes files whether the project is scanned by a relative or an absolute path
    Given a project with tests/q.sql containing SELECT * FROM users
    And its .greenlint.toml sets ignore = ["*/tests/*"]
    When the operator runs greenlint <target> from the project directory
    Then no findings are reported

    Examples:
      | target                      |
      | .                           |
      | the project's absolute path |

  @id:configuration.path-exclusion.002 @rule:configuration.exclusion.explicit-file-still-excluded @verified @source:greenlint/discovery.py#is_ignored @test:tests/test_greenlint.py#test_is_ignored_matches_the_walkers_own_filtering @test:tests/test_greenlint.py#test_walk_files_prunes_virtualenvs_and_caches
  Scenario Outline: Naming an excluded file directly does not bring it back into the scan
    Given the file <file> contains SELECT * FROM users
    And <config>
    When the operator scans <file> by name
    Then no findings are reported for <file>

    Examples:
      | file             | config                                                     |
      | vendor/q.sql     | the project's .greenlint.toml sets ignore = ["*/vendor/*"] |
      | .venv/lib/mod.py | no ignore globs are configured                             |

  @id:configuration.path-exclusion.003 @rule:configuration.exclusion.case-insensitive-on-windows @inferred @source:greenlint/discovery.py#_ignore_matcher
  Scenario Outline: Ignore globs follow the platform's path case rules
    Given the project's .greenlint.toml sets ignore = ["*/vendor/*"]
    And a file Vendor/q.sql contains SELECT * FROM users
    When the operator scans the project on <platform>
    Then Vendor/q.sql is <outcome>

    Examples:
      | platform | outcome  |
      | Windows  | excluded |
      | Linux    | scanned  |
