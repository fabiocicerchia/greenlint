-- setup(), the public API, and when a scan happens.
--
-- greenlint is cheap -- about 60ms for one file and 120ms for a whole small
-- repository, interpreter start included -- which is why this can afford to
-- scan on save, and even on a debounced keystroke, by running the CLI rather
-- than keeping a server alive.

local commands = require('greenlint.commands')
local config = require('greenlint.config')
local core = require('greenlint.core')
local log = require('greenlint.log')
local ui = require('greenlint.ui')

local M = {}

local cfg = nil
--- absolute path -> findings
local by_file = {}
--- Scans in flight, so `:GreenlintCancel` has something to stop. A killed scan
--- has no answer to give, so its entry carries the flag that keeps its callback
--- quiet rather than letting it report the kill as a failure.
local jobs = {}
local timers = {}

local log_line = log.add
local notify = ui.notify

function M.is_setup()
  return cfg ~= nil
end

function M.config()
  return cfg
end

function M.log_text()
  return log.lines()
end

function M.root()
  return vim.fs.root(0, { '.greenlint.toml', '.git', '.hg' }) or vim.uv.cwd()
end

local function relative(path)
  return vim.fs.relpath(M.root(), path) or path
end

M.relative = relative

--- The project's greenlint config, when it has one.
local function config_path()
  local candidate = vim.fs.joinpath(M.root(), '.greenlint.toml')
  return vim.uv.fs_stat(candidate) and candidate or nil
end

local function baseline_path()
  local candidate = vim.fs.joinpath(M.root(), '.greenlint-baseline.json')
  return vim.uv.fs_stat(candidate) and candidate or nil
end

-- --- running greenlint -------------------------------------------------------

local missing_reported = false

