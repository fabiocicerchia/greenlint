@domain:documentation @area:site-theme @from:stylesheets/extra
Feature: Branding the documentation site
  Gives readers of the greenlint docs and splash page one consistent GreenOps look that works offline and in both light and dark schemes.

  Background:
    Given the greenlint documentation site and its splash page are published

  @id:docs.documentation.site-theme.001 @rule:docs.theme.greenops-accent-palette @inferred @source:docs/stylesheets/extra.css#:root @questionable
  Scenario: The docs and the splash page share the GreenOps green accent pair
    Given the theme's accent pair is the GreenOps pair #34d399 and #059669
    When a reader opens the splash page and then the rendered docs
    Then links in the light scheme use #059669
    And the primary buttons and the home hero title show a gradient from #34d399 to #059669
    And the splash page title and button show the same two colours

  @id:docs.documentation.site-theme.002 @rule:docs.theme.no-network-assets @inferred @source:docs/stylesheets/extra.css#:root
  Scenario: The docs render with system fonts and fetch nothing from the network
    Given the reader has no network access beyond the docs host
    When a reader opens any docs page
    Then body text is set in the operating system's sans-serif font
    And code is set in the operating system's monospace font
    And no web font or CDN asset is requested

  @id:docs.documentation.site-theme.003 @rule:docs.theme.dark-scheme-legible @inferred @source:docs/stylesheets/extra.css#[data-md-color-scheme="slate"]
  Scenario: In the dark scheme the docs use a deep navy ground with light-accent links
    Given the reader's docs colour scheme is dark
    When a reader opens any docs page
    Then the page, header and tabs background is #0b0f1a
    And links are shown in #34d399

  @id:docs.documentation.site-theme.004 @rule:docs.theme.no-placeholder-logo @inferred @source:docs/stylesheets/extra.css#.md-header__button.md-logo
  Scenario: The docs header shows no stand-in logo
    Given the project has no logo configured
    When a reader opens any docs page
    Then no logo icon appears in the header or the navigation title
