@domain:code-energy-rules @area:busy-waiting @from:greenlint/rules
Feature: Flagging busy waiting and tight polling
  Developers learn where their code keeps a CPU core awake for nothing, by spinning on a clock or polling faster than every 100 ms.

  @id:code-energy-rules.busy-waiting.004 @rule:code-rules.busy-waiting.sub-100ms-polling-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_sleep_below_100ms_is_still_flagged @test:tests/test_greenlint.py#test_detects_sub_100ms_polling_across_languages @test:tests/test_greenlint.py#test_detects_kotlin_short_delay @test:tests/test_greenlint.py#test_detects_swift_short_timer_interval
  Scenario Outline: A polling interval shorter than 100 ms is flagged across languages
    Given a project containing <file> with the line <code>
    When the developer scans the project
    Then greenlint reports GL002 "sub-100ms polling interval" with severity low on that line

    Examples:
      | file       | code                                                                        |
      | worker.py  | time.sleep(0.05)                                                            |
      | poll.sh    | sleep 0.05                                                                  |
      | poll.go    | time.Sleep(50 * time.Millisecond)                                           |
      | poll.rs    | thread::sleep(Duration::from_millis(50));                                   |
      | Poll.java  | Thread.sleep(50);                                                           |
      | poll.c     | usleep(50000);                                                              |
      | Poll.kt    | suspend fun bad() { while (true) { delay(50) } }                            |
      | Poll.swift | Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { _ in tick() } |
      | app.js     | setInterval(tick, 10)                                                       |

  @id:code-energy-rules.busy-waiting.005 @rule:code-rules.busy-waiting.intervals-of-100ms-or-more-allowed @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_sleep_of_exactly_100ms_is_not_flagged @test:tests/test_greenlint.py#test_normal_sleep_intervals_across_languages_not_flagged @test:tests/test_greenlint.py#test_kotlin_long_delay_not_flagged @test:tests/test_greenlint.py#test_swift_long_timer_interval_not_flagged
  Scenario Outline: Polling every 100 ms or slower is not flagged
    Given a project containing <file> with the line <code>
    When the developer scans the project
    Then greenlint does not report GL002

    Examples:
      | file       | code                                                                       |
      | worker.py  | time.sleep(0.1)                                                            |
      | poll.sh    | sleep 5                                                                    |
      | poll.go    | time.Sleep(5 * time.Second)                                                |
      | poll.rs    | thread::sleep(Duration::from_secs(5));                                     |
      | Poll.kt    | suspend fun good() { while (true) { delay(5000) } }                        |
      | Poll.swift | Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { _ in tick() } |

  @id:code-energy-rules.busy-waiting.007 @rule:code-rules.busy-waiting.clock-spin-wait-flagged @inferred @source:greenlint/rules.py#RULES
  Scenario Outline: A loop that only re-reads the clock until a deadline is flagged as a spin-wait
    Given a project containing <file> with a loop whose condition is <loop>
    And none of sleep, usleep, delay, setTimeout, yield, await, select, poll, recv or read appears within 240 characters after the clock read
    When the developer scans the project
    Then greenlint reports GL051 "spin-wait on a clock (busy loop until a deadline)" with severity high

    Examples:
      | file    | loop                                      |
      | wait.js | while (Date.now() < until) { /* burn */ } |
      | wait.py | while time.monotonic() < until:           |
      | wait.go | for time.Now().Before(deadline) {         |

  @id:code-energy-rules.busy-waiting.008 @rule:code-rules.busy-waiting.waiting-loop-or-single-clock-read-not-spin @inferred @source:greenlint/rules.py#RULES
  Scenario Outline: A deadline loop that sleeps, or a clock read outside a loop, is not a spin-wait
    Given a project containing <file> with <code>
    When the developer scans the project
    Then greenlint does not report GL051

    Examples:
      | file      | code                                                            |
      | poll.js   | while (Date.now() < until) { await sleep(100) }                 |
      | timing.js | const started = Date.now(); render(); log(Date.now() - started) |

  @id:code-energy-rules.busy-waiting.009 @rule:code-rules.busy-waiting.jsx-polling-not-checked @inferred @source:greenlint/rules.py#RULES @questionable
  Scenario: Fast setInterval polling in a JSX or TSX component is not flagged
    Given a project containing Ticker.tsx with the line setInterval(tick, 10)
    When the developer scans the project
    Then greenlint does not report GL002
