@domain:scanning @area:language-detection @from:greenlint/base
Feature: Recognising Dockerfiles and other files by name or extension
  Lets an operator know which files greenlint treats as Dockerfiles, so container-image checks run on the files they expect and not on look-alikes.

  Background:
    Given a project containing a file whose base image line is "FROM ubuntu:24.04"

  @id:scanning.language-detection.001 @rule:scanning.language.dockerfile-selected-by-exact-name-or-suffix @verified @source:greenlint/base.py#lang_key @test:tests/test_greenlint.py#test_detects_select_star_and_fat_base
  Scenario Outline: A file named Dockerfile, or ending in .dockerfile, gets the container-image checks
    Given the file is named "<file name>"
    When the operator scans the project
    Then the report includes a "full-fat base image" finding (GL006) for "<file name>"

    Examples:
      | file name        |
      | Dockerfile       |
      | build.dockerfile |

  @id:scanning.language-detection.002 @rule:scanning.language.dockerfile-name-variants-not-scanned @verified @source:greenlint/base.py#lang_key @test:tests/test_greenlint.py#test_scannable_matches_whether_scan_file_can_find_anything @questionable
  Scenario Outline: Common Dockerfile name variants are skipped without any finding
    Given the file is named "<file name>"
    When the operator scans the project
    Then the report has no finding for "<file name>"

    Examples:
      | file name       |
      | Dockerfile.prod |
      | dockerfile      |
      | api.Dockerfile  |
