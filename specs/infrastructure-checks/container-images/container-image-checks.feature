@domain:infrastructure-checks @area:container-images @from:greenlint/rules
Feature: Checking Dockerfiles for bloated images
  Developers see which images pull and store more than they need, so that they can shrink transfer, storage and cold-start energy.

  @id:infrastructure-checks.container-images.004 @rule:infra.container-images.bloated-or-eol-base-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_select_star_and_fat_base @test:tests/test_greenlint.py#test_detects_eol_docker_base_image
  Scenario Outline: A full-fat or end-of-life base image is flagged
    Given a project containing a Dockerfile starting with <from>
    When the developer scans the project
    Then greenlint reports <rule> "<message>" with severity medium

    Examples:
      | from                 | rule  | message                                                |
      | FROM ubuntu:24.04    | GL006 | full-fat base image                                    |
      | FROM debian:bookworm | GL006 | full-fat base image                                    |
      | FROM node:12         | GL015 | base image pinned to an end-of-life runtime/OS version |
      | FROM python:2.7      | GL015 | base image pinned to an end-of-life runtime/OS version |
      | FROM centos:7        | GL015 | base image pinned to an end-of-life runtime/OS version |

  @id:infrastructure-checks.container-images.005 @rule:infra.container-images.slim-current-base-allowed @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_slim_base_not_flagged @test:tests/test_greenlint.py#test_current_docker_base_image_not_flagged
  Scenario Outline: A slim or current base image is not flagged
    Given a project containing a Dockerfile starting with <from>
    When the developer scans the project
    Then greenlint does not report <rule>

    Examples:
      | from                      | rule  |
      | FROM debian:bookworm-slim | GL006 |
      | FROM node:22              | GL015 |

  @id:infrastructure-checks.container-images.006 @rule:infra.container-images.package-install-without-slimming-flag @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_apt_and_pip_without_cleanup_flags @test:tests/test_greenlint.py#test_apt_and_pip_cleanup_flags_not_flagged
  Scenario Outline: Package installs that keep recommends or the pip cache are flagged
    Given a project containing a Dockerfile with the line <line>
    When the developer scans the project
    Then greenlint <outcome> <rule>

    Examples:
      | line                                                | outcome                   | rule  |
      | RUN apt-get update && apt-get install -y curl       | reports with severity low | GL009 |
      | RUN apt-get install -y --no-install-recommends curl | does not report           | GL009 |
      | RUN pip install -r requirements.txt                 | reports with severity low | GL010 |
      | RUN pip install --no-cache-dir -r requirements.txt  | does not report           | GL010 |
