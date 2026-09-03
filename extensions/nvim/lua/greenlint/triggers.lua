-- Which editor events cause a scan, and how long they wait first.
--
-- The plugin is required lazily, the way `commands.lua` does it: this module is
-- reached from `greenlint.setup`, so requiring it at the top would be a cycle.

local store = require('greenlint.store')
local ui = require('greenlint.ui')

local M = {}

--- Debounce key -> the timer that has not fired yet.
local timers = {}

local function api()
  return require('greenlint')
end

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
  local cfg = api().config()
  return cfg.enabled and cfg.run ~= 'manual'
end

local function on_write(event)
  if scans_by_itself() then
    api().scan_file(event.match, {})
  end
end

--- A file coming into view: repaint what is already known about it, and scan
--- it only when nothing is.
local function on_open(event)
  local path = vim.fs.normalize(event.match)
  local known = store.for_path(path)
  if #known > 0 then
    vim.schedule(function()
      ui.render(path, known, api().config())
    end)
  elseif scans_by_itself() and vim.uv.fs_stat(path) then
    api().scan_file(path, {})
  end
end

local function on_edit(event)
  local cfg = api().config()
  if not (cfg.enabled and cfg.run == 'on_type') then
    return
  end
  debounce(event.buf, cfg.debounce_ms, function()
    if vim.api.nvim_buf_is_valid(event.buf) then
      api().scan_buffer(event.buf, {})
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

function M.attach()
  local group = vim.api.nvim_create_augroup('greenlint', { clear = true })
  for _, trigger in ipairs(TRIGGERS) do
    vim.api.nvim_create_autocmd(trigger[1], { group = group, callback = trigger[2] })
  end
end

--- Drop every debounced scan that has not started, and say how many there were.
function M.cancel_pending()
  local pending = 0
  for key, timer in pairs(timers) do
    timer:stop()
    timer:close()
    timers[key] = nil
    pending = pending + 1
  end
  return pending
end

return M
