-- The user-facing commands, driven against a fake greenlint.
--
-- Each one's product is a window, a quickfix list or a message, so that is what
-- is asserted: the float's lines, the quickfix items, what vim.notify was told.
-- vim.ui.select is captured so the choices offered can be checked without one
-- being made, and made without a prompt when the point is what follows.

local greenlint = require('greenlint')

local root = greenlint.root()

local function fake(findings)
  local file = vim.fn.tempname() .. '.json'
  vim.fn.writefile({ vim.json.encode(findings) }, file)
  return { 'sh', '-c', 'cat ' .. vim.fn.shellescape(file) }
end

local function finding(over)
  return vim.tbl_extend('force', {
    rule = 'GL001',
    severity = 'medium',
    file = root .. '/a.py',
    line = 1,
    message = 'busy loop without sleep',
    suggestion = 'poll with a backoff',
  }, over or {})
end

local function setup(findings)
  greenlint.setup({ cmd = fake(findings), run = 'manual', scan_project_on_startup = false })
end

--- setup, then walk the project once so what follows starts from these
--- findings and not from the previous example's. Also empties the quickfix
--- list, which the editor keeps between examples.
local function scanned(findings)
  setup(findings)
  local done = false
  greenlint.scan_project({
    on_done = function()
      done = true
    end,
  })
  assert(vim.wait(10000, function()
    return done
  end, 10), 'the project scan never called back')
  vim.fn.setqflist({}, 'r')
end

--- Run `fn`, then wait for a window whose buffer has `filetype`, and return its
--- lines. Commands scan first when nothing is known yet, so this has to wait.
local function float_lines(filetype, fn)
  fn()
  local buf
  assert(vim.wait(10000, function()
    for _, win in ipairs(vim.api.nvim_list_wins()) do
      local candidate = vim.api.nvim_win_get_buf(win)
      if vim.bo[candidate].filetype == filetype then
        buf = candidate
        return true
      end
    end
    return false
  end, 10), 'no ' .. filetype .. ' window opened')
  local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
  vim.cmd('silent! close')
  return lines
end

