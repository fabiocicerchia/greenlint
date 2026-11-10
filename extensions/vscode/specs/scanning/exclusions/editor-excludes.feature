@domain:scanning @area:exclusions @from:server/server-ops
Feature: Honouring the editor's excludes
  Keeps findings out of paths the developer has excluded in the editor, so generated or vendored files never produce noise.

  Background:
    Given the workspace has the same SELECT * in src/q.sql and dist/q.sql

  @id:vscode.scanning.exclusions.001 @rule:scanning.exclusions.editor-excludes-hide-findings @verified @source:extensions/vscode/server/server_ops.py#op_configure @test:tests/test_vscode_server.py#test_configure_adds_ignore_globs_on_top_of_the_config @test:tests/test_vscode_server.py#test_configure_applies_to_a_single_buffer_too
  Scenario Outline: Files under an editor exclude report no findings
    Given the editor excludes */dist/*
    When greenlint runs <how>
    Then no finding is reported for dist/q.sql
    And <src result>

    Examples:
      | how                                  | src result                           |
      | a workspace scan                     | the finding in src/q.sql is reported |
      | a scan of the saved file dist/q.sql  | no finding is reported at all        |
      | a scan of the open buffer dist/q.sql | no finding is reported at all        |

  @id:vscode.scanning.exclusions.002 @rule:scanning.exclusions.exclude-changes-apply-without-restart @verified @source:extensions/vscode/server/server_ops.py#op_configure @test:tests/test_vscode_server.py#test_configure_invalidates_what_was_cached_under_the_old_excludes
  Scenario Outline: Changing the editor excludes takes effect on the next scan without a restart
    Given a workspace scan has reported the finding in dist/q.sql
    When the developer <change>
    Then the next workspace scan <outcome>

    Examples:
      | change                                          | outcome                                 |
      | adds */dist/* to the editor excludes            | reports no finding for dist/q.sql       |
      | removes */dist/* from the editor excludes again | reports the finding in dist/q.sql again |
