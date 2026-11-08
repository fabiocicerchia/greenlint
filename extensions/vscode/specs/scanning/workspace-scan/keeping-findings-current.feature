@domain:scanning @area:workspace-scan @from:src/store
Feature: Keeping the project's findings current
  Serves developers watching the findings panel: what it lists must match the code as it stands now, without rescanning the whole project after every edit, fix or deletion.

  Background:
    Given a workspace folder "/work/shop" is open in the editor

  @id:vscode.scanning.workspace-scan.004 @rule:scanning.findings.rescan-replaces-only-that-file @verified @source:extensions/vscode/src/store.ts#FindingStore @test:extensions/vscode/src/test/store.test.ts#replaces one file without touching the rest
  Scenario: Re-scanning one file replaces that file's findings and leaves every other file's alone
    Given the panel lists 1 finding in "/work/shop/app.py" and 1 finding in "/work/shop/db.py"
    When the developer fixes the finding in "/work/shop/app.py" and the file is re-scanned
    Then the panel lists no findings for "/work/shop/app.py"
    And the panel still lists 1 finding for "/work/shop/db.py"
    And the total finding count shown is 1
