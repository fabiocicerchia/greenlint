@domain:developer-tooling @area:container-distribution @from:greenlint/dockerfile
Feature: Running greenlint from its container image
  Gives CI operators a ready-made image that runs greenlint as a one-shot command, without installing Python packages on the runner.

  Background:
    Given the greenlint container image has been built from the repository

  @id:developer-tooling.container-distribution.001 @rule:distribution.container.no-arguments-shows-help @inferred @source:Dockerfile#runtime stage
  Scenario: Starting the image with no arguments prints the greenlint help
    When the operator runs the image without any arguments
    Then greenlint's usage help is printed
    And no scan is performed

  @id:developer-tooling.container-distribution.002 @rule:distribution.container.arguments-passed-to-greenlint @inferred @source:Dockerfile#runtime stage
  Scenario Outline: Arguments given to the image are passed straight to greenlint
    Given the operator's project is mounted into the container
    When the operator runs the image with <arguments>
    Then greenlint runs with <arguments> exactly as if they were typed on the greenlint command line
    And the container exits with greenlint's exit status

    Examples:
      | arguments          |
      | /src               |
      | --format json /src |
      | --list-rules       |

  @id:developer-tooling.container-distribution.003 @rule:distribution.container.runs-as-unprivileged-user @inferred @source:Dockerfile#runtime stage
  Scenario: greenlint in the container runs as an unprivileged user, not root
    When the operator runs the image without overriding the user
    Then greenlint runs as the user "app" with UID 10001
    And greenlint cannot write to files that are writable only by root
