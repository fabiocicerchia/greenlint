local core = require('greenlint.core')

local function finding(over)
  return vim.tbl_extend('force', {
    rule = 'GL005',
    severity = 'medium',
    file = '/p/src/db.py',
    line = 10,
    message = 'SELECT * query',
    suggestion = 'name the columns you need',
    co2e_estimate = '~15 gCO2e per GB of columns never read',
  }, over or {})
end

describe('the command line', function()
  local cfg = require('greenlint.config').resolve({})

  it('always asks for JSON', function()
    local argv = core.scan_argv(cfg, { '/p/a.py' }, {})
    assert.same({ '--format', 'json', '/p/a.py' }, argv)
  end)

  it('passes the project config and baseline when they exist', function()
    local argv = core.scan_argv(cfg, { '/p' }, { config = '/p/.greenlint.toml', baseline = '/p/.greenlint-baseline.json' })
    assert.is_true(vim.tbl_contains(argv, '--config'))
    assert.is_true(vim.tbl_contains(argv, '/p/.greenlint.toml'))
    assert.is_true(vim.tbl_contains(argv, '--baseline'))
  end)

  it('repeats --exclude rather than joining, since a glob may contain a comma', function()
    local with = require('greenlint.config').resolve({ exclude = { '*/vendor/*', '*/dist/*' } })
    local argv = core.scan_argv(with, { '/p' }, {})
    local count = 0
    for _, arg in ipairs(argv) do
      if arg == '--exclude' then
        count = count + 1
      end
    end
    assert.equals(2, count)
  end)

  it('puts paths last, after every flag', function()
    local argv = core.scan_argv(cfg, { '/p/a.py' }, { config = '/p/.greenlint.toml' })
    assert.equals('/p/a.py', argv[#argv])
  end)

  it('drops --format when writing a baseline, which does not produce findings', function()
    local argv = core.write_baseline_argv(cfg, { '/p' }, '/p/.greenlint-baseline.json')
    assert.is_false(vim.tbl_contains(argv, '--format'))
    assert.is_false(vim.tbl_contains(argv, 'json'))
    assert.equals('--write-baseline', argv[1])
    assert.equals('/p/.greenlint-baseline.json', argv[2])
  end)
end)

describe('reading the output', function()
  it('accepts an empty result, which is the happy answer', function()
    assert.is_true(core.is_findings({}))
  end)

  it('rejects anything that is not a list of findings', function()
    assert.is_false(core.is_findings(nil))
    assert.is_false(core.is_findings('[]'))
    assert.is_false(core.is_findings({ { rule = 'GL001' } }), 'no file')
    assert.is_false(core.is_findings({ { file = 'a.py' } }), 'no rule')
  end)

  it('accepts what greenlint actually prints', function()
    assert.is_true(core.is_findings({ finding() }))
  end)
end)

describe('ordering', function()
  it('is severity, then file, then line', function()
    local sorted = core.sorted({
      finding({ severity = 'low', file = 'a.py', line = 1 }),
      finding({ severity = 'high', file = 'b.py', line = 9 }),
      finding({ severity = 'medium', file = 'a.py', line = 5 }),
      finding({ severity = 'high', file = 'a.py', line = 2 }),
    })
    assert.same(
      { 'a.py:2', 'b.py:9', 'a.py:5', 'a.py:1' },
      vim.tbl_map(function(f)
        return f.file .. ':' .. f.line
      end, sorted)
    )
  end)

  it('sorts a severity it does not know last, rather than at random', function()
    local sorted = core.sorted({
      finding({ severity = 'nonsense', file = 'a.py' }),
      finding({ severity = 'low', file = 'a.py' }),
    })
    assert.equals('low', sorted[1].severity)
  end)

  it('does not mutate what it was given', function()
    local input = { finding({ severity = 'low' }), finding({ severity = 'high' }) }
    core.sorted(input)
    assert.equals('low', input[1].severity)
  end)
end)

describe('counting', function()
  it('counts each severity', function()
    local counts = core.count_by_severity({
      finding({ severity = 'high' }),
      finding({ severity = 'high' }),
      finding({ severity = 'low' }),
    })
    assert.same({ high = 2, medium = 0, low = 1 }, counts)
  end)
end)

describe('saying why', function()
  it('puts the suggestion on the diagnostic, because it is the point', function()
    assert.equals('SELECT * query — name the columns you need', core.summarise(finding()))
  end)

  it('builds the anchor the rules reference actually uses', function()
    -- The headings are `## GL001 — busy loop without sleep`, and GitHub's slug
    -- rules leave the doubled hyphen where the em dash was.
    assert.equals(
      'https://github.com/fabiocicerchia/greenlint/blob/main/docs/rules.md#gl001--busy-loop-without-sleep',
      core.docs_url({ rule = 'GL001', message = 'busy loop without sleep' })
    )
  end)

  it('drops punctuation from an anchor the way GitHub does', function()
    local url = core.docs_url({ rule = 'GL018', message = 'nested loop (possible O(n²) pattern)' })
    assert.is_falsy(url:find('%('))
    assert.is_falsy(url:find('²'), 'non-ascii is dropped, as GitHub drops it')
  end)

  it('shows the cost as prose, not as a number', function()
    -- The CO2e hints describe different physical quantities, so a single
    -- summed figure would have no unit and a false air of precision.
    local lines = table.concat(core.hover_lines(finding()), '\n')
    assert.is_truthy(lines:find('~15 gCO2e per GB', 1, true))
    assert.is_truthy(lines:find('Do instead', 1, true))
    assert.is_truthy(lines:find('rules.md#gl005', 1, true))
  end)

  it('leaves the cost line out when a rule has none', function()
    local lines = table.concat(core.hover_lines(finding({ co2e_estimate = '' })), '\n')
    assert.is_falsy(lines:find('Rough cost'))
  end)
end)

describe('the report', function()
  local findings = {
    finding({ severity = 'high', file = '/p/a.py', rule = 'GL001', message = 'busy loop' }),
    finding({ severity = 'low', file = '/p/b.sql', rule = 'GL005', message = 'SELECT *' }),
    finding({ severity = 'high', file = '/p/b.sql', rule = 'GL001', message = 'busy loop' }),
  }
  local rel = function(path)
    return (path:gsub('^/p/', ''))
  end

  it('leads with the totals', function()
    local lines = core.report_lines(findings, 'file', rel)
    assert.is_truthy(lines[1]:find('3 finding(s)', 1, true))
    assert.is_truthy(lines[1]:find('2 high', 1, true))
  end)

  it('groups by file', function()
    local text = table.concat(core.report_lines(findings, 'file', rel), '\n')
    assert.is_truthy(text:find('a.py  (1)', 1, true))
    assert.is_truthy(text:find('b.sql  (2)', 1, true))
  end)

  it('groups by rule', function()
    local text = table.concat(core.report_lines(findings, 'rule', rel), '\n')
    assert.is_truthy(text:find('GL001 — busy loop  (2)', 1, true))
  end)

  it('groups by severity, worst first', function()
    local lines = core.report_lines(findings, 'severity', rel)
    local high, low
    for i, line in ipairs(lines) do
      if line:find('^high') then
        high = i
      elseif line:find('^low') then
        low = i
      end
    end
    assert.is_true(high < low)
  end)

  it('says so when there is nothing', function()
    local text = table.concat(core.report_lines({}, 'file', rel), '\n')
    assert.is_truthy(text:find('Nothing wasteful found', 1, true))
  end)
end)
