@domain:scanning @area:exclusions @from:src/excludes
Feature: Skipping what the editor already excludes
  Developers using the VS Code extension expect greenlint to leave alone the paths their editor already hides (build output, virtualenvs, vendored trees), so scans spend no time or energy there and report nothing from them.

  Background:
    Given a workspace folder at /home/dev/proj is open
    And the setting greenlint.respectEditorExcludes is on

  @id:vscode.scanning.exclusions.003 @rule:scanning.exclusions.editor-excluded-paths-not-scanned @verified @source:extensions/vscode/src/excludes.ts#editorExcludeGlobs @test:extensions/vscode/src/test/excludes.test.ts#emits both the entry and everything under it @test:extensions/vscode/src/test/excludes.test.ts#treats a trailing globstar as the directory itself @test:extensions/vscode/src/test/excludes.test.ts#takes both exclude settings, and only the plain true ones
  Scenario Outline: Paths hidden by the editor's exclude settings are not scanned, at any depth
    Given the editor setting <setting> excludes "<pattern>"
    When the developer scans the workspace
    Then no file at <excluded path> is scanned or reported
    And no file beneath <excluded path> is scanned or reported

    Examples:
      | setting        | pattern         | excluded path              |
      | files.exclude  | **/.git         | any .git directory         |
      | search.exclude | **/node_modules | any node_modules directory |
      | files.exclude  | **/dist/**      | any dist directory         |

  @id:vscode.scanning.exclusions.004 @rule:scanning.exclusions.root-relative-excludes-anchored-to-workspace @verified @source:extensions/vscode/src/excludes.ts#toIgnoreGlobs @test:extensions/vscode/src/test/excludes.test.ts#anchors a root-relative pattern to the real workspace path
  Scenario: A root-relative editor exclude covers only this workspace's own folder
    Given files.exclude excludes "out"
    And another folder named out exists elsewhere on disk, outside the workspace, and is scanned too
    When the developer scans the workspace
    Then nothing under /home/dev/proj/out is scanned or reported
    And findings in the out folder outside the workspace are still reported

  @id:vscode.scanning.exclusions.005 @rule:scanning.exclusions.only-plainly-enabled-excludes-honoured @verified @source:extensions/vscode/src/excludes.ts#editorExcludeGlobs @test:extensions/vscode/src/test/excludes.test.ts#takes both exclude settings, and only the plain true ones @questionable
  Scenario Outline: Only editor excludes switched plainly on keep files out of the scan
    Given files.exclude lists "<pattern>" with the value <value>
    When the developer scans the workspace
    Then files matching <pattern> are <outcome>

    Examples:
      | pattern        | value                        | outcome              |
      | **/.git        | true                         | not scanned          |
      | **/disabled    | false                        | scanned and reported |
      | **/conditional | { "when": "$(basename).ts" } | scanned and reported |

  @id:vscode.scanning.exclusions.006 @rule:scanning.exclusions.brace-alternatives-each-excluded @verified @source:extensions/vscode/src/excludes.ts#expandBraces @test:extensions/vscode/src/test/excludes.test.ts#expands brace alternatives, which fnmatch has no syntax for
  Scenario Outline: Every alternative in a braced editor exclude is excluded
    Given files.exclude excludes "<pattern>"
    When the developer scans the workspace
    Then files matching any of <alternatives> are not scanned or reported

    Examples:
      | pattern               | alternatives                           |
      | **/*.{log,tmp}        | **/*.log, **/*.tmp                     |
      | {build,dist}/{js,css} | build/js, build/css, dist/js, dist/css |

  @id:vscode.scanning.exclusions.007 @rule:scanning.exclusions.editor-excludes-can-be-turned-off @inferred @source:extensions/vscode/src/extension.ts#applyExcludes
  Scenario: Turning off editor excludes brings editor-hidden paths back into the scan
    Given files.exclude excludes "**/dist"
    And the setting greenlint.respectEditorExcludes is off
    When the developer scans the workspace
    Then files under dist directories are scanned and their findings reported
    And paths listed in greenlint.exclude are still not scanned
