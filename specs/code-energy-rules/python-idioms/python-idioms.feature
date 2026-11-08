@domain:code-energy-rules @area:python-idioms @from:greenlint/rules
Feature: Flagging energy-costly Python idioms
  Python developers learn about idioms that do work nobody uses: eager log formatting, row-by-row pandas and star imports.

  @id:code-energy-rules.python-idioms.004 @rule:code-rules.python-idioms.costly-idiom-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_eager_logging_fstring @test:tests/test_greenlint.py#test_detects_pandas_iterrows @test:tests/test_greenlint.py#test_detects_wildcard_import
  Scenario Outline: Eager log formatting, row-wise pandas and wildcard imports are flagged
    Given a project containing a Python file with <code>
    When the developer scans the project
    Then greenlint reports <rule> "<message>" with severity <severity>

    Examples:
      | code                         | rule  | message                                                  | severity |
      | logging.debug(f"x={x}")      | GL020 | logging call built eagerly with an f-string or .format() | low      |
      | for i, row in df.iterrows(): | GL021 | row-wise pandas iteration (iterrows/apply(axis=1))       | medium   |
      | df.apply(score, axis=1)      | GL021 | row-wise pandas iteration (iterrows/apply(axis=1))       | medium   |
      | from os import *             | GL028 | wildcard import                                          | low      |

  @id:code-energy-rules.python-idioms.005 @rule:code-rules.python-idioms.efficient-idiom-allowed @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_lazy_logging_not_flagged @test:tests/test_greenlint.py#test_vectorised_pandas_not_flagged @test:tests/test_greenlint.py#test_named_import_not_flagged
  Scenario Outline: Lazy log arguments, vectorised pandas and named imports are not flagged
    Given a project containing a Python file with <code>
    When the developer scans the project
    Then greenlint does not report <rule>

    Examples:
      | code                        | rule  |
      | logging.debug("x=%s", x)    | GL020 |
      | df["c"] = df["a"] + df["b"] | GL021 |
      | from math import sqrt       | GL028 |
