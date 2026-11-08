@domain:scanning @area:file-discovery @from:greenlint/discovery
Feature: Walking the files to scan
  Operators pointing greenlint at a project get findings for their own code only, without it wading through dependency trees and tool caches or stopping on directories it cannot read.

  Background:
    Given no .greenlint.toml ignore globs are configured

  @id:scanning.file-discovery.001 @rule:scanning.discovery.dependency-and-tool-directories-skipped @verified @source:greenlint/discovery.py#walk_files @test:tests/test_greenlint.py#test_walk_files_never_descends_into_pruned_directories @test:tests/test_greenlint.py#test_walk_files_prunes_virtualenvs_and_caches
  Scenario Outline: Dependency, version-control and cache directories are never scanned, build output directories are
    Given a project containing app.py with no findings
    And a file with a busy loop inside the directory <directory>
    When the operator scans the project directory
    Then the file inside <directory> is <outcome>

    Examples:
      | directory                    | outcome     |
      | .git/objects                 | not scanned |
      | node_modules/pkg             | not scanned |
      | .venv/lib/python3.11         | not scanned |
      | env3/lib/site-packages/other | not scanned |
      | .mypy_cache/3.11             | not scanned |
      | __pycache__                  | not scanned |
      | dist                         | scanned     |
      | build                        | scanned     |
      | target                       | scanned     |

  @id:scanning.file-discovery.002 @rule:scanning.discovery.symlinks @verified @source:greenlint/discovery.py#walk_files @test:tests/test_greenlint.py#test_walk_files_matches_what_rglob_selected
  Scenario: Symlinked files are scanned but symlinked directories are not followed
    Given a project with a.py and sub/b.py
    And link.py is a symlink to a.py
    And linkdir is a symlink to sub
    And broken.py is a symlink to a file that does not exist
    When the operator scans the project directory
    Then a.py, sub/b.py and link.py are scanned
    And nothing is scanned through linkdir
    And broken.py is skipped without an error

  @id:scanning.file-discovery.003 @rule:scanning.discovery.unreadable-directory-skipped-silently @verified @source:greenlint/discovery.py#walk_files @test:tests/test_greenlint.py#test_walk_files_survives_an_unreadable_directory @questionable
  Scenario: An unreadable directory is skipped silently and the rest of the project is still scanned
    Given a project with ok/a.py
    And a directory locked/ that the operator cannot read
    When the operator scans the project directory
    Then ok/a.py is scanned
    And the files in locked/ are not scanned
    And no warning about locked/ is printed

  @id:scanning.file-discovery.004 @rule:scanning.discovery.missing-path-yields-nothing @inferred @source:greenlint/discovery.py#iter_files @questionable
  Scenario: A scan target that does not exist produces no findings and no error
    Given no file or directory named srcc exists
    When the operator runs greenlint srcc
    Then the scan reports no findings
    And no error about the missing path is printed
