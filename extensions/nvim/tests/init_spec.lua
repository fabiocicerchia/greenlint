-- The public API, driven against a fake greenlint.
--
-- `cmd` is a shell that prints a canned JSON document and ignores every flag
-- the plugin appends, so the whole round trip -- argv, spawn, decode, store,
-- render -- runs without greenlint being installed. Assertions are on what the
-- module returns (findings_for, counts, statusline) and on the diagnostics that
-- reach the buffer, never on the internals.

local greenlint = require('greenlint')
local ui = require('greenlint.ui')

local root = greenlint.root()

local function fixture(findings)
  local file = vim.fn.tempname() .. '.json'
  vim.fn.writefile({ vim.json.encode(findings) }, file)
  return file
end

--- A cmd that prints `findings` as greenlint would. `sh -c SCRIPT name args...`
--- puts everything the plugin appends into $0/$1..., where the script ignores it.
local function fake(findings)
  return { 'sh', '-c', 'cat ' .. vim.fn.shellescape(fixture(findings)) }
end

local function broken(script)
  return { 'sh', '-c', script }
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

local function setup(cmd, extra)
  greenlint.setup(vim.tbl_extend('force', {
    cmd = cmd,
    run = 'manual',
    scan_project_on_startup = false,
  }, extra or {}))
end

--- Run `start` to completion with vim.notify captured; returns what it said.
local function notified(start)
  local said
  local real = vim.notify
  vim.notify = function(message)
    said = message
  end
  local done = false
  start(function()
    done = true
  end)
  assert(vim.wait(10000, function()
    return done
  end, 10), 'the scan never called back')
  vim.notify = real
  return said
end

--- Run `start` and block until its on_done fires. Returns what it was passed.
local function await(start)
  local outcome, done = nil, false
  start(function(ok)
    outcome, done = ok, true
  end)
  assert(vim.wait(10000, function()
    return done
  end, 10), 'the scan never called back')
  return outcome
end

