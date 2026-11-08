@domain:editor-feedback @area:rule-documentation @from:src/types
Feature: Linking findings to their rule documentation
  Developers reach the explanation of why a pattern wastes energy in one click from any finding.

  @id:vscode.editor-feedback.rule-documentation.001 @rule:editor-feedback.rule-docs.link-to-rule-section @verified @source:extensions/vscode/src/types.ts#ruleDocsUrl @test:extensions/vscode/src/test/types.test.ts#builds the GitHub anchor for a rule, doubled hyphen and all
  Scenario Outline: A finding links to its rule's section of the rules reference
    Given a finding for rule <rule> with message "<message>"
    When the developer follows the rule link on the finding
    Then the link opens <url>

    Examples:
      | rule  | message                                                            | url                                                                                                                                         |
      | GL001 | busy loop without sleep                                            | https://github.com/fabiocicerchia/greenlint/blob/main/docs/rules.md#gl001--busy-loop-without-sleep                                          |
      | GL007 | quadratic rebuild in a loop (whole sequence copied each iteration) | https://github.com/fabiocicerchia/greenlint/blob/main/docs/rules.md#gl007--quadratic-rebuild-in-a-loop-whole-sequence-copied-each-iteration |
