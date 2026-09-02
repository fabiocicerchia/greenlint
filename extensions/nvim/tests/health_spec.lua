-- :checkhealth greenlint, asserted on what it reports.
--
-- vim.health is stubbed so the report becomes a list this can read: the health
-- check's product is the entries it emits, and there is no other way to get at
-- them without parsing a floating window.

local greenlint = require('greenlint')

local function with_health(fn)
  local entries = {}
  local real = vim.health
  local function record(kind)
    return function(message, advice)
      entries[#entries + 1] = { kind = kind, message = tostring(message), advice = advice }
    end
  end
  vim.health = {
    start = record('start'),
    ok = record('ok'),
    warn = record('warn'),
    error = record('error'),
    info = record('info'),
  }
  local ok, err = pcall(fn, entries)
  vim.health = real
  assert(ok, err)
  return entries
end

--- The first entry whose message contains `needle`, or nil.
local function find(entries, needle)
  for _, entry in ipairs(entries) do
    if entry.message:find(needle, 1, true) then
      return entry
    end
  end
  return nil
end

local function check_with(cmd)
  greenlint.setup({ cmd = cmd, run = 'manual', scan_project_on_startup = false })
  return with_health(function()
    require('greenlint.health').check()
  end)
end

describe('checkhealth', function()
  it('opens a report section', function()
    local entries = check_with({ 'sh', '-c', 'printf "GL001 a\\nGL002 b\\n"' })
    assert.equals('start', entries[1].kind)
    assert.equals('greenlint', entries[1].message)
  end)

  it('counts the rules the command reports, first line included', function()
    -- Two rules: one on the first line (no leading newline to match on) and one
    -- after it. Getting the first line wrong is an off-by-one nobody would see.
    local entries = check_with({ 'sh', '-c', 'printf "GL001 a\\nGL002 b\\n"' })
    local entry = find(entries, 'rules')
    assert.is_not_nil(entry)
    assert.equals('ok', entry.kind)
    assert.is_not_nil(entry.message:find('2 rules', 1, true))
  end)

  it('errors, with the install advice, when the command is not executable', function()
    local entries = check_with({ 'greenlint-does-not-exist-9c1f' })
    local entry = find(entries, 'is not executable')
    assert.is_not_nil(entry)
    assert.equals('error', entry.kind)
    assert.is_not_nil(entry.advice)
    assert.is_not_nil(table.concat(entry.advice, '\n'):find('setup', 1, true))
  end)

  it('errors with the exit code when the command runs and fails', function()
    local entries = check_with({ 'sh', '-c', 'echo boom >&2; exit 3' })
    local entry = find(entries, 'exited 3')
    assert.is_not_nil(entry)
    assert.equals('error', entry.kind)
  end)

  it('warns when the command runs but is not greenlint', function()
    local entries = check_with({ 'sh', '-c', 'echo hello' })
    local entry = find(entries, 'does not look like greenlint')
    assert.is_not_nil(entry)
    assert.equals('warn', entry.kind)
  end)

  it('reports the project root it will scan', function()
    local entries = check_with({ 'sh', '-c', 'echo hello' })
    local entry = find(entries, 'project root: ')
    assert.is_not_nil(entry)
    assert.equals('info', entry.kind)
    assert.is_not_nil(entry.message:find(greenlint.root(), 1, true))
  end)

  it('explains the temp-file cost of on_type only when on_type is set', function()
    greenlint.setup({ cmd = { 'sh', '-c', 'echo hello' }, run = 'manual', scan_project_on_startup = false })
    local quiet = with_health(function()
      require('greenlint.health').check()
    end)
    assert.is_nil(find(quiet, 'run = "on_type"'))

    greenlint.setup({
      cmd = { 'sh', '-c', 'echo hello' },
      run = 'on_type',
      scan_project_on_startup = false,
    })
    local loud = with_health(function()
      require('greenlint.health').check()
    end)
    assert.is_not_nil(find(loud, 'run = "on_type"'))
  end)
end)
