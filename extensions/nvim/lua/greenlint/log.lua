-- What greenlint.nvim did, for :GreenlintLog.
--
-- A bounded ring: a session that scans on every keystroke would otherwise grow
-- this without limit, and the interesting lines are always the recent ones.

local M = {}

local LIMIT = 500

local lines = {}

function M.add(fmt, ...)
  lines[#lines + 1] = string.format('[%s] ' .. fmt, os.date('%H:%M:%S'), ...)
  if #lines > LIMIT then
    table.remove(lines, 1)
  end
end

function M.lines()
  return lines
end

return M
