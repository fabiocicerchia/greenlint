@domain:findings-explorer @area:grouping @from:src/extension
Feature: Arranging the Findings panel
  Developers choose how findings are grouped and scoped in the Findings panel, and the panel remembers their choice for the workspace.

  Background:
    Given a workspace folder "acme-api" is open

  @id:vscode.findings-explorer.grouping.001 @rule:findings.layout.defaults @verified @source:extensions/vscode/src/extension.ts#Controller @test:extensions/vscode/src/test/extension.test.ts#seeds the context keys the menus and welcome view read
  Scenario: A new workspace shows the whole project's findings grouped by file
    Given the developer has never changed the Findings panel's grouping or scope in this workspace
    When the extension starts
    Then the Findings panel shows findings for the whole project
    And findings are grouped by file
