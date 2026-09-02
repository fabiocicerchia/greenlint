-- What ends up on the buffer as diagnostics.
--
-- Read back through vim.diagnostic.get rather than from anything the module
-- keeps: the published diagnostics are the product, and they are what a user
-- and an LSP-adjacent plugin actually see.

local config = require('greenlint.config')
local ui = require('greenlint.ui')

local function buffer(lines, name)
  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.api.nvim_buf_set_name(buf, name)
  vim.fn.bufload(buf)
  return buf
end

local function finding(over)
  return vim.tbl_extend('force', {
    rule = 'GL001',
    severity = 'medium',
    file = '/proj/a.py',
    line = 1,
    message = 'busy loop without sleep',
    suggestion = 'poll with a backoff',
  }, over or {})
end

local function published(buf)
  return vim.diagnostic.get(buf, { namespace = ui.namespace })
end

describe('render', function()
  it('traces the code, not the indentation', function()
    local path = '/tmp/greenlint-ui-spec-indent.py'
    local buf = buffer({ '    while True:', 'x = 1' }, path)
    ui.render(path, { finding({ line = 1 }) }, config.resolve())
    local got = published(buf)
    assert.equals(1, #got)
    assert.equals(0, got[1].lnum)
    assert.equals(4, got[1].col)
    assert.equals(15, got[1].end_col)
  end)

  it('starts at column zero on a line with nothing but whitespace', function()
    local path = '/tmp/greenlint-ui-spec-blank.py'
    local buf = buffer({ '   ', 'x = 1' }, path)
    ui.render(path, { finding({ line = 1 }) }, config.resolve())
    local got = published(buf)
    assert.equals(1, #got)
    assert.equals(0, got[1].col)
    assert.equals(3, got[1].end_col)
  end)

  it('carries the rule as the code and the suggestion in the message', function()
    local path = '/tmp/greenlint-ui-spec-message.py'
    local buf = buffer({ 'while True: pass' }, path)
    ui.render(path, { finding({ rule = 'GL005' }) }, config.resolve())
    local got = published(buf)
    assert.equals('GL005', got[1].code)
    assert.equals('greenlint', got[1].source)
    assert.equals('busy loop without sleep — poll with a backoff', got[1].message)
  end)

  it('drops a finding past the end of the buffer rather than clamping it', function()
    -- greenlint scanned the file on disk; the buffer may be shorter. A
    -- diagnostic on a line that is not there is worse than no diagnostic.
    local path = '/tmp/greenlint-ui-spec-past.py'
    local buf = buffer({ 'x = 1' }, path)
    ui.render(path, { finding({ line = 99 }) }, config.resolve())
    assert.equals(0, #published(buf))
  end)

  it('drops a severity the user mapped to false', function()
    local path = '/tmp/greenlint-ui-spec-off.py'
    local buf = buffer({ 'x = 1' }, path)
    local cfg = config.resolve({ diagnostics = { severity = { medium = false } } })
    ui.render(path, { finding({ severity = 'medium' }), finding({ severity = 'high' }) }, cfg)
    local got = published(buf)
    assert.equals(1, #got)
    assert.equals(vim.diagnostic.severity.WARN, got[1].severity)
  end)

  it('publishes nothing at all when diagnostics are turned off', function()
    local path = '/tmp/greenlint-ui-spec-disabled.py'
    local buf = buffer({ 'while True: pass' }, path)
    local cfg = config.resolve({ diagnostics = { enabled = false } })
    ui.render(path, { finding() }, cfg)
    assert.equals(0, #published(buf))
  end)

  it('publishes in severity order, worst first', function()
    local path = '/tmp/greenlint-ui-spec-order.py'
    local buf = buffer({ 'a', 'b', 'c' }, path)
    ui.render(path, {
      finding({ severity = 'low', line = 3, rule = 'GL-LOW' }),
      finding({ severity = 'high', line = 1, rule = 'GL-HIGH' }),
      finding({ severity = 'medium', line = 2, rule = 'GL-MED' }),
    }, config.resolve())
    local got = published(buf)
    assert.same({ 'GL-HIGH', 'GL-MED', 'GL-LOW' }, { got[1].code, got[2].code, got[3].code })
  end)

  it('clear removes what render published', function()
    local path = '/tmp/greenlint-ui-spec-clear.py'
    local buf = buffer({ 'while True: pass' }, path)
    ui.render(path, { finding() }, config.resolve())
    assert.equals(1, #published(buf))
    ui.clear(path)
    assert.equals(0, #published(buf))
  end)
end)

describe('quickfix', function()
  it('lists findings worst-first, with the rule and the suggestion on the line', function()
    ui.to_quickfix({
      finding({ severity = 'low', file = '/tmp/z.py', line = 4, rule = 'GL-LOW' }),
      finding({ severity = 'high', file = '/tmp/a.py', line = 2, rule = 'GL-HIGH' }),
    }, 'greenlint')
    local list = vim.fn.getqflist({ title = 1, items = 1 })
    assert.equals('greenlint', list.title)
    assert.equals(2, #list.items)
    assert.equals('W', list.items[1].type)
    assert.equals('I', list.items[2].type)
    assert.equals(2, list.items[1].lnum)
    assert.is_not_nil(list.items[1].text:find('[GL-HIGH]', 1, true))
    assert.is_not_nil(list.items[1].text:find('poll with a backoff', 1, true))
  end)

  it('never emits line zero, which quickfix reads as "no line"', function()
    ui.to_quickfix({ finding({ line = 0 }) }, 'greenlint')
    assert.equals(1, vim.fn.getqflist({ items = 1 }).items[1].lnum)
  end)
end)

describe('float', function()
  it('shows the lines it was given, unmodifiable, and closes on q', function()
    local buf, win = ui.float({ 'one', 'two' }, { title = ' t ', filetype = 'log' })
    assert.same({ 'one', 'two' }, vim.api.nvim_buf_get_lines(buf, 0, -1, false))
    assert.is_false(vim.bo[buf].modifiable)
    assert.equals('log', vim.bo[buf].filetype)
    vim.api.nvim_set_current_win(win)
    vim.api.nvim_feedkeys('q', 'x', false)
    assert.is_false(vim.api.nvim_win_is_valid(win))
  end)
end)
