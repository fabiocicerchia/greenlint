@domain:infrastructure-checks @area:ci-pipelines @from:greenlint/infra
Feature: Flagging full-history clones in CI
  Flags CI jobs that clone the whole git history for nothing, and stays quiet for jobs whose tools really need it, so pipeline owners trust the finding.

  Background:
    Given a project containing a CI workflow YAML file

  @id:infrastructure-checks.ci-pipelines.001 @rule:infra.ci.full-history-clone-flagged @verified @source:greenlint/infra.py#_fetch_depth_findings @test:tests/test_greenlint.py#test_detects_full_history_clone @test:tests/test_greenlint.py#test_full_history_clone_still_flagged_for_a_plain_build
  Scenario: A job that clones full history without needing it is flagged
    Given a workflow job "build" that checks out with fetch-depth: 0
    And the job then only runs make build
    When the developer scans the project
    Then the scan reports GL004 "full git history clone in CI" on the fetch-depth line

  @id:infrastructure-checks.ci-pipelines.002 @rule:infra.ci.history-needing-tools-exempt @verified @source:greenlint/infra.py#NEEDS_FULL_HISTORY @test:tests/test_greenlint.py#test_full_history_clone_not_flagged_when_a_scanner_needs_it @test:tests/test_greenlint.py#test_full_history_clone_not_flagged_for_release_tooling @test:tests/test_greenlint.py#test_full_history_clone_not_flagged_for_docs_date_plugins @test:tests/test_greenlint.py#test_full_history_clone_not_flagged_for_super_linter
  Scenario Outline: A job whose tools need commit history may clone it in full
    Given a workflow job that checks out with fetch-depth: 0
    And the same job uses <tool>
    When the developer scans the project
    Then the scan reports no GL004 finding

    Examples:
      | tool                                      |
      | gitleaks/gitleaks-action@v3               |
      | googleapis/release-please-action@v4       |
      | mkdocs-git-revision-date-localized-plugin |
      | super-linter                              |
      | git describe                              |
      | goreleaser                                |

  @id:infrastructure-checks.ci-pipelines.003 @rule:infra.ci.exemption-scoped-to-job @verified @source:greenlint/infra.py#_job_span @test:tests/test_greenlint.py#test_fetch_depth_exemption_is_per_job
  Scenario: One job's history-needing tool does not exempt other jobs
    Given a workflow with a "secrets" job that clones with fetch-depth: 0 and runs gitleaks
    And a "build" job in the same workflow that clones with fetch-depth: 0 and runs make build
    When the developer scans the project
    Then the scan reports GL004 only on the build job's fetch-depth line (line 13)

  @id:infrastructure-checks.ci-pipelines.004 @rule:infra.ci.commented-setting-ignored @verified @source:greenlint/infra.py#_fetch_depth_findings @test:tests/test_greenlint.py#test_full_history_clone_in_a_comment_not_flagged
  Scenario: A full-history setting that only appears in a comment is not flagged
    Given a CI action file whose only mention of fetch-depth: 0 is in a comment line
    When the developer scans the project
    Then the scan reports no GL004 finding
