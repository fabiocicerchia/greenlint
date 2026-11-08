@domain:infrastructure-checks @area:cloud-resources @from:greenlint/rules
Feature: Checking Terraform for oversized and inefficient cloud resources
  Developers are told which hard-coded instance and volume choices draw more power than an equivalent alternative.

  @id:infrastructure-checks.cloud-resources.005 @rule:infra.cloud-resources.inefficient-instance-or-volume-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_very_large_instance_type @test:tests/test_greenlint.py#test_detects_non_graviton_instance_family @test:tests/test_greenlint.py#test_opentofu_files_use_the_same_terraform_rules @test:tests/test_greenlint.py#test_detects_gp2_volume
  Scenario Outline: Peak-sized, x86-only instances and gp2 volumes are flagged in Terraform and OpenTofu
    Given a project containing <file> with the line <setting>
    When the developer scans the project
    Then greenlint reports <rule> "<message>" with severity <severity>

    Examples:
      | file      | setting                       | rule  | message                                                       | severity |
      | main.tf   | instance_type = "m5.16xlarge" | GL008 | very large instance type hardcoded                            | high     |
      | main.tf   | instance_type = "m5.large"    | GL016 | x86 instance family with an ARM/Graviton equivalent available | low      |
      | main.tofu | instance_type = "m5.large"    | GL016 | x86 instance family with an ARM/Graviton equivalent available | low      |
      | vol.tf    | volume_type = "gp2"           | GL025 | EBS volume using gp2 instead of gp3                           | low      |

  @id:infrastructure-checks.cloud-resources.006 @rule:infra.cloud-resources.right-sized-choices-allowed @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_modest_instance_type_not_flagged @test:tests/test_greenlint.py#test_graviton_instance_family_not_flagged @test:tests/test_greenlint.py#test_gp3_volume_not_flagged
  Scenario Outline: Modest, ARM-based instances and gp3 volumes are not flagged
    Given a project containing <file> with the line <setting>
    When the developer scans the project
    Then greenlint does not report <rule>

    Examples:
      | file    | setting                      | rule  |
      | main.tf | instance_type = "m5.4xlarge" | GL008 |
      | main.tf | instance_type = "m6g.large"  | GL016 |
      | vol.tf  | volume_type = "gp3"          | GL025 |

  @id:infrastructure-checks.cloud-resources.007 @rule:infra.cloud-resources.large-modern-families-unchecked @inferred @source:greenlint/rules.py#RULES @questionable
  Scenario Outline: Very large instances from newer or suffixed families, or above 24xlarge, are not flagged as oversized
    Given a project containing main.tf with the line <setting>
    When the developer scans the project
    Then greenlint does not report GL008

    Examples:
      | setting                        |
      | instance_type = "r6g.16xlarge" |
      | instance_type = "m6i.24xlarge" |
      | instance_type = "m5.48xlarge"  |
