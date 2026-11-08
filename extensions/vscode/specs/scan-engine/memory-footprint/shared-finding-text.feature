@domain:scan-engine @area:memory-footprint @from:src/share
Feature: Keeping large result sets light without changing what findings say
  Serves developers scanning large projects: repeated rule text and file paths are held once, so the editor stays light while every finding still shows its own rule's wording and its own file.

  Background:
    Given greenlint is installed and the scan server is running

  @id:vscode.scan-engine.memory-footprint.001 @rule:engine.memory.finding-keeps-own-rule-text-and-file @verified @source:extensions/vscode/src/share.ts#share @test:extensions/vscode/src/test/engine.test.ts#does not put one rule's prose on another rule @test:extensions/vscode/src/test/engine.test.ts#keeps each path when findings from two files are interleaved @test:extensions/vscode/src/test/engine.test.ts#holds one copy of a rule prose and one of a repeated path
  Scenario: Every finding shows its own rule's message, suggestion and CO2e note, and its own file
    Given a project where rule GL005 fires in "/proj/a.py" and rule GL003 fires in "/proj/b.py"
    And findings from the two files arrive interleaved: a.py, b.py, a.py
    When the developer scans the project
    Then the GL005 findings read "SELECT * query" with the suggestion "fetch only needed columns"
    And the GL003 finding reads "every-minute cron"
    And the findings are listed against "/proj/a.py", "/proj/b.py" and "/proj/a.py" in that order

  @id:vscode.scan-engine.memory-footprint.002 @rule:engine.memory.rule-wording-follows-running-greenlint @inferred @source:extensions/vscode/src/share.ts#forgetRuleProse
  Scenario: After the scan server restarts, findings use the wording of the greenlint now running
    Given findings from the previous greenlint version showed rule GL005 as "SELECT * query"
    And the developer has upgraded greenlint, and the new version words GL005 as "SELECT * fetches unused columns"
    When the scan server restarts and the developer scans the file again
    Then the GL005 finding reads "SELECT * fetches unused columns"
    And the GL005 finding no longer reads "SELECT * query"
