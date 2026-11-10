@domain:infrastructure-checks @area:container-images @from:greenlint/infra
Feature: Flagging separate install layers in Dockerfiles
  Points image authors to installs that each add their own image layer, so images are smaller to store and pull.

  Background:
    Given a project containing a Dockerfile

  @id:infrastructure-checks.container-images.001 @rule:infra.dockerfile.one-install-layer-per-stage @verified @source:greenlint/infra.py#_dockerfile_layer_bloat_findings @test:tests/test_greenlint.py#test_detects_multiple_dockerfile_install_layers @test:tests/test_greenlint.py#test_single_dockerfile_install_layer_not_flagged @test:tests/test_greenlint.py#test_detects_two_install_layers_in_one_stage
  Scenario Outline: Every install step after the first in a build stage is flagged
    Given a Dockerfile stage FROM debian:bookworm-slim whose install steps are <steps>
    When the developer scans the project
    Then the scan reports <outcome>

    Examples:
      | steps                                                                  | outcome                                                                      |
      | RUN apt-get install -y curl, then RUN pip3 install -r requirements.txt | GL029 "separate RUN install layer (image layer bloat)" on the pip3 line only |
      | RUN apt-get install -y curl && pip3 install -r requirements.txt        | no GL029 finding                                                             |

  @id:infrastructure-checks.container-images.002 @rule:infra.dockerfile-install-layers-counted-per-stage @verified @source:greenlint/infra.py#_dockerfile_layer_bloat_findings @test:tests/test_greenlint.py#test_install_layers_in_separate_build_stages_not_flagged
  Scenario: Installs in different build stages are not flagged
    Given a Dockerfile with a build stage FROM python:3.12 AS build that runs RUN pip install build
    And a final stage FROM python:3.12-slim that runs RUN pip install /tmp/x.whl
    When the developer scans the project
    Then the scan reports no GL029 finding

  @id:infrastructure-checks.container-images.003 @rule:infra.dockerfile.install-tools-recognised @inferred @source:greenlint/infra.py#_dockerfile_layer_bloat_findings @questionable
  Scenario Outline: Only apt, apt-get, pip, pip3, npm and yum installs count as install layers
    Given a Dockerfile stage with two separate steps RUN <tool> curl and RUN <tool> git
    When the developer scans the project
    Then the scan reports <outcome>

    Examples:
      | tool               | outcome                  |
      | apt-get install -y | GL029 on the second step |
      | yum install -y     | GL029 on the second step |
      | apk add            | no GL029 finding         |
      | dnf install -y     | no GL029 finding         |
