@domain:infrastructure-checks @area:ci-pipelines @from:greenlint/rules
Feature: Flagging schedules that run every minute
  Developers are warned when a workflow or CronJob is set to wake up every minute.

  @id:infrastructure-checks.ci-pipelines.005 @rule:infra.ci-pipelines.every-minute-cron-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_every_minute_cron @test:tests/test_greenlint.py#test_detects_k8s_cronjob_schedule_every_minute
  Scenario Outline: A cron schedule of every minute is flagged as high severity
    Given a project containing <file> with the schedule line <line>
    When the developer scans the project
    Then greenlint reports GL003 "cron job scheduled every minute" with severity high

    Examples:
      | file                     | line                  |
      | .github/workflows/ci.yml | - cron: '* * * * *'   |
      | cron.yaml                | schedule: '* * * * *' |

  @id:infrastructure-checks.ci-pipelines.006 @rule:infra.ci-pipelines.wider-schedules-allowed @inferred @source:greenlint/rules.py#RULES
  Scenario: A schedule with a wider interval is not flagged
    Given a project containing ci.yml with the schedule line - cron: '*/5 * * * *'
    When the developer scans the project
    Then greenlint does not report GL003