describe('scan_file', function()
  it('stores what greenlint reported for the file it scanned', function()
    setup(fake({ finding({ line = 3 }), finding({ severity = 'high', line = 9 }) }))
    local path = root .. '/a.py'
    assert.is_true(await(function(done)
      greenlint.scan_file(path, { on_done = done })
    end))
    local found = greenlint.findings_for(path)
    assert.equals(2, #found)
    assert.equals('GL001', found[1].rule)
  end)

  it('drops the entry entirely when a rescan finds nothing', function()
    setup(fake({ finding() }))
    local path = root .. '/b.py'
    await(function(done)
      greenlint.scan_file(path, { on_done = done })
    end)
    assert.equals(1, #greenlint.findings_for(path))

    setup(fake({}))
    await(function(done)
      greenlint.scan_file(path, { on_done = done })
    end)
    assert.same({}, greenlint.findings_for(path))
  end)

  it('reports failure, and keeps nothing, when the output is not JSON', function()
    setup(broken('echo not-json'))
    local path = root .. '/c.py'
    assert.is_false(await(function(done)
      greenlint.scan_file(path, { on_done = done })
    end))
    assert.same({}, greenlint.findings_for(path))
  end)

  it('rejects valid JSON that is not a list of findings', function()
    -- The likeliest way to get here is `cmd` pointing at some other tool, so
    -- the message names that rather than talking about JSON.
    setup(broken([[echo '[{"hello": 1}]']]))
    assert.equals('greenlint: unexpected output — is `cmd` pointing at greenlint?', notified(function(done)
      greenlint.scan_file(root .. '/c2.py', { on_done = done, notify = true })
    end))
  end)

  it('passes the command\'s own stderr on when it produces no output', function()
    setup(broken('echo boom >&2; exit 1'))
    assert.equals('greenlint: boom', notified(function(done)
      greenlint.scan_file(root .. '/d.py', { on_done = done, notify = true })
    end))
  end)

  it('skips a file over the byte cap without running greenlint', function()
    local big = vim.fn.tempname()
    vim.fn.writefile({ string.rep('x', 4096) }, big)
    -- A cmd that would fail loudly if it ran: the assertion is that it does not.
    setup(broken('exit 7'), { max_file_bytes = 1024 })
    assert.is_true(await(function(done)
      greenlint.scan_file(big, { on_done = done })
    end))
  end)

  it('does nothing at all when the plugin is disabled', function()
    setup(fake({ finding() }))
    local path = root .. '/e.py'
    await(function(done)
      greenlint.scan_file(path, { on_done = done })
    end)
    assert.equals(1, #greenlint.findings_for(path))

    greenlint.setup({ enabled = false })
    local called = false
    greenlint.scan_file(path, {
      on_done = function()
        called = true
      end,
    })
    vim.wait(200, function()
      return called
    end, 10)
    assert.is_false(called)
  end)
end)

describe('scan_project', function()
  it('groups findings by file and drops what the walk no longer reports', function()
    setup(fake({
      finding({ file = root .. '/one.py', line = 1 }),
      finding({ file = root .. '/one.py', line = 2 }),
      finding({ file = root .. '/two.py', severity = 'high' }),
    }))
    assert.is_true(await(function(done)
      greenlint.scan_project({ on_done = done })
    end))
    assert.equals(2, #greenlint.findings_for(root .. '/one.py'))
    assert.equals(1, #greenlint.findings_for(root .. '/two.py'))

    -- A whole-project scan is the whole truth for the tree it walked.
    setup(fake({ finding({ file = root .. '/two.py', severity = 'high' }) }))
    await(function(done)
      greenlint.scan_project({ on_done = done })
    end)
    assert.same({}, greenlint.findings_for(root .. '/one.py'))
    assert.equals(1, #greenlint.findings_for(root .. '/two.py'))
  end)

  it('counts every severity across the project', function()
    setup(fake({
      finding({ file = root .. '/one.py', severity = 'high' }),
      finding({ file = root .. '/one.py', severity = 'low' }),
      finding({ file = root .. '/two.py', severity = 'high' }),
    }))
    await(function(done)
      greenlint.scan_project({ on_done = done })
    end)
    assert.same({ high = 2, medium = 0, low = 1 }, greenlint.counts())
    assert.equals(3, #greenlint.findings())
  end)

  it('reports failure without disturbing what is already known', function()
    setup(fake({ finding({ file = root .. '/one.py' }) }))
    await(function(done)
      greenlint.scan_project({ on_done = done })
    end)
    setup(broken('echo not-json'))
    assert.is_false(await(function(done)
      greenlint.scan_project({ on_done = done })
    end))
    assert.equals(1, #greenlint.findings_for(root .. '/one.py'))
  end)
end)

describe('scan_buffer', function()
  it('maps findings from the temp file back onto the buffer\'s own path', function()
    local path = root .. '/buffered.py'
    local buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_name(buf, path)
    vim.api.nvim_buf_set_lines(buf, 0, -1, false, { 'while True:', '    pass' })
    vim.fn.bufload(buf)
    -- greenlint would name the temp file it was handed, not the real path.
    setup(fake({ finding({ file = '/tmp/whatever/buffered.py', line = 1 }) }))
    assert.is_true(await(function(done)
      greenlint.scan_buffer(buf, { on_done = done })
    end))
    local found = greenlint.findings_for(path)
    assert.equals(1, #found)
    assert.equals(path, found[1].file)
    assert.equals(1, #vim.diagnostic.get(buf, { namespace = ui.namespace }))
  end)

  it('does nothing for a buffer with no name', function()
    setup(fake({ finding() }))
    local buf = vim.api.nvim_create_buf(false, true)
    local called = false
    greenlint.scan_buffer(buf, {
      on_done = function()
        called = true
      end,
    })
    vim.wait(200, function()
      return called
    end, 10)
    assert.is_false(called)
  end)
end)

describe('statusline', function()
  it('is empty before setup and when nothing was found', function()
    setup(fake({}))
    await(function(done)
      greenlint.scan_project({ on_done = done })
    end)
    assert.equals('', greenlint.statusline())
  end)

  it('shows high/medium/low once there is something to show', function()
    setup(fake({
      finding({ file = root .. '/one.py', severity = 'high' }),
      finding({ file = root .. '/one.py', severity = 'medium' }),
      finding({ file = root .. '/two.py', severity = 'low' }),
    }))
    await(function(done)
      greenlint.scan_project({ on_done = done })
    end)
    assert.is_not_nil(greenlint.statusline():find('1/1/1', 1, true))
  end)
end)

describe('setup', function()
  it('attaches one autocmd group covering save, read and both type events', function()
    setup(fake({}))
    local events = {}
    for _, autocmd in ipairs(vim.api.nvim_get_autocmds({ group = 'greenlint' })) do
      events[autocmd.event] = true
    end
    assert.is_true(events.BufWritePost)
    assert.is_true(events.BufReadPost)
    assert.is_true(events.BufEnter)
    assert.is_true(events.TextChanged)
    assert.is_true(events.TextChangedI)
  end)

  it('leaves the autocmds it already attached inert once disabled', function()
    -- Re-setup does not tear the group down, so the guard has to be inside the
    -- callback. A cmd that would report a finding proves it never ran.
    local path = root .. '/inert.py'
    setup(fake({ finding({ file = path }) }))
    greenlint.setup({ enabled = false })
    vim.api.nvim_exec_autocmds('BufWritePost', { pattern = path })
    vim.wait(300, function()
      return #greenlint.findings_for(path) > 0
    end, 10)
    assert.same({}, greenlint.findings_for(path))
  end)

  it('reports whether it has run', function()
    setup(fake({}))
    assert.is_true(greenlint.is_setup())
    assert.equals('manual', greenlint.config().run)
  end)
end)

describe('cancel', function()
  it('says so when there is nothing to stop', function()
    setup(fake({}))
    local said
    local real = vim.notify
    vim.notify = function(msg)
      said = msg
    end
    greenlint.cancel()
    vim.notify = real
    assert.equals('greenlint: nothing running.', said)
  end)
end)
