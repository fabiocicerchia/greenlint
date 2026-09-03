-- What the editor events do, driven by firing them.
--
-- Same fake greenlint as init_spec: `cmd` is a shell that prints a canned JSON
-- document and ignores every flag the plugin appends. Assertions are on the
-- diagnostics that reach the buffer and on what the module returns, never on
-- the internals -- a trigger's product is a scan or a repaint, so that is what
-- is watched.

local greenlint = require('greenlint')
local ui = require('greenlint.ui')

local function fixture(findings)
  local file = vim.fn.tempname() .. '.json'
  vim.fn.writefile({ vim.json.encode(findings) }, file)
  return file
end

local function fake(findings)
  return { 'sh', '-c', 'cat ' .. vim.fn.shellescape(fixture(findings)) }
end

local function finding(file)
  return {
    rule = 'GL001',
    severity = 'medium',
    file = file,
    line = 1,
    message = 'busy loop without sleep',
    suggestion = 'poll with a backoff',
  }
end

--- A real file with a loaded buffer over it, so a repaint has somewhere to
--- land. Built rather than edited: `:edit` would fire BufReadPost itself, under
--- whatever config the previous test left behind.
local function open_buffer(lines)
  local path = vim.fn.tempname() .. '.py'
  vim.fn.writefile(lines, path)
  local buf = vim.api.nvim_create_buf(true, false)
  vim.api.nvim_buf_set_name(buf, path)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  return path, buf
end

local function setup(cmd, run)
  greenlint.setup({ cmd = cmd, run = run, scan_project_on_startup = false })
end

local function published(buf)
  return #vim.diagnostic.get(buf, { namespace = ui.namespace })
end

describe('a file coming into view', function()
  it('repaints what is already known rather than scanning again', function()
    local path, buf = open_buffer({ 'while True:', '    pass' })
    setup(fake({ finding(path) }), 'manual')
    local done = false
    greenlint.scan_file(path, {
      on_done = function()
        done = true
      end,
    })
    assert(vim.wait(10000, function()
      return done
    end, 10), 'the scan never called back')
    assert.equals(1, published(buf))

    -- Wipe the diagnostics and point cmd at a greenlint that reports nothing,
    -- with automatic scanning on: a repaint brings the finding back, a rescan
    -- would leave the buffer clean.
    vim.diagnostic.reset(ui.namespace, buf)
    assert.equals(0, published(buf))
    setup(fake({}), 'on_save')
    vim.api.nvim_exec_autocmds('BufReadPost', { pattern = path })
    assert(
      vim.wait(2000, function()
        return published(buf) > 0
      end, 10),
      'the known finding was never repainted'
    )
  end)

  it('scans a file nothing is known about', function()
    local path, buf = open_buffer({ 'while True:', '    pass' })
    setup(fake({ finding(path) }), 'on_save')
    assert.same({}, greenlint.findings_for(path))
    vim.api.nvim_exec_autocmds('BufReadPost', { pattern = path })
    assert(
      vim.wait(10000, function()
        return #greenlint.findings_for(path) > 0
      end, 10),
      'the file was never scanned'
    )
    assert.equals(1, published(buf))
  end)

  it('leaves an unknown file alone when scanning is manual', function()
    local path = select(1, open_buffer({ 'while True:', '    pass' }))
    setup(fake({ finding(path) }), 'manual')
    vim.api.nvim_exec_autocmds('BufReadPost', { pattern = path })
    vim.wait(300, function()
      return #greenlint.findings_for(path) > 0
    end, 10)
    assert.same({}, greenlint.findings_for(path))
  end)
end)

describe('cancel', function()
  it('stops a debounced on-type scan that has not started', function()
    local _, buf = open_buffer({ 'while True:', '    pass' })
    greenlint.setup({
      cmd = fake({}),
      run = 'on_type',
      debounce_ms = 60000,
      scan_project_on_startup = false,
    })
    vim.api.nvim_exec_autocmds('TextChanged', { buffer = buf })

    local said
    local real = vim.notify
    vim.notify = function(message)
      said = message
    end
    greenlint.cancel()
    vim.notify = real
    assert.equals('greenlint: stopped 1 scan(s).', said)
  end)

  it('says nothing is running when no scan is waiting', function()
    setup(fake({}), 'manual')
    local said
    local real = vim.notify
    vim.notify = function(message)
      said = message
    end
    greenlint.cancel()
    vim.notify = real
    assert.equals('greenlint: nothing running.', said)
  end)
end)
