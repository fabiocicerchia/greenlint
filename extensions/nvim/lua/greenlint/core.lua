-- The ported logic: building the command line, reading what comes back, and
-- saying why a finding matters.
--
-- The rules are not ported and could not sensibly be: they are Python regexes
-- plus six `ast`-based analyses, and a Lua reimplementation would be a
-- different linter that mostly agrees -- which is the worst possible outcome
-- when the rule set is the product. So greenlint is run, and this reads its
-- JSON.
--
-- No `vim.` calls: the whole module is testable under plain Lua.

local M = {}

-- --- the command line --------------------------------------------------------

--- Argv for a scan of `paths`.
---@param cfg table resolved configuration
---@param paths string[] files or directories
---@param opts table|nil { config = string|nil, baseline = string|nil }
function M.scan_argv(cfg, paths, opts)
  opts = opts or {}
  local argv = { '--format', 'json' }
  local function add(...)
    for _, value in ipairs({ ... }) do
      argv[#argv + 1] = value
    end
  end

  if opts.config then
    add('--config', opts.config)
  end
  if opts.baseline then
    add('--baseline', opts.baseline)
  end
  -- Repeated rather than joined: a glob may legitimately contain a comma, and
  -- greenlint's argparse append is unambiguous.
  for _, glob in ipairs(cfg.exclude) do
    add('--exclude', glob)
  end
  for _, path in ipairs(paths) do
    add(path)
  end
  return argv
end

function M.write_baseline_argv(cfg, paths, baseline_path)
  local argv = M.scan_argv(cfg, paths, {})
  -- --format is meaningless with --write-baseline, and greenlint prints a
  -- human line either way; drop it so the output is just that line.
  local out = {}
  local skip = 0
  for i, arg in ipairs(argv) do
    if skip > 0 then
      skip = skip - 1
    elseif arg == '--format' then
      skip = 1
    else
      out[#out + 1] = argv[i]
    end
  end
  table.insert(out, 1, baseline_path)
  table.insert(out, 1, '--write-baseline')
  return out
end

-- --- severities --------------------------------------------------------------

--- greenlint's three levels, worst first.
---
--- This mirrors `SEVERITY_ORDER` in greenlint.py, and `severity_order_spec.lua`
--- reads that module and fails if the two ever disagree. The plugin has to sort
--- here -- it merges findings from several scans, which no single greenlint run
--- covers -- but it must not invent a second answer to what the order *is*.
M.SEVERITY_ORDER = { high = 1, medium = 2, low = 3 }

M.SEVERITIES = { 'high', 'medium', 'low' }

M.SEVERITY_ICON = { high = '', medium = '', low = '' }

local function rank(severity)
  return M.SEVERITY_ORDER[severity] or math.huge
end

--- Severity, then file, then line -- the order greenlint's own output uses.
function M.compare_findings(a, b)
  local ra, rb = rank(a.severity), rank(b.severity)
  if ra ~= rb then
    return ra < rb
  end
  if a.file ~= b.file then
    return a.file < b.file
  end
  return (a.line or 0) < (b.line or 0)
end

function M.sorted(findings)
  local out = {}
  for i, finding in ipairs(findings) do
    out[i] = finding
  end
  table.sort(out, M.compare_findings)
  return out
end

--- Whether a decoded value looks like greenlint's output: a list of findings.
--- An empty list is a perfectly good answer, so shape is checked rather than
--- emptiness.
function M.is_findings(value)
  if type(value) ~= 'table' then
    return false
  end
  for _, finding in ipairs(value) do
    if type(finding) ~= 'table' or type(finding.rule) ~= 'string' or type(finding.file) ~= 'string' then
      return false
    end
  end
  return true
end

function M.count_by_severity(findings)
  local counts = { high = 0, medium = 0, low = 0 }
  for _, finding in ipairs(findings) do
    counts[finding.severity] = (counts[finding.severity] or 0) + 1
  end
  return counts
end

-- --- saying why --------------------------------------------------------------

--- The anchor for a rule's section in docs/rules.md, following GitHub's slug
--- rules: lowercase, punctuation dropped, spaces to hyphens. The headings there
--- are `## GL001 — busy loop without sleep`, so the em dash leaves the doubled
--- hyphen you see in the result.
---
--- greenlint's own test suite asserts every rule still has a heading that
--- matches its message, so this cannot silently start pointing nowhere.
function M.docs_url(finding)
  local slug = (finding.rule .. ' — ' .. finding.message):lower()
  slug = slug:gsub('[^a-z0-9 _%-]', ''):gsub(' ', '-')
  return 'https://github.com/fabiocicerchia/greenlint/blob/main/docs/rules.md#' .. slug
end

--- The one-line message on the diagnostic. The suggestion is the point of the
--- tool, so it is on the line rather than a click away.
function M.summarise(finding)
  return string.format('%s — %s', finding.message, finding.suggestion or '')
end

--- The hover: what was found, what to do instead, what it costs.
function M.hover_lines(finding)
  local lines = {
    string.format('**%s**', finding.message),
    '',
    string.format('`%s` · %s severity · greenlint', finding.rule, finding.severity),
    '',
    '**Do instead:** ' .. (finding.suggestion or ''),
  }
  -- The CO2e hints are prose about different physical quantities -- grams per
  -- GB, grams per instance-day, "negligible per call" -- so they are shown as
  -- written rather than summed into a number with no unit.
  if finding.co2e_estimate and finding.co2e_estimate ~= '' then
    lines[#lines + 1] = ''
    lines[#lines + 1] = '**Rough cost:** ' .. finding.co2e_estimate
  end
  lines[#lines + 1] = ''
  lines[#lines + 1] = string.format('[%s in the rules reference](%s)', finding.rule, M.docs_url(finding))
  return lines
end

--- The report, as lines. Grouped by the thing asked for.
---@param grouping 'severity'|'file'|'rule'
function M.report_lines(findings, grouping, relative)
  relative = relative or function(path)
    return path
  end
  local sorted = M.sorted(findings)
  local counts = M.count_by_severity(sorted)
  local lines = {
    string.format('%d finding(s) — %d high · %d medium · %d low', #sorted, counts.high, counts.medium, counts.low),
    string.rep('─', 60),
    '',
  }
  if #sorted == 0 then
    lines[#lines + 1] = 'Nothing wasteful found.'
    return lines
  end

  local groups, order = {}, {}
  for _, finding in ipairs(sorted) do
    local key
    if grouping == 'file' then
      key = relative(finding.file)
    elseif grouping == 'rule' then
      key = finding.rule .. ' — ' .. finding.message
    else
      key = finding.severity
    end
    if not groups[key] then
      groups[key] = {}
      order[#order + 1] = key
    end
    table.insert(groups[key], finding)
  end

  for _, key in ipairs(order) do
    lines[#lines + 1] = string.format('%s  (%d)', key, #groups[key])
    for _, finding in ipairs(groups[key]) do
      lines[#lines + 1] = string.format(
        '  %-28s %5d  %-7s %s',
        relative(finding.file),
        finding.line or 0,
        finding.severity,
        finding.message
      )
    end
    lines[#lines + 1] = ''
  end
  return lines
end

return M