local function run(argv, cb)
  local cmd = vim.list_extend(vim.list_slice(cfg.cmd, 1, #cfg.cmd), argv)
  log_line('run: %s', table.concat(cmd, ' '))
  local job = { cancelled = false }
  -- vim.system raises when the executable is not there, and a missing greenlint
  -- must not be a traceback -- it is the likeliest thing to be wrong, and
  -- :checkhealth is where it is explained.
  local ok, handle = pcall(vim.system, cmd, {
    text = true,
    cwd = M.root(),
    timeout = cfg.timeout_ms,
  }, function(out)
    jobs[job] = nil
    -- Cancelled: the non-zero exit is the kill, not an answer, and reporting it
    -- as a failed scan would make the command look broken.
    if job.cancelled then
      return
    end
    vim.schedule(function()
      cb(out)
    end)
  end)
  if ok then
    job.handle = handle
    jobs[job] = true
    return handle
  end
  log_line('could not run %s: %s', cmd[1], tostring(handle))
  if not missing_reported then
    missing_reported = true
    notify(('could not run `%s` — see :checkhealth greenlint'):format(cmd[1]), vim.log.levels.ERROR)
  end
  vim.schedule(function()
    cb({ code = -1, stdout = '', stderr = tostring(handle) })
  end)
  return nil
end

local function decode(out)
  if (out.stdout or '') == '' then
    return nil, (out.stderr ~= '' and out.stderr or 'greenlint produced no output')
  end
  local ok, value = pcall(vim.json.decode, out.stdout, { luanil = { array = true, object = true } })
  if not ok then
    return nil, 'could not read greenlint output as JSON: ' .. tostring(value)
  end
  if not core.is_findings(value) then
    return nil, 'unexpected output — is `cmd` pointing at greenlint?'
  end
  return value, nil
end

local function store(path, findings)
  path = vim.fs.normalize(path)
  if #findings == 0 then
    by_file[path] = nil
  else
    by_file[path] = findings
  end
  ui.render(path, findings, cfg)
end

--- Scan one file on disk.
function M.scan_file(path, opts)
  opts = opts or {}
  if not cfg.enabled then
    return
  end
  path = vim.fs.normalize(path)

  local stat = vim.uv.fs_stat(path)
  if stat and stat.size > cfg.max_file_bytes then
    log_line('%s: %d bytes, over the cap', relative(path), stat.size)
    if opts.on_done then
      opts.on_done(true)
    end
    return
  end

  run(core.scan_argv(cfg, { path }, { config = config_path(), baseline = baseline_path() }), function(out)
    local findings, err = decode(out)
    if not findings then
      log_line('%s: %s', relative(path), (err or ''):gsub('%s+$', ''))
      if opts.notify then
        notify(vim.split(err or 'scan failed', '\n')[1], vim.log.levels.WARN)
      end
    else
      store(path, findings)
      log_line('%s: %d finding(s)', relative(path), #findings)
    end
    if opts.on_done then
      opts.on_done(findings ~= nil)
    end
  end)
end

--- Scan an unsaved buffer.
---
--- The CLI reads files, not buffers, so the buffer is written to a temp file --
--- keeping its basename, because greenlint picks a rule set by extension and
--- recognises a test file by its name. Findings come back naming the temp file,
--- so the path is mapped home before anything sees it.
function M.scan_buffer(buf, opts)
  opts = opts or {}
  if not cfg.enabled then
    return
  end
  buf = buf or vim.api.nvim_get_current_buf()
  local path = vim.fs.normalize(vim.api.nvim_buf_get_name(buf))
  if path == '' then
    return
  end

  local dir = vim.fn.tempname()
  vim.fn.mkdir(dir, 'p')
  local temp = vim.fs.joinpath(dir, vim.fs.basename(path))
  local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
  vim.fn.writefile(lines, temp)

  local version = vim.api.nvim_buf_get_var and vim.b[buf].changedtick or nil
  run(core.scan_argv(cfg, { temp }, { config = config_path(), baseline = baseline_path() }), function(out)
    pcall(vim.fn.delete, dir, 'rf')
    local findings, err = decode(out)
    if not findings then
      log_line('%s (buffer): %s', relative(path), (err or ''):gsub('%s+$', ''))
      if opts.on_done then
        opts.on_done(false)
      end
      return
    end
    -- A newer edit landed while this was in flight; its scan is already
    -- scheduled and this answer describes text nobody is looking at.
    if vim.api.nvim_buf_is_valid(buf) and version and vim.b[buf].changedtick ~= version then
      if opts.on_done then
        opts.on_done(false)
      end
      return
    end
    for _, finding in ipairs(findings) do
      finding.file = path
    end
    store(path, findings)
    log_line('%s (buffer): %d finding(s)', relative(path), #findings)
    if opts.on_done then
      opts.on_done(true)
    end
  end)
end

--- Scan the whole project.
function M.scan_project(opts)
  opts = opts or {}
  if not cfg.enabled then
    return
  end
  local root = M.root()
  run(core.scan_argv(cfg, { root }, { config = config_path(), baseline = baseline_path() }), function(out)
    local findings, err = decode(out)
    if not findings then
      log_line('project: %s', (err or ''):gsub('%s+$', ''))
      if opts.notify then
        notify(vim.split(err or 'scan failed', '\n')[1], vim.log.levels.WARN)
      end
      if opts.on_done then
        opts.on_done(false)
      end
      return
    end

    -- A whole-project scan is the whole truth for the tree it walked, so files
    -- it reached and found nothing in must lose their old findings too.
    for path in pairs(by_file) do
      if path:sub(1, #root) == root then
        by_file[path] = nil
        ui.clear(path)
      end
    end
    local grouped = {}
    for _, finding in ipairs(findings) do
      local path = vim.fs.normalize(finding.file)
      finding.file = path
      grouped[path] = grouped[path] or {}
      table.insert(grouped[path], finding)
    end
    for path, list in pairs(grouped) do
      store(path, list)
    end
    log_line('project: %d finding(s) in %d file(s)', #findings, vim.tbl_count(grouped))
    if opts.on_done then
      opts.on_done(true)
    end
  end)
end

-- --- what was found ----------------------------------------------------------

function M.findings()
  local out = {}
  for _, list in pairs(by_file) do
    for _, finding in ipairs(list) do
      out[#out + 1] = finding
    end
  end
  return core.sorted(out)
end

function M.findings_for(path)
  return by_file[vim.fs.normalize(path or vim.api.nvim_buf_get_name(0))] or {}
end

function M.counts()
  return core.count_by_severity(M.findings())
end

--- A lualine component, or anything else that wants one string.
function M.statusline()
  if not cfg then
    return ''
  end
  local counts = M.counts()
  local total = counts.high + counts.medium + counts.low
  if total == 0 then
    return ''
  end
  return string.format('󱄅 %d/%d/%d', counts.high, counts.medium, counts.low)
end

-- --- triggers ----------------------------------------------------------------

local function debounce(key, ms, fn)
  if timers[key] then
    timers[key]:stop()
    timers[key]:close()
  end
  local timer = vim.uv.new_timer()
  timers[key] = timer
  timer:start(ms, 0, function()
    timer:stop()
    timer:close()
    timers[key] = nil
    vim.schedule(fn)
  end)
end

--- Automatic, as opposed to a command: 'manual' means only when asked.
local function scans_by_itself()
  return cfg.enabled and cfg.run ~= 'manual'
end

local function on_write(event)
  if scans_by_itself() then
    M.scan_file(event.match, {})
  end
end

--- A file coming into view: repaint what is already known about it, and scan
--- it only when nothing is.
local function on_open(event)
  local path = vim.fs.normalize(event.match)
  local known = by_file[path]
  if known then
    vim.schedule(function()
      ui.render(path, known, cfg)
    end)
  elseif scans_by_itself() and vim.uv.fs_stat(path) then
    M.scan_file(path, {})
  end
end

local function on_edit(event)
  if not (cfg.enabled and cfg.run == 'on_type') then
    return
  end
  debounce(event.buf, cfg.debounce_ms, function()
    if vim.api.nvim_buf_is_valid(event.buf) then
      M.scan_buffer(event.buf, {})
    end
  end)
end

--- Which handler answers which events. Both on-type events share one entry:
--- editing in normal mode and editing in insert mode are the same trigger, and
--- two registrations is two places for the guard to drift.
local TRIGGERS = {
  { 'BufWritePost', on_write },
  { { 'BufReadPost', 'BufEnter' }, on_open },
  { { 'TextChanged', 'TextChangedI' }, on_edit },
}

local function attach_autocmds()
  local group = vim.api.nvim_create_augroup('greenlint', { clear = true })
  for _, trigger in ipairs(TRIGGERS) do
    vim.api.nvim_create_autocmd(trigger[1], { group = group, callback = trigger[2] })
  end
end

-- --- commands ----------------------------------------------------------------

M.report = commands.report
M.list = commands.list
M.filter = commands.filter
M.set_grouping = commands.set_grouping
M.hover = commands.hover
M.clear_baseline = commands.clear_baseline
M.show_log = commands.show_log

--- Accept everything currently found, so an existing codebase starts green.
--- Confirmed first: it writes a file into the repository and quietens real
--- findings, which is not something to do because a command was near the cursor.
function M.write_baseline()
  local total = #M.findings()
  local choice = vim.fn.confirm(
    string.format(
      'Accept the %d current finding(s) as the baseline?\nThey stop being reported here and in CI; new ones still are.',
      total
    ),
    '&Write baseline\n&Cancel',
    2
  )
  if choice ~= 1 then
    return
  end
  local target = vim.fs.joinpath(M.root(), '.greenlint-baseline.json')
  run(core.write_baseline_argv(cfg, { M.root() }, target), function(out)
    if out.code ~= 0 then
      return notify(vim.split((out.stderr or 'could not write the baseline'), '\n')[1], vim.log.levels.ERROR)
    end
    local message = (out.stdout or ''):gsub('%s+$', '')
    notify(message ~= '' and message:gsub('^greenlint: ', '') or ('wrote ' .. relative(target)))
    M.scan_project({})
  end)
end

--- Stop whatever greenlint is running.
---
--- Both halves of "running": the processes in flight, and the debounced scan
--- that has not started yet -- cancelling one and leaving the other would put a
--- scan back milliseconds after the command said it stopped them.
function M.cancel()
  local stopped = 0
  for job in pairs(jobs) do
    job.cancelled = true
    jobs[job] = nil
    if job.handle then
      pcall(function()
        job.handle:kill('sigterm')
      end)
    end
    stopped = stopped + 1
  end
  local pending = 0
  for key, timer in pairs(timers) do
    timer:stop()
    timer:close()
    timers[key] = nil
    pending = pending + 1
  end
  log_line('cancelled %d scan(s), %d pending', stopped, pending)
  if stopped == 0 and pending == 0 then
    return notify('nothing running.')
  end
  notify(('stopped %d scan(s).'):format(stopped + pending))
end

-- --- setup -------------------------------------------------------------------

function M.setup(opts)
  cfg = config.resolve(opts)
  if not cfg.enabled then
    ui.clear_all()
    return
  end
  attach_autocmds()
  if cfg.scan_project_on_startup then
    vim.schedule(function()
      M.scan_project({})
    end)
  end
end

return M
