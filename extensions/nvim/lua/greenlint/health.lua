-- :checkhealth greenlint

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

function M.check()
  vim.health.start('greenlint')

  local greenlint = require('greenlint')
  local cfg = greenlint.config() or require('greenlint.config').resolve({})

  if vim.fn.has('nvim-0.11') ~= 1 then
    vim.health.error('Neovim 0.11 or newer is required (vim.system, vim.fs.relpath, vim.validate).')
  else
    vim.health.ok('Neovim ' .. tostring(vim.version()))
  end

  local shown = table.concat(cfg.cmd, ' ')
  if vim.fn.executable(cfg.cmd[1]) ~= 1 then
    vim.health.error(('`%s` is not executable'):format(cfg.cmd[1]), {
      'pip install greenlint, or point cmd at a checkout:',
      "  require('greenlint').setup({ cmd = { 'python3', '/path/to/greenlint.py' } })",
    })
  else
    -- The rule set is the product, so how many rules this build has is the
    -- thing worth reporting.
    local out, err = run(cfg.cmd, { '--list-rules' })
    if not out then
      vim.health.error(('`%s` did not run: %s'):format(shown, err))
    elseif out.code ~= 0 then
      vim.health.error(('`%s --list-rules` exited %d'):format(shown, out.code), {
        vim.split(out.stderr or '', '\n')[1] or '',
      })
    else
      local rules = 0
      for _ in (out.stdout or ''):gmatch('\nGL%d') do
        rules = rules + 1
      end
      rules = rules + ((out.stdout or ''):match('^GL%d') and 1 or 0)
      if rules == 0 then
        vim.health.warn(('`%s` ran, but does not look like greenlint'):format(shown))
      else
        vim.health.ok(('`%s` runs — %d rules'):format(shown, rules))
      end
    end
  end

  local root = greenlint.root()
  vim.health.info('project root: ' .. tostring(root))

  local config_file = vim.fs.joinpath(root, '.greenlint.toml')
  if vim.uv.fs_stat(config_file) then
    vim.health.ok('.greenlint.toml found — its rule opt-outs and ignore globs apply here too')
  else
    vim.health.info('no .greenlint.toml; the default rule set applies')
  end

  local baseline = vim.fs.joinpath(root, '.greenlint-baseline.json')
  if vim.uv.fs_stat(baseline) then
    vim.health.ok('baseline: .greenlint-baseline.json (accepted findings are hidden)')
  else
    vim.health.info('baseline: none')
  end

  if cfg.run == 'on_type' then
    vim.health.info('run = "on_type": each scan writes the buffer to a temp file, since the CLI reads files')
  end
end

return M
