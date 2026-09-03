-- What has been found, keyed by the file it was found in.
--
-- The store is the one place that decides a file's findings changed, so it is
-- also the one place that repaints them: every writer goes through `put`, and
-- nothing else touches the table.

local core = require('greenlint.core')
local ui = require('greenlint.ui')

local M = {}

--- absolute path -> findings
local by_file = {}

--- Record `findings` for `path` and repaint it. An empty list is an absence,
--- not an entry: `findings_for` and the project prune both read it that way.
function M.put(path, findings, cfg)
  path = vim.fs.normalize(path)
  if #findings == 0 then
    by_file[path] = nil
  else
    by_file[path] = findings
  end
  ui.render(path, findings, cfg)
end

--- Everything known about the tree under `root` is now history: the walk that
--- just finished is the whole truth for it, so a file it reached and found
--- nothing in must lose its old findings too.
function M.forget_under(root)
  for path in pairs(by_file) do
    if path:sub(1, #root) == root then
      by_file[path] = nil
      ui.clear(path)
    end
  end
end

--- The findings of a project scan, keyed by the normalised file they name.
function M.group_by_file(findings)
  local grouped = {}
  for _, finding in ipairs(findings) do
    local path = vim.fs.normalize(finding.file)
    finding.file = path
    grouped[path] = grouped[path] or {}
    table.insert(grouped[path], finding)
  end
  return grouped
end

function M.all()
  local out = {}
  for _, list in pairs(by_file) do
    for _, finding in ipairs(list) do
      out[#out + 1] = finding
    end
  end
  return core.sorted(out)
end

function M.for_path(path)
  return by_file[vim.fs.normalize(path or vim.api.nvim_buf_get_name(0))] or {}
end

function M.counts()
  return core.count_by_severity(M.all())
end

return M
