-- :checkhealth greenlint
--
-- One function per question the report answers, in the order it answers them.

local M = {}

local function run(cmd, args, timeout)
  local ok, out = pcall(function()
    return vim.system(vim.list_extend(vim.list_slice(cmd, 1, #cmd), args), { text = true }):wait(timeout or 15000)
  end)
  if not ok then
    return nil, tostring(out)
  end
  return out, nil
end

local function check_neovim()
  -- vim.system, vim.fs.relpath and vim.validate are all 0.11.
  if vim.fn.has('nvim-0.11') ~= 1 then
    vim.health.error('Neovim 0.11 or newer is required (vim.system, vim.fs.relpath, vim.validate).')
  else
    vim.health.ok('Neovim ' .. tostring(vim.version()))
  end
end

--- How many rules `--list-rules` listed. The first line has no newline in
--- front of it, so it is counted separately rather than missed.
local function count_rules(stdout)
  stdout = stdout or ''
  local rules = 0
  for _ in stdout:gmatch('\nGL%d') do
    rules = rules + 1
  end
  return rules + (stdout:match('^GL%d') and 1 or 0)
end

--- What `cmd --list-rules` had to say. The rule set is the product, so the
--- number of rules is the thing worth reporting.
local function check_rules(cfg, shown)
  local out, err = run(cfg.cmd, { '--list-rules' })
  if not out then
    return vim.health.error(('`%s` did not run: %s'):format(shown, err))
  end
  if out.code ~= 0 then
    return vim.health.error(('`%s --list-rules` exited %d'):format(shown, out.code), {
      vim.split(out.stderr or '', '\n')[1] or '',
    })
  end
  local rules = count_rules(out.stdout)
  if rules == 0 then
    return vim.health.warn(('`%s` ran, but does not look like greenlint'):format(shown))
  end
  vim.health.ok(('`%s` runs — %d rules'):format(shown, rules))
end

local function check_command(cfg)
  if vim.fn.executable(cfg.cmd[1]) ~= 1 then
    return vim.health.error(('`%s` is not executable'):format(cfg.cmd[1]), {
      'pip install greenlint, or point cmd at a checkout:',
      "  require('greenlint').setup({ cmd = { 'python3', '/path/to/greenlint.py' } })",
    })
  end
  check_rules(cfg, table.concat(cfg.cmd, ' '))
end

--- The two files in the project that change what a scan reports.
local function check_project_files(root)
  if vim.uv.fs_stat(vim.fs.joinpath(root, '.greenlint.toml')) then
    vim.health.ok('.greenlint.toml found — its rule opt-outs and ignore globs apply here too')
  else
    vim.health.info('no .greenlint.toml; the default rule set applies')
  end

  if vim.uv.fs_stat(vim.fs.joinpath(root, '.greenlint-baseline.json')) then
    vim.health.ok('baseline: .greenlint-baseline.json (accepted findings are hidden)')
  else
    vim.health.info('baseline: none')
  end
end

function M.check()
  vim.health.start('greenlint')

  local greenlint = require('greenlint')
  local cfg = greenlint.config() or require('greenlint.config').resolve({})

  check_neovim()
  check_command(cfg)

  local root = greenlint.root()
  vim.health.info('project root: ' .. tostring(root))
  check_project_files(root)

  if cfg.run == 'on_type' then
    vim.health.info('run = "on_type": each scan writes the buffer to a temp file, since the CLI reads files')
  end
end

return M
