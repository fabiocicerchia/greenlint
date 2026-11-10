@domain:code-energy-rules @area:data-and-network-access @from:greenlint/rules
Feature: Flagging wasteful queries, requests and file reads
  Developers see where code fetches more data than it uses, or makes one round trip per item, in database, network and file access.

  @id:code-energy-rules.data-and-network-access.001 @rule:code-rules.data-access.select-star-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_select_star_and_fat_base @test:tests/test_greenlint.py#test_select_star_detected_in_c_and_rust @test:tests/test_greenlint.py#test_embedded_content_rules_still_match_inside_strings
  Scenario Outline: A SELECT * query is flagged in SQL and in code that embeds SQL
    Given a project containing <file> with <code>
    When the developer scans the project
    Then greenlint reports GL005 "SELECT * query" with severity medium

    Examples:
      | file  | code                             |
      | q.sql | SELECT * FROM users;             |
      | q.c   | char *q = "SELECT * FROM users"; |
      | q.rs  | let q = "SELECT * FROM users";   |
      | q.go  | q := "SELECT * FROM users"       |

  @id:code-energy-rules.data-and-network-access.002 @rule:code-rules.data-access.per-item-round-trip-in-loop-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_query_in_loop @test:tests/test_greenlint.py#test_detects_http_request_in_loop @test:tests/test_greenlint.py#test_detects_file_open_in_loop @questionable
  Scenario Outline: A query, HTTP request or file open as the first statement of a Python loop is flagged
    Given a project containing a Python file with a for loop whose first statement is <call>
    When the developer scans the project
    Then greenlint reports <rule> "<message>" with severity <severity>

    Examples:
      | call                                                              | rule  | message                                                       | severity |
      | cursor.execute("SELECT name FROM users WHERE id = ?", (user_id,)) | GL012 | database query executed inside a loop (N+1 pattern)           | medium   |
      | requests.get(f'/x/{i}')                                           | GL019 | HTTP request executed inside a loop (N+1-style network calls) | medium   |
      | f = open(p)                                                       | GL022 | file opened/read inside a loop                                | low      |

  @id:code-energy-rules.data-and-network-access.003 @rule:code-rules.data-access.batched-access-allowed @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_batched_query_not_flagged_as_n_plus_1 @test:tests/test_greenlint.py#test_batched_http_request_not_flagged @test:tests/test_greenlint.py#test_file_opened_outside_loop_not_flagged
  Scenario Outline: Batched queries, batched requests and comprehension reads are not flagged
    Given a project containing a Python file with <code>
    When the developer scans the project
    Then greenlint does not report <rule>

    Examples:
      | code                                                             | rule  |
      | cursor.execute(f"SELECT name FROM users WHERE id IN {user_ids}") | GL012 |
      | session.get('/batch', params={'ids': ids})                       | GL019 |
      | data = [open(p).read() for p in paths]                           | GL022 |
