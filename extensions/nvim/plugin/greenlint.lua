-- User commands only. Nothing here requires core.lua, so a session that never
-- scans never loads the plugin.

if vim.g.loaded_greenlint then
  return
end
vim.g.loaded_greenlint = true

local function ready()
  local greenlint = require('greenlint')
  if not greenlint.is_setup() then
    greenlint.setup({})
  end
  return greenlint
end

local command = vim.api.nvim_create_user_command

command('GreenlintScan', function()
  local greenlint = ready()
  local buf = vim.api.nvim_get_current_buf()
  if vim.bo[buf].modified then
    greenlint.scan_buffer(buf, { notify = true })
  else
    greenlint.scan_file(vim.api.nvim_buf_get_name(buf), { notify = true })
  end
end, { desc = 'greenlint: scan the current file' })

command('GreenlintScanProject', function()
  ready().scan_project({ notify = true })
end, { desc = 'greenlint: scan the whole project' })

command('GreenlintReport', function()
  ready().report()
end, { desc = 'greenlint: open the report' })

command('GreenlintList', function()
  ready().list()
end, { desc = 'greenlint: every finding, in the quickfix list' })

command('GreenlintFilter', function()
  ready().filter()
end, { desc = 'greenlint: findings at one severity, in the quickfix list' })

command('GreenlintGroupBy', function()
  ready().set_grouping()
end, { desc = 'greenlint: group the report by file, severity or rule' })

command('GreenlintHover', function()
  ready().hover()
end, { desc = 'greenlint: explain the finding under the cursor' })

command('GreenlintBaselineWrite', function()
  ready().write_baseline()
end, { desc = 'greenlint: accept current findings (write baseline)' })

command('GreenlintLog', function()
  ready().show_log()
end, { desc = 'greenlint: show the log' })
