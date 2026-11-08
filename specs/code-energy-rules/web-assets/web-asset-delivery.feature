@domain:code-energy-rules @area:web-assets @from:greenlint/rules
Feature: Flagging heavy front-end asset delivery
  Front-end developers see pages and servers that make browsers download more than necessary.

  @id:code-energy-rules.web-assets.001 @rule:code-rules.web-assets.heavy-delivery-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_img_missing_lazy_loading @test:tests/test_greenlint.py#test_detects_gif_in_html_and_css @test:tests/test_greenlint.py#test_detects_express_static_without_cache
  Scenario Outline: Eager images, GIFs and uncached static assets are flagged
    Given a project containing <file> with <code>
    When the developer scans the project
    Then greenlint reports <rule> "<message>" with severity low

    Examples:
      | file      | code                                    | rule  | message                                                 |
      | page.html | <img src="hero.png">                    | GL011 | img tag missing lazy loading                            |
      | page.html | <img loading="lazy" src="hero.gif">     | GL017 | GIF referenced for image/animation                      |
      | style.css | .bg { background: url("loading.gif"); } | GL017 | GIF referenced for image/animation                      |
      | server.js | app.use(express.static('public'));      | GL027 | static assets served without a cache duration (Express) |

  @id:code-energy-rules.web-assets.002 @rule:code-rules.web-assets.efficient-delivery-allowed @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_img_with_loading_attr_not_flagged @test:tests/test_greenlint.py#test_png_in_html_and_css_not_flagged @test:tests/test_greenlint.py#test_express_static_with_maxage_not_flagged
  Scenario Outline: Lazy images, modern formats and cached static assets are not flagged
    Given a project containing <file> with <code>
    When the developer scans the project
    Then greenlint does not report <rule>

    Examples:
      | file      | code                                                 | rule  |
      | page.html | <img loading="lazy" src="hero.png">                  | GL011 |
      | page.html | <img src="hero.png">                                 | GL017 |
      | server.js | app.use(express.static('public', { maxAge: '1y' })); | GL027 |
