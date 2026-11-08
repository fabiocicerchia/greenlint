@domain:infrastructure-checks @area:cloud-resources @from:greenlint/infra
Feature: Flagging wasteful Terraform resources
  Flags Terraform buckets, log groups and autoscaling groups that keep data or capacity forever, so teams cut storage and idle compute before they are deployed.

  Background:
    Given a project containing Terraform files

  @id:infrastructure-checks.cloud-resources.001 @rule:infra.terraform.s3-bucket-needs-lifecycle @verified @source:greenlint/infra.py#_tf_s3_lifecycle_findings @test:tests/test_greenlint.py#test_detects_s3_bucket_without_lifecycle @test:tests/test_greenlint.py#test_s3_bucket_with_lifecycle_not_flagged @questionable
  Scenario Outline: An S3 bucket with no lifecycle rule is flagged
    Given a Terraform file declaring an "aws_s3_bucket" resource whose body <body>
    When the developer scans the project
    Then the scan reports <outcome>

    Examples:
      | body                                                       | outcome                                                             |
      | sets only bucket = "my-logs"                               | GL013 "S3 bucket without a lifecycle policy" on the resource's line |
      | contains a lifecycle_rule block                            | no GL013 finding                                                    |
      | contains only a lifecycle { prevent_destroy = true } block | no GL013 finding                                                    |

  @id:infrastructure-checks.cloud-resources.002 @rule:infra.terraform.separate-lifecycle-configuration-not-recognised @inferred @source:greenlint/infra.py#_tf_s3_lifecycle_findings @questionable
  Scenario: A bucket whose lifecycle is a separate resource is still flagged
    Given a Terraform file declaring an "aws_s3_bucket" resource with no lifecycle setting in its body
    And an "aws_s3_bucket_lifecycle_configuration" resource for that bucket in the same file
    When the developer scans the project
    Then the scan reports GL013 "S3 bucket without a lifecycle policy" on the bucket's line

  @id:infrastructure-checks.cloud-resources.003 @rule:infra.terraform.log-group-needs-retention @verified @source:greenlint/infra.py#_tf_log_retention_findings @test:tests/test_greenlint.py#test_detects_log_group_without_retention @test:tests/test_greenlint.py#test_log_group_with_retention_not_flagged
  Scenario Outline: A CloudWatch log group with no retention period is flagged
    Given a Terraform file declaring an "aws_cloudwatch_log_group" resource that <retention>
    When the developer scans the project
    Then the scan reports <outcome>

    Examples:
      | retention                   | outcome                                                                        |
      | sets only name = "app"      | GL026 "CloudWatch log group without a retention period" on the resource's line |
      | sets retention_in_days = 30 | no GL026 finding                                                               |

  @id:infrastructure-checks.cloud-resources.004 @rule:infra.terraform.autoscaling-group-must-be-elastic @verified @source:greenlint/infra.py#_tf_asg_static_size_findings @test:tests/test_greenlint.py#test_detects_fixed_size_autoscaling_group @test:tests/test_greenlint.py#test_elastic_autoscaling_group_not_flagged
  Scenario Outline: An autoscaling group whose minimum and maximum size are equal is flagged
    Given a Terraform file declaring an "aws_autoscaling_group" resource with min_size = <min> and max_size = <max>
    When the developer scans the project
    Then the scan reports <outcome>

    Examples:
      | min | max | outcome                                                                    |
      | 3   | 3   | GL024 "autoscaling group with min_size == max_size" on the resource's line |
      | 1   | 5   | no GL024 finding                                                           |
