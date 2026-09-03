-- Diagnostics, the report float, and the quickfix list.

local core = require('greenlint.core')

local M = {}

local NS = vim.api.nvim_create_namespace('greenlint')
M.namespace = NS

--- Everything the plugin says to the user, prefixed once.
function M.notify(message, level)
  vim.notify('greenlint: ' .. message, level or vim.log.levels.INFO)
end

--- One finding as a diagnostic spanning the code on `text`.
---
--- The squiggle starts at the first non-whitespace character, so it traces the
--- code rather than the indentation.
local function to_diagnostic(finding, lnum, text, severity)
  local indent = text:match('^%s*') or ''
  local col = text:match('%S') and #indent or 0
  return {
    lnum = lnum,
    col = col,
    end_lnum = lnum,
    end_col = math.max(col, #text),
    severity = severity,
    source = 'greenlint',
    code = finding.rule,
    message = core.summarise(finding),
  }
end

--- The findings that have a place in this buffer, worst first.
---
--- greenlint scanned the file on disk and the buffer may be shorter, so a
--- finding past the end is dropped rather than clamped onto the wrong line.
local function build_diagnostics(buf, findings, cfg)
  local line_count = vim.api.nvim_buf_line_count(buf)
  local diagnostics = {}
  for _, finding in ipairs(core.sorted(findings)) do
    local severity = cfg.diagnostics.severity[finding.severity]
    local lnum = math.max(0, (finding.line or 1) - 1)
    if severity and lnum < line_count then
      local text = vim.api.nvim_buf_get_lines(buf, lnum, lnum + 1, false)[1] or ''
      diagnostics[#diagnostics + 1] = to_diagnostic(finding, lnum, text, severity)
    end
  end
  return diagnostics
end

--- Publish one file's findings, if it is open.
function M.render(path, findings, cfg)
  if not cfg.diagnostics.enabled then
    return
  end
  local buf = vim.fn.bufnr(path)
  if buf == -1 or not vim.api.nvim_buf_is_loaded(buf) then
    return
  end
  vim.diagnostic.set(NS, buf, build_diagnostics(buf, findings, cfg))
end

function M.clear(path)
  local buf = path and vim.fn.bufnr(path) or nil
  if buf and buf ~= -1 then
    vim.diagnostic.reset(NS, buf)
  end
end

function M.clear_all()
  vim.diagnostic.reset(NS)
end

function M.float(lines, opts)
  opts = opts or {}
  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].modifiable = false
  vim.bo[buf].filetype = opts.filetype or 'markdown'
  vim.bo[buf].bufhidden = 'wipe'

  local width = 0
  for _, line in ipairs(lines) do
    width = math.max(width, vim.fn.strdisplaywidth(line))
  end
  width = math.min(math.max(width + 2, 48), math.floor(vim.o.columns * 0.9))
  local height = math.min(math.max(#lines, 3), math.floor(vim.o.lines * 0.8))

  local win = vim.api.nvim_open_win(buf, true, {
    relative = 'editor',
    row = math.floor((vim.o.lines - height) / 2),
    col = math.floor((vim.o.columns - width) / 2),
    width = width,
    height = height,
    style = 'minimal',
    border = 'rounded',
    title = opts.title or ' greenlint ',
    title_pos = 'center',
  })
  vim.wo[win].wrap = false
  vim.wo[win].cursorline = true
  for _, key in ipairs({ 'q', '<Esc>' }) do
    vim.keymap.set('n', key, function()
      if vim.api.nvim_win_is_valid(win) then
        vim.api.nvim_win_close(win, true)
      end
    end, { buffer = buf, nowait = true, silent = true })
  end
  return buf, win
end

function M.hover(lines)
  return vim.lsp.util.open_floating_preview(lines, 'markdown', {
    border = 'rounded',
    focusable = true,
    max_width = 90,
  })
end

function M.to_quickfix(findings, title)
  local items = {}
  for _, finding in ipairs(core.sorted(findings)) do
    items[#items + 1] = {
      filename = finding.file,
      lnum = math.max(1, finding.line or 1),
      col = 1,
      text = string.format('[%s] %s — %s', finding.rule, finding.message, finding.suggestion or ''),
      type = finding.severity == 'high' and 'W' or 'I',
    }
  end
  vim.fn.setqflist({}, ' ', { title = title, items = items })
end

return M
