-- Defaults and validation.

local M = {}

M.defaults = {
  enabled = true,

  --- How to run greenlint. A list, so an interpreter can go in front of it:
  --- `{ 'python3', '/path/to/greenlint.py' }` for a checkout.
  cmd = { 'greenlint' },

  --- When to scan the file you are editing.
  ---   'on_save'  scan when the file is written (the default: it is the only
  ---              mode that scans exactly what is on disk)
  ---   'on_type'  scan the buffer as you go, debounced. The CLI reads files,
  ---              not buffers, so the buffer is written to a temp file whose
  ---              basename is preserved -- greenlint picks a rule set by
  ---              extension, and detects test files by name
  ---   'manual'   only when you ask
  run = 'on_save',

  --- Idle time before an on_type scan. The cost of a keystroke is this timer
  --- being reset, not a scan.
  debounce_ms = 400,

  --- Scan the whole project once when the plugin loads.
  scan_project_on_startup = true,

  --- Skip files larger than this. A generated or vendored megabyte costs real
  --- time to scan and is rarely yours to fix.
  max_file_bytes = 1000000,

  --- Extra ignore globs for the editor only, on top of .greenlint.toml. Same
  --- syntax as `ignore` there; prefer the config file for anything CI should
  --- skip too.
  exclude = {},

  --- Give up on a scan that takes longer than this.
  timeout_ms = 60000,

  diagnostics = {
    enabled = true,
    --- greenlint's severities as editor severities. Three levels with a
    --- natural order do not need much of a settings page, but a warning per
    --- `SELECT *` is a lot for some people, so it is adjustable.
    severity = {
      high = vim.diagnostic.severity.WARN,
      medium = vim.diagnostic.severity.INFO,
      low = vim.diagnostic.severity.HINT,
    },
  },

  --- How :GreenlintReport groups findings: 'severity', 'file' or 'rule'.
  grouping = 'file',
}

local function merge(defaults, opts)
  local out = {}
  for key, value in pairs(defaults) do
    if type(value) == 'table' and not vim.islist(value) then
      out[key] = merge(value, (opts or {})[key] or {})
    elseif opts and opts[key] ~= nil then
      out[key] = opts[key]
    else
      out[key] = value
    end
  end
  for key, value in pairs(opts or {}) do
    if out[key] == nil then
      out[key] = value
    end
  end
  return out
end

local RUN_MODES = { on_save = true, on_type = true, manual = true }
local GROUPINGS = { severity = true, file = true, rule = true }
local SEVERITIES = {
  [vim.diagnostic.severity.ERROR] = true,
  [vim.diagnostic.severity.WARN] = true,
  [vim.diagnostic.severity.INFO] = true,
  [vim.diagnostic.severity.HINT] = true,
}

function M.validate(cfg)
  vim.validate('enabled', cfg.enabled, 'boolean')
  vim.validate('cmd', cfg.cmd, function(v)
    return vim.islist(v) and #v > 0 and type(v[1]) == 'string'
  end, 'a non-empty list of strings')
  vim.validate('run', cfg.run, function(v)
    return RUN_MODES[v] == true
  end, 'one of: on_save, on_type, manual')
  vim.validate('debounce_ms', cfg.debounce_ms, function(v)
    return type(v) == 'number' and v >= 100
  end, 'a number >= 100')
  vim.validate('scan_project_on_startup', cfg.scan_project_on_startup, 'boolean')
  vim.validate('max_file_bytes', cfg.max_file_bytes, function(v)
    return type(v) == 'number' and v >= 1024
  end, 'a number >= 1024')
  vim.validate('exclude', cfg.exclude, vim.islist, 'a list of globs')
  vim.validate('timeout_ms', cfg.timeout_ms, 'number')
  vim.validate('diagnostics.enabled', cfg.diagnostics.enabled, 'boolean')
  for severity, value in pairs(cfg.diagnostics.severity) do
    vim.validate('diagnostics.severity.' .. severity, value, function(v)
      return v == false or SEVERITIES[v] == true
    end, 'false, or a vim.diagnostic.severity value')
  end
  vim.validate('grouping', cfg.grouping, function(v)
    return GROUPINGS[v] == true
  end, 'one of: severity, file, rule')
  return cfg
end

function M.resolve(opts)
  return M.validate(merge(M.defaults, opts or {}))
end

return M
