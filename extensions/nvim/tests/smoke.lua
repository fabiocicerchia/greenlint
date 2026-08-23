-- End-to-end: this plugin, the real greenlint CLI, real files, nothing else on
-- the runtimepath.

local here = vim.fn.fnamemodify(vim.fn.resolve(debug.getinfo(1, 'S').source:sub(2)), ':p:h:h')
vim.opt.runtimepath:prepend(here)
vim.opt.swapfile = false
vim.cmd('runtime! plugin/greenlint.lua')

local repo = vim.fn.fnamemodify(here, ':h:h')

-- Headless has no one to answer a prompt.
local prompts = 0
vim.ui.select = function(items, opts, on_choice)
  prompts = prompts + 1
  on_choice(items[1], 1)
end
vim.fn.confirm = function()
  return 1
end

local failures = {}
local function check(ok, what)
  print((ok and '  ok   ' or '  FAIL ') .. what)
  if not ok then
    failures[#failures + 1] = what
  end
end

local project = vim.fn.tempname()
vim.fn.mkdir(project .. '/src', 'p')
-- GL001: a busy loop with no sleep. GL005: SELECT *.
vim.fn.writefile({ 'while True:', '    pass' }, project .. '/src/worker.py')
vim.fn.writefile({ 'SELECT * FROM users;' }, project .. '/src/query.sql')
vim.fn.writefile({ 'clean = 1' }, project .. '/src/ok.py')
vim.uv.chdir(project)

local cmd = vim.env.GREENLINT_CMD and vim.split(vim.env.GREENLINT_CMD, ' ')
  or { 'python3', repo .. '/greenlint.py' }

print('greenlint.nvim smoke test')
print('  cmd:     ' .. table.concat(cmd, ' '))
print('  project: ' .. project)

local greenlint = require('greenlint')
greenlint.setup({ cmd = cmd, run = 'manual', scan_project_on_startup = false })

check(greenlint.is_setup(), 'setup() resolved a config')

local done = nil
greenlint.scan_project({ on_done = function(ok)
  done = ok
end })
vim.wait(60000, function()
  return done ~= nil
end, 100)
check(done == true, 'the project scan completed')

local findings = greenlint.findings()
check(#findings >= 2, ('found the planted issues (%d finding(s))'):format(#findings))

local rules = {}
for _, finding in ipairs(findings) do
  rules[finding.rule] = true
end
check(rules.GL001, 'GL001 (busy loop) was found')
check(rules.GL005, 'GL005 (SELECT *) was found')

-- Worst first, which is greenlint's own ordering.
check(findings[1].severity == 'high' or findings[1].severity == 'medium', 'the list leads with the worst')

local counts = greenlint.counts()
check(counts.high + counts.medium + counts.low == #findings, 'the counts add up')
check(greenlint.statusline() ~= '', 'the statusline reads "' .. greenlint.statusline() .. '"')

-- Diagnostics land only once a file is open, and on the line greenlint named.
vim.cmd.edit(project .. '/src/worker.py')
local buf = vim.api.nvim_get_current_buf()
vim.wait(2000, function()
  return #vim.diagnostic.get(buf, { namespace = require('greenlint.ui').namespace }) > 0
end, 50)
local diagnostics = vim.diagnostic.get(buf, { namespace = require('greenlint.ui').namespace })
check(#diagnostics > 0, ('diagnostics were published (%d)'):format(#diagnostics))
if #diagnostics > 0 then
  check(diagnostics[1].lnum == 0, 'on the line the busy loop is on')
  check(diagnostics[1].message:find('sleep', 1, true) ~= nil, 'carrying the suggestion, which is the point')
end

-- A clean file must end up with nothing, not with stale findings.
check(#greenlint.findings_for(project .. '/src/ok.py') == 0, 'a clean file has no findings')

-- Scanning an unsaved buffer: the CLI reads files, so this writes the buffer to
-- a temp file whose basename is preserved.
vim.api.nvim_buf_set_lines(buf, 0, -1, false, { 'import time', 'while True:', '    time.sleep(1)' })
local typed = nil
greenlint.scan_buffer(buf, { on_done = function(ok)
  typed = ok
end })
vim.wait(60000, function()
  return typed ~= nil
end, 100)
check(typed == true, 'the buffer scan completed')
check(#greenlint.findings_for(project .. '/src/worker.py') == 0, 'fixing the loop in the buffer cleared it')

for _, name in ipairs({
  'GreenlintReport',
  'GreenlintList',
  'GreenlintFilter',
  'GreenlintGroupBy',
  'GreenlintLog',
}) do
  local ok, err = pcall(vim.cmd, name)
  check(ok, name .. (ok and '' or ': ' .. tostring(err)))
  pcall(vim.cmd, 'cclose')
  pcall(vim.cmd, 'close')
end
check(prompts >= 2, ('the commands that offer a choice did (%d prompt(s))'):format(prompts))

print('')
if #failures > 0 then
  print(('%d check(s) failed:'):format(#failures))
  for _, what in ipairs(failures) do
    print('  - ' .. what)
  end
  vim.cmd('cq')
else
  print('all checks passed')
  vim.cmd('qa!')
end
