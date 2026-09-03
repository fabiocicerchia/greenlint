-- The commands in plugin/greenlint.lua that only read what has been found.
--
-- They reach the rest of the plugin through its public API rather than through
-- its internals, and they require it lazily: greenlint/init.lua requires this
-- module while it is still loading, so a require at the top of this file would
-- be a cycle.

local core = require('greenlint.core')
local log = require('greenlint.log')
local ui = require('greenlint.ui')

local M = {}

--- What :GreenlintGroupBy chose, until the session ends. nil means the
--- configured default.
local grouping = nil

local function api()
  return require('greenlint')
end

--- Run `cb` once there is something to show, walking the project first when
--- nothing has been scanned yet.
local function ensure_scanned(cb)
  if #api().findings() > 0 then
    return cb()
  end
  api().scan_project({ on_done = cb })
end

function M.report()
  ensure_scanned(function()
    local greenlint = api()
    ui.float(
      core.report_lines(greenlint.findings(), grouping or greenlint.config().grouping, greenlint.relative),
      { title = ' greenlint report ', filetype = 'greenlint-report' }
    )
  end)
end

function M.list()
  ensure_scanned(function()
    local findings = api().findings()
    if #findings == 0 then
      return ui.notify('nothing wasteful found.')
    end
    ui.to_quickfix(findings, 'greenlint')
    vim.cmd('copen')
  end)
end

--- The severities actually present, in greenlint's own order.
local function severities_found(counts)
  local items = {}
  for _, severity in ipairs(core.SEVERITIES) do
    if counts[severity] > 0 then
      items[#items + 1] = severity
    end
  end
  return items
end

local function list_severity(severity)
  local rows = {}
  for _, finding in ipairs(api().findings()) do
    if finding.severity == severity then
      rows[#rows + 1] = finding
    end
  end
  ui.to_quickfix(rows, 'greenlint: ' .. severity)
  vim.cmd('copen')
end

function M.filter()
  ensure_scanned(function()
    local counts = api().counts()
    local items = severities_found(counts)
    if #items == 0 then
      return ui.notify('nothing wasteful found.')
    end
    vim.ui.select(items, {
      prompt = 'Show findings at severity',
      format_item = function(severity)
        return string.format('%-7s %d', severity, counts[severity])
      end,
    }, function(severity)
      if severity then
        list_severity(severity)
      end
    end)
  end)
end

local GROUPING_BLURB = {
  file = 'one group per file',
  severity = 'high, then medium, then low',
  rule = 'one group per rule',
}

function M.set_grouping()
  vim.ui.select({ 'file', 'severity', 'rule' }, {
    prompt = 'Group findings by',
    format_item = function(choice)
      return string.format('%-9s %s', choice, GROUPING_BLURB[choice])
    end,
  }, function(choice)
    if choice then
      grouping = choice
      M.report()
    end
  end)
end

function M.hover()
  local path = vim.fs.normalize(vim.api.nvim_buf_get_name(0))
  local lnum = vim.api.nvim_win_get_cursor(0)[1]
  for _, finding in ipairs(api().findings_for(path)) do
    if finding.line == lnum then
      return ui.hover(core.hover_lines(finding))
    end
  end
  ui.notify('no finding on this line.')
end

--- Drop the baseline, so everything it was accepting is reported again.
---
--- Confirmed like writing one is: it deletes a file from the repository, and
--- that file can be the record of which findings a team decided to live with.
--- Going back is a scan; getting the list of accepted findings back is not.
function M.clear_baseline()
  local greenlint = api()
  local target = vim.fs.joinpath(greenlint.root(), '.greenlint-baseline.json')
  if not vim.uv.fs_stat(target) then
    return ui.notify('no baseline to clear.')
  end
  local choice = vim.fn.confirm(
    ('Delete %s?\nEvery finding it was accepting is reported again.'):format(greenlint.relative(target)),
    '&Delete baseline\n&Cancel',
    2
  )
  if choice ~= 1 then
    return
  end
  local ok, err = os.remove(target)
  if not ok then
    return ui.notify(
      ('could not delete %s: %s'):format(greenlint.relative(target), err or '?'),
      vim.log.levels.ERROR
    )
  end
  log.add('deleted %s', greenlint.relative(target))
  ui.notify('deleted ' .. greenlint.relative(target))
  -- The findings on screen were filtered by the baseline that just went, so
  -- they describe a world that no longer exists.
  greenlint.scan_project({})
end

function M.show_log()
  local lines = log.lines()
  ui.float(#lines > 0 and lines or { 'nothing logged yet' }, {
    title = ' greenlint log ',
    filetype = 'log',
  })
end

return M
