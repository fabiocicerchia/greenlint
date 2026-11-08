@domain:code-energy-rules @area:other-language-idioms @from:greenlint/rules
Feature: Flagging energy-costly idioms in C#, Kotlin, Swift, Ruby and JSX
  Developers outside Python get language-specific warnings about blocking threads, throwaway clients and extra passes over collections.

  @id:code-energy-rules.other-language-idioms.001 @rule:code-rules.other-languages.costly-idiom-flagged @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_detects_linq_count_zero_check @test:tests/test_greenlint.py#test_detects_ruby_hash_keys_include @test:tests/test_greenlint.py#test_detects_ruby_select_map_chain @test:tests/test_greenlint.py#test_detects_inline_jsx_prop_allocation
  Scenario Outline: Language-specific wasteful idioms are flagged
    Given a project containing <file> with <code>
    When the developer scans the project
    Then greenlint reports <rule> "<message>" with severity <severity>

    Examples:
      | file     | code                                                           | rule  | message                                                   | severity |
      | a.cs     | if (items.Count() == 0) { return; }                            | GL035 | LINQ .Count() used just to check emptiness                | low      |
      | a.cs     | var c = new HttpClient();                                      | GL039 | new HttpClient per call                                   | medium   |
      | a.cs     | var r = FetchAsync().Result;                                   | GL040 | blocking on a Task (.Result / .Wait())                    | medium   |
      | a.cs     | foreach (var x in items.Where(i => i.Ok).ToList()) { }         | GL041 | ToList() materialised just to iterate it once             | low      |
      | a.kt     | GlobalScope.launch { work() }                                  | GL042 | GlobalScope coroutine                                     | medium   |
      | a.kt     | val out = xs.filter { it.ok }.map { it.name }                  | GL043 | filter{}.map{} chain (two passes over the collection)     | low      |
      | a.kt     | runBlocking { fetch() }                                        | GL044 | runBlocking                                               | medium   |
      | a.swift  | let out = xs.filter { $0.ok }.map { $0.name }                  | GL045 | filter{}.map{} chain (two passes over the collection)     | low      |
      | a.swift  | DispatchQueue.main.sync { render() }                           | GL046 | DispatchQueue.sync                                        | medium   |
      | a.swift  | let s = URLSession(configuration: .default)                    | GL047 | a new URLSession per request                              | low      |
      | a.rb     | if h.keys.include?(k)                                          | GL036 | Hash membership check via keys/values.include?            | low      |
      | a.rb     | list.select(&:active?).map(&:name)                             | GL037 | select().map() chain (two passes over the collection)     | low      |
      | a.rb     | items.each do |i|\n  out += i.to_s                             | GL048 | string built with += inside a loop                        | medium   |
      | a.rb     | orders.each do |o|\n  o.customer = Customer.find_by(id: o.cid) | GL049 | query inside an each loop (N+1)                           | medium   |
      | a.rb     | rows.map { |r| r.tags }.flatten                                | GL050 | map().flatten() / map().compact() (an intermediate array) | low      |
      | Comp.jsx | <Foo onClick={() => doThing()} />                              | GL038 | inline function or object literal passed as a JSX prop    | low      |

  @id:code-energy-rules.other-language-idioms.002 @rule:code-rules.other-languages.recommended-fix-allowed @verified @source:greenlint/rules.py#RULES @test:tests/test_greenlint.py#test_linq_any_not_flagged @test:tests/test_greenlint.py#test_ruby_hash_key_predicate_not_flagged @test:tests/test_greenlint.py#test_ruby_filter_map_not_flagged @test:tests/test_greenlint.py#test_hoisted_jsx_prop_not_flagged
  Scenario Outline: The fix each language rule recommends is not itself flagged
    Given a project containing <file> with <code>
    When the developer scans the project
    Then greenlint does not report <rule>

    Examples:
      | file     | code                                                                 | rule  |
      | a.cs     | if (!items.Any()) { return; }                                        | GL035 |
      | a.cs     | private static readonly HttpClient Client = _factory.CreateClient(); | GL039 |
      | a.cs     | var r = await FetchAsync();                                          | GL040 |
      | a.cs     | var list = items.Where(i => i.Ok).ToList();                          | GL041 |
      | a.kt     | viewModelScope.launch { work() }                                     | GL042 |
      | a.kt     | val out = xs.mapNotNull { if (it.ok) it.name else null }             | GL043 |
      | a.kt     | suspend fun go() { fetch() }                                         | GL044 |
      | a.swift  | let out = xs.compactMap { $0.ok ? $0.name : nil }                    | GL045 |
      | a.swift  | DispatchQueue.main.async { render() }                                | GL046 |
      | a.swift  | let s = URLSession.shared                                            | GL047 |
      | a.rb     | if h.key?(k)                                                         | GL036 |
      | a.rb     | list.filter_map { |x| x.name if x.active? }                          | GL037 |
      | a.rb     | items.each do |i|\n  out << i.to_s                                   | GL048 |
      | a.rb     | Order.includes(:customer).each do |o|\n  puts o.customer.name        | GL049 |
      | a.rb     | rows.flat_map { |r| r.tags }                                         | GL050 |
      | Comp.jsx | <Foo onClick={handleClick} />                                        | GL038 |
