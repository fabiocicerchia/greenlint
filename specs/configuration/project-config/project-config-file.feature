@domain:configuration @area:project-config @from:greenlint/config
Feature: Tuning a scan with .greenlint.toml
  Lets a project team switch off rules and skip paths from one checked-in file, and refuses a config that would look applied but silently do nothing.

  Background:
    Given the operator runs greenlint from the project root

  @id:configuration.project-config.001 @rule:configuration.project-config.disabled-rules-not-reported @verified @source:greenlint/config.py#load_config @test:tests/test_greenlint.py#test_config_disables_rule @test:tests/test_greenlint.py#test_ast_busy_loop_respects_disable
  Scenario Outline: Rules listed under disable are not reported
    Given a project containing "q.sql" with "SELECT * FROM users;"
    And a .greenlint.toml with disable = ["<rule>"]
    When the operator scans the project
    Then no finding for rule <rule> is reported

    Examples:
      | rule  |
      | GL005 |
      | GL001 |

  @id:configuration.project-config.002 @rule:configuration.project-config.ignore-list-honoured @verified @source:greenlint/config.py#load_config @test:tests/test_greenlint.py#test_config_ignores_path @test:tests/test_greenlint.py#test_config_array_may_span_lines @test:tests/test_greenlint.py#test_multiline_ignore_actually_excludes_files @test:tests/test_greenlint.py#test_multiline_ignore_array_is_parsed
  Scenario Outline: Paths matching the config's ignore list are not scanned, however the list is laid out
    Given a project with a wasteful file under "<dir>/"
    And a .greenlint.toml whose ignore array lists "*/<dir>/*" <layout>
    When the operator scans the project
    Then no findings are reported

    Examples:
      | dir      | layout                                             |
      | vendor   | on one line                                        |
      | examples | spread over several lines                          |
      | tests    | spread over several lines alongside "*/examples/*" |

  @id:configuration.project-config.003 @rule:configuration.project-config.absent-file-means-defaults @verified @source:greenlint/config.py#load_config @test:tests/test_greenlint.py#test_missing_config_is_a_noop
  Scenario: Without a config file every rule runs and nothing is ignored
    Given no .greenlint.toml in the working directory
    When the operator scans the project without --config
    Then every rule is active
    And no path is ignored apart from any --exclude flags

  @id:configuration.project-config.004 @rule:configuration.project-config.explicit-missing-config-ignored @inferred @source:greenlint/config.py#load_config @questionable
  Scenario: A --config path that does not exist is silently treated as no config
    Given no file at "conf/greenlint.toml"
    When the operator scans with --config conf/greenlint.toml
    Then the scan runs with every rule active and nothing ignored
    And no warning or error about the missing config is shown

  @id:configuration.project-config.005 @rule:configuration.project-config.invalid-toml-aborts @verified @source:greenlint/config.py#load_config @test:tests/test_greenlint.py#test_malformed_config_aborts
  Scenario: A config that is not valid TOML stops the scan
    Given a .greenlint.toml containing "disable = [" with no closing bracket
    When the operator scans the project
    Then no scan runs
    And the operator sees "greenlint: <config path>: invalid TOML — <parser detail>"
    And greenlint exits with status 1

  @id:configuration.project-config.006 @rule:configuration.project-config.string-instead-of-list-refused @verified @source:greenlint/config.py#_as_list @test:tests/test_greenlint.py#test_string_instead_of_list_is_rejected
  Scenario Outline: A setting written as a single string instead of a list is refused with the fix
    Given a .greenlint.toml containing <setting> = "<value>"
    When the operator scans the project
    Then no scan runs
    And the operator sees "greenlint: .greenlint.toml: `<setting>` must be a list, not a string — write `<setting> = ["<value>"]`"
    And greenlint exits with status 1

    Examples:
      | setting | value      |
      | disable | GL005      |
      | ignore  | */vendor/* |

  @id:configuration.project-config.007 @rule:configuration.project-config.non-list-value-crashes @inferred @source:greenlint/config.py#_as_list @questionable
  Scenario Outline: A setting given as a number or true/false crashes instead of being refused
    Given a .greenlint.toml containing disable = <value>
    When the operator scans the project
    Then no scan runs
    And the operator sees a Python traceback ending in "TypeError: '<type>' object is not iterable" rather than a greenlint message

    Examples:
      | value | type |
      | 5     | int  |
      | true  | bool |

  @id:configuration.project-config.008 @rule:configuration.project-config.unknown-settings-ignored @inferred @source:greenlint/config.py#load_config @questionable
  Scenario: Misspelled or unknown settings are silently ignored
    Given a project containing "q.sql" with "SELECT * FROM users;"
    And a .greenlint.toml containing disabled = ["GL005"]
    When the operator scans the project
    Then a GL005 finding is still reported
    And no warning names the unknown setting "disabled"
