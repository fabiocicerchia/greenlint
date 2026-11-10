@domain:documentation @area:site-theme @from:stylesheets/extra
Feature: Branding the documentation site
  Gives readers of the greenlint docs and splash page one consistent GreenOps look that works offline and in both light and dark schemes.

  Background:
    Given the greenlint documentation site and its splash page are published

  @id:docs.documentation.site-theme.002 @rule:docs.theme.no-network-assets @inferred @source:docs/stylesheets/extra.css#:root
  Scenario: The docs render with system fonts and fetch nothing from the network
    Given the reader has no network access beyond the docs host
    When a reader opens any docs page
    Then body text is set in the operating system's sans-serif font
    And code is set in the operating system's monospace font
    And no web font or CDN asset is requested