--- Run `fn` with vim.notify captured; returns what it was told, and whether a
--- menu was put on screen. vim.ui.select is stubbed too because the real one
--- waits for an answer nobody is there to give.
local function messages(fn)
  local said, prompted = {}, false
  local real_notify, real_select = vim.notify, vim.ui.select
  vim.notify = function(message)
    said[#said + 1] = message
  end
  vim.ui.select = function(_items, _opts, on_choice)
    prompted = true
    on_choice(nil)
  end
  fn()
  vim.wait(2000, function()
    return #said > 0 or prompted
  end, 10)
  vim.notify, vim.ui.select = real_notify, real_select
  return said, prompted
end

--- Run `fn` with vim.ui.select captured; `choose` picks from what is offered.
local function selection(fn, choose)
  local offered, formatted = nil, {}
  local real = vim.ui.select
  vim.ui.select = function(items, opts, on_choice)
    offered = items
    for _, item in ipairs(items) do
      formatted[#formatted + 1] = opts.format_item and opts.format_item(item) or tostring(item)
    end
    on_choice(choose and choose(items) or nil)
  end
  fn()
  vim.wait(2000, function()
    return offered ~= nil
  end, 10)
  vim.ui.select = real
  return offered or {}, formatted
end

describe('report', function()
  -- First, deliberately: nothing has been scanned in this session yet, which
  -- is the state this example is about.
  it('scans the project first when nothing is known yet', function()
    setup({ finding() })
    local lines = float_lines('greenlint-report', function()
      greenlint.report()
    end)
    assert.equals('1 finding(s) — 0 high · 1 medium · 0 low', lines[1])
  end)

  it('opens a float that leads with the totals', function()
    scanned({ finding({ severity = 'high' }), finding({ file = root .. '/b.py' }) })
    local lines = float_lines('greenlint-report', function()
      greenlint.report()
    end)
    assert.equals('2 finding(s) — 1 high · 1 medium · 0 low', lines[1])
  end)

  it('says so when there is nothing to report', function()
    scanned({})
    local lines = float_lines('greenlint-report', function()
      greenlint.report()
    end)
    assert.is_true(vim.tbl_contains(lines, 'Nothing wasteful found.'))
  end)
end)

describe('list', function()
  it('fills the quickfix list with every finding, worst first', function()
    scanned({
      finding({ file = root .. '/z.py', severity = 'low', rule = 'GL-LOW' }),
      finding({ file = root .. '/a.py', severity = 'high', rule = 'GL-HIGH' }),
    })
    greenlint.list()
    assert(vim.wait(10000, function()
      return #vim.fn.getqflist() == 2
    end, 10), 'the quickfix list never filled')
    local list = vim.fn.getqflist({ title = 1, items = 1 })
    assert.equals('greenlint', list.title)
    assert.is_not_nil(list.items[1].text:find('[GL-HIGH]', 1, true))
    vim.cmd('cclose')
  end)

  it('says so, and opens nothing, when there is nothing to list', function()
    scanned({})
    assert.same({ 'greenlint: nothing wasteful found.' }, messages(function()
      greenlint.list()
    end))
  end)
end)

describe('filter', function()
  it('offers only the severities that were actually found, with their counts', function()
    scanned({
      finding({ file = root .. '/a.py', severity = 'high' }),
      finding({ file = root .. '/b.py', severity = 'low' }),
      finding({ file = root .. '/c.py', severity = 'low' }),
    })
    local offered, formatted = selection(function()
      greenlint.filter()
    end)
    assert.same({ 'high', 'low' }, offered)
    assert.same({ 'high    1', 'low     2' }, formatted)
  end)

  it('lists only the chosen severity', function()
    scanned({
      finding({ file = root .. '/a.py', severity = 'high' }),
      finding({ file = root .. '/b.py', severity = 'low' }),
    })
    selection(function()
      greenlint.filter()
    end, function()
      return 'low'
    end)
    assert(vim.wait(10000, function()
      return #vim.fn.getqflist() == 1
    end, 10), 'the quickfix list never filled')
    local list = vim.fn.getqflist({ title = 1, items = 1 })
    assert.equals('greenlint: low', list.title)
    assert.is_not_nil(list.items[1].text:find('GL001', 1, true))
    vim.cmd('cclose')
  end)

  it('says so, without an empty menu, when there is nothing to filter', function()
    scanned({})
    local said, prompted = messages(function()
      greenlint.filter()
    end)
    assert.same({ 'greenlint: nothing wasteful found.' }, said)
    assert.is_false(prompted)
  end)
end)

describe('grouping', function()
  it('offers the three groupings with a blurb each', function()
    scanned({ finding() })
    local offered, formatted = selection(function()
      greenlint.set_grouping()
    end)
    assert.same({ 'file', 'severity', 'rule' }, offered)
    assert.same({
      'file      one group per file',
      'severity  high, then medium, then low',
      'rule      one group per rule',
    }, formatted)
  end)

  it('regroups the report by what was chosen', function()
    scanned({ finding({ file = root .. '/a.py', rule = 'GL001' }) })
    local lines
    selection(function()
      lines = float_lines('greenlint-report', function()
        greenlint.set_grouping()
      end)
    end, function()
      return 'rule'
    end)
    assert.is_true(vim.tbl_contains(lines, 'GL001 — busy loop without sleep  (1)'))
  end)
end)

describe('hover', function()
  it('says so when the cursor is not on a finding', function()
    scanned({ finding({ line = 5 }) })
    local buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_name(buf, root .. '/a.py')
    vim.api.nvim_buf_set_lines(buf, 0, -1, false, { 'x = 1' })
    vim.api.nvim_set_current_buf(buf)
    assert.same({ 'greenlint: no finding on this line.' }, messages(function()
      greenlint.hover()
    end))
  end)
end)

describe('show_log', function()
  it('opens a float of the log, one timestamped line per event', function()
    scanned({})
    local lines = float_lines('log', function()
      greenlint.show_log()
    end)
    assert.same(lines, greenlint.log_text())
    for _, line in ipairs(lines) do
      assert.is_not_nil(line:match('^%[%d%d:%d%d:%d%d%] '), line)
    end
  end)

  it('shows the run it logged once something has been scanned', function()
    scanned({ finding() })
    local done = false
    greenlint.scan_file(root .. '/a.py', {
      on_done = function()
        done = true
      end,
    })
    assert(vim.wait(10000, function()
      return done
    end, 10))
    local lines = float_lines('log', function()
      greenlint.show_log()
    end)
    assert.is_not_nil(table.concat(lines, '\n'):find('run: sh -c', 1, true))
  end)
end)

describe('baseline', function()
  it('runs nothing at all unless the write is confirmed', function()
    -- Headless has no one to ask, so confirm() answers 0 -- not the "write"
    -- choice. On that answer greenlint must not be invoked, which the log is
    -- the evidence for: it records every command before it is spawned.
    scanned({ finding() })
    local before = #greenlint.log_text()
    greenlint.write_baseline()
    vim.wait(500, function()
      return #greenlint.log_text() > before
    end, 10)
    assert.equals(before, #greenlint.log_text())
  end)

  it('says so when there is no baseline to clear', function()
    scanned({})
    if vim.uv.fs_stat(vim.fs.joinpath(root, '.greenlint-baseline.json')) then
      return
    end
    assert.same({ 'greenlint: no baseline to clear.' }, messages(function()
      greenlint.clear_baseline()
    end))
  end)
end)
