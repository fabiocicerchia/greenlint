-- The plugin has to sort: it merges findings from several scans, which no
-- single greenlint run covers. But the *order* is greenlint's, and this spec is
-- what stops the copy here from quietly becoming a second answer.
--
-- It reads greenlint.py and compares. Skipped when there is no interpreter or
-- no checkout to read, so the suite still runs anywhere.

local core = require('greenlint.core')

local function greenlint_severity_order()
  local root = vim.fn.fnamemodify(vim.fn.resolve(debug.getinfo(1, 'S').source:sub(2)), ':p:h:h:h:h')
  local module = vim.fs.joinpath(root, 'greenlint.py')
  if vim.fn.executable('python3') ~= 1 or not vim.uv.fs_stat(module) then
    return nil
  end
  local out = vim.system({
    'python3',
    '-c',
    ([[
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("greenlint", %q)
module = importlib.util.module_from_spec(spec)
sys.modules["greenlint"] = module
spec.loader.exec_module(module)
print(json.dumps(module.SEVERITY_ORDER))
]]):format(module),
  }, { text = true }):wait(20000)
  if out.code ~= 0 then
    return nil
  end
  local ok, decoded = pcall(vim.json.decode, out.stdout)
  return ok and decoded or nil
end

describe("greenlint's severity order", function()
  it('is the order this plugin sorts by', function()
    local theirs = greenlint_severity_order()
    if not theirs then
      pending('no python3 or no greenlint.py to compare against')
      return
    end
    -- Same words, and the same relative order. greenlint counts from 0 and this
    -- counts from 1, which is a Lua convention rather than a disagreement.
    assert.same(vim.tbl_keys(theirs), vim.tbl_keys(core.SEVERITY_ORDER))

    local function ordered(map)
      local words = vim.tbl_keys(map)
      table.sort(words, function(a, b)
        return map[a] < map[b]
      end)
      return words
    end
    assert.same(ordered(theirs), ordered(core.SEVERITY_ORDER))
  end)

  it('lists the same severities as SEVERITIES, worst first', function()
    local ordered = vim.tbl_keys(core.SEVERITY_ORDER)
    table.sort(ordered, function(a, b)
      return core.SEVERITY_ORDER[a] < core.SEVERITY_ORDER[b]
    end)
    assert.same(ordered, core.SEVERITIES)
  end)
end)
