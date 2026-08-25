local config = require('greenlint.config')

describe('defaults', function()
  it('resolves without options', function()
    local cfg = config.resolve()
    assert.same({ 'greenlint' }, cfg.cmd)
    assert.equals('on_save', cfg.run)
    assert.equals('file', cfg.grouping)
  end)

  it('scans on save by default, not on every keystroke', function()
    -- on_type is available and cheap, but writing the buffer to a temp file per
    -- keystroke is a choice to make deliberately.
    assert.equals('on_save', config.resolve().run)
  end)
end)

describe('merging', function()
  it('keeps siblings when one nested key is set', function()
    local cfg = config.resolve({ diagnostics = { enabled = false } })
    assert.is_false(cfg.diagnostics.enabled)
    assert.equals(vim.diagnostic.severity.WARN, cfg.diagnostics.severity.high)
  end)

  it('replaces a list wholesale', function()
    assert.same({ '*/vendor/*' }, config.resolve({ exclude = { '*/vendor/*' } }).exclude)
  end)

  it('lets a severity be silenced', function()
    local cfg = config.resolve({ diagnostics = { severity = { low = false } } })
    assert.is_false(cfg.diagnostics.severity.low)
  end)
end)

describe('validation', function()
  local function fails(opts)
    local ok, err = pcall(config.resolve, opts)
    assert.is_false(ok, 'expected this to be rejected')
    return tostring(err)
  end

  it('rejects an empty cmd', function()
    assert.is_truthy(fails({ cmd = {} }):match('cmd'))
  end)

  it('rejects a run mode it does not have', function()
    assert.is_truthy(fails({ run = 'onType' }):match('run'), 'the VS Code spelling is not this one')
  end)

  it('rejects a debounce short enough to scan per keystroke', function()
    assert.is_truthy(fails({ debounce_ms = 5 }):match('debounce_ms'))
  end)

  it('rejects a grouping the report cannot do', function()
    assert.is_truthy(fails({ grouping = 'ecosystem' }):match('grouping'))
  end)

  it('rejects a file cap below a kilobyte', function()
    assert.is_truthy(fails({ max_file_bytes = 10 }):match('max_file_bytes'))
  end)

  it('accepts a checkout, which is the awkward shape', function()
    assert.has_no.errors(function()
      config.resolve({ cmd = { 'python3', '/p/greenlint.py' }, run = 'on_type', debounce_ms = 250 })
    end)
  end)
end)
