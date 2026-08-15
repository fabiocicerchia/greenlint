import type { Finding, ScanStats, Severity } from './types';

export interface ReportMeta {
  /** "whole project", "src/db.py" — what the numbers below are about. */
  scopeLabel: string;
  generatedAt: Date;
  version?: string;
  stats?: ScanStats;
  showCo2e: boolean;
  /** Webview: rows link back into the editor. Exported file: they are plain. */
  interactive: boolean;
  /** Required by the webview's content security policy; omitted on export. */
  nonce?: string;
  cspSource?: string;
  /** Paths shown to the reader, keyed by absolute path. */
  relative: (fsPath: string) => string;
}

const SEVERITIES: Severity[] = ['high', 'medium', 'low'];

function bucket(map: Map<string, Finding[]>, key: string): Finding[] {
  let existing = map.get(key);
  if (!existing) {
    existing = [];
    map.set(key, existing);
  }
  return existing;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * The report, as one self-contained document.
 *
 * Styled entirely from VS Code's own theme variables, so in a webview it is the
 * editor's UI rather than a second design sitting inside it — the user's theme,
 * contrast setting and font size all apply without this code knowing which they
 * chose. The same template exports to a standalone file, where none of those
 * variables exist and the fallbacks in each `var()` take over.
 */
export function renderReport(findings: Finding[], meta: ReportMeta): string {
  const counts = { high: 0, medium: 0, low: 0 } as Record<Severity, number>;
  for (const finding of findings) {
    counts[finding.severity] += 1;
  }
  const byRule = new Map<string, Finding[]>();
  const byFile = new Map<string, Finding[]>();
  for (const finding of findings) {
    bucket(byRule, finding.rule).push(finding);
    bucket(byFile, finding.file).push(finding);
  }

  const csp = meta.cspSource
    ? `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${meta.nonce}';">`
    : '';
  const script = meta.nonce ? `<script nonce="${meta.nonce}">${CLIENT_SCRIPT}</script>` : `<script>${CLIENT_SCRIPT}</script>`;

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
${csp}
<title>greenlint report</title>
<style>${STYLES}</style>
</head>
<body data-interactive="${meta.interactive}">
<div class="wrap">
  <header>
    <h1>greenlint report</h1>
    <p class="tagline">${escapeHtml(meta.scopeLabel)} — ${findings.length} finding${findings.length === 1 ? '' : 's'}</p>
    <p class="meta">${escapeHtml(meta.generatedAt.toLocaleString())}${
      meta.version ? ` · greenlint ${escapeHtml(meta.version)}` : ''
    }${renderScanCost(meta.stats)}</p>
  </header>

  <div class="chips">
    ${SEVERITIES.map(
      (severity) =>
        `<button class="chip ${severity}" data-severity="${severity}" aria-pressed="true">
           <span class="count">${counts[severity]}</span> ${severity}
         </button>`,
    ).join('')}
    <input id="filter" type="search" placeholder="Filter by rule, file or message…" autocomplete="off">
  </div>

  ${findings.length === 0 ? emptyState() : ''}
  ${byRule.size > 0 ? renderRuleSummary(byRule) : ''}
  ${[...byFile.entries()].map(([file, items]) => renderFile(file, items, meta)).join('\n')}

  <footer>
    Every finding says why it wastes energy and what to do instead.
    CO2e figures are order-of-magnitude steers, not measurements —
    see <span class="mono">docs/architecture.md</span>.
  </footer>
</div>
${script}
</body>
</html>`;
}

function emptyState(): string {
  return `<section class="card empty">
    <h2>Nothing found</h2>
    <p>No energy-wasteful patterns matched here. That is the good outcome.</p>
  </section>`;
}

function renderScanCost(stats?: ScanStats): string {
  if (!stats) {
    return '';
  }
  const reused = stats.reusedFromStat + stats.reusedFromHash;
  return ` · ${stats.files} files in ${stats.ms} ms (${stats.scanned} scanned, ${reused} reused from cache, ${stats.skipped} skipped)`;
}

function renderRuleSummary(byRule: Map<string, Finding[]>): string {
  const rows = [...byRule.entries()]
    .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
    .map(([rule, items]) => {
      const first = items[0];
      return `<tr data-severity="${first.severity}"
              data-haystack="${escapeHtml(`${rule} ${first.message}`.toLowerCase())}">
        <td class="mono rule"><span class="dot ${first.severity}"></span>${escapeHtml(rule)}</td>
        <td>${escapeHtml(first.message)}</td>
        <td class="num">${items.length}</td>
      </tr>`;
    })
    .join('\n');
  return `<section class="card">
    <h2>By rule</h2>
    <table class="summary">
      <thead><tr><th>Rule</th><th>Message</th><th class="num">Count</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </section>`;
}

function renderFile(file: string, findings: Finding[], meta: ReportMeta): string {
  const label = escapeHtml(meta.relative(file));
  const rows = findings
    .map((finding) => {
      const haystack = escapeHtml(
        `${finding.rule} ${finding.message} ${finding.suggestion} ${meta.relative(file)}`.toLowerCase(),
      );
      const co2e =
        meta.showCo2e && finding.co2e_estimate
          ? `<p class="co2e">~ ${escapeHtml(finding.co2e_estimate)}</p>`
          : '';
      return `<li class="finding" data-severity="${finding.severity}" data-haystack="${haystack}"
             data-file="${escapeHtml(file)}" data-line="${finding.line}"
             ${meta.interactive ? 'tabindex="0" role="link"' : ''}>
        <div class="line">
          <span class="dot ${finding.severity}"></span>
          <span class="mono where">${label}:${finding.line}</span>
          <span class="badge ${finding.severity}">${escapeHtml(finding.rule)}</span>
          <span class="msg">${escapeHtml(finding.message)}</span>
        </div>
        <p class="suggestion">↳ ${escapeHtml(finding.suggestion)}</p>
        ${co2e}
      </li>`;
    })
    .join('\n');
  return `<section class="card file" data-haystack="${escapeHtml(label.toLowerCase())}">
    <h2 class="mono">${label} <span class="pill">${findings.length}</span></h2>
    <ul class="findings">${rows}</ul>
  </section>`;
}

/* Every colour, font and radius here is a VS Code theme variable, so the report
   is the editor's UI rather than a second design living inside it: it follows
   the user's theme, contrast setting and font size without knowing which one
   they picked.
   The second value in each `var()` is the fallback for the exported file, which
   has to stand on its own in a browser where none of those variables exist —
   hence the light/dark pair below, which the webview never reaches. */
const STYLES = `
:root{
  --fg:var(--vscode-foreground,#1f2328);
  --bg:var(--vscode-editor-background,#ffffff);
  --muted:var(--vscode-descriptionForeground,#57606a);
  --card:var(--vscode-editorWidget-background,#f6f8fa);
  --border:var(--vscode-widget-border,#d0d7de);
  --link:var(--vscode-textLink-foreground,#0969da);
  --hover:var(--vscode-list-hoverBackground,rgba(0,0,0,.05));
  --badge-bg:var(--vscode-badge-background,#0969da);
  --badge-fg:var(--vscode-badge-foreground,#ffffff);
  --code:var(--vscode-textPreformat-foreground,#0550ae);
  --high:var(--vscode-editorError-foreground,#cf222e);
  --medium:var(--vscode-editorWarning-foreground,#9a6700);
  --low:var(--vscode-editorInfo-foreground,#0969da);
  --font:var(--vscode-font-family,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif);
  --mono:var(--vscode-editor-font-family,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace);
}
@media (prefers-color-scheme: dark){
  :root{
    --fg:var(--vscode-foreground,#e6edf3);
    --bg:var(--vscode-editor-background,#0d1117);
    --muted:var(--vscode-descriptionForeground,#8b949e);
    --card:var(--vscode-editorWidget-background,#161b22);
    --border:var(--vscode-widget-border,#30363d);
    --link:var(--vscode-textLink-foreground,#4493f8);
    --hover:var(--vscode-list-hoverBackground,rgba(255,255,255,.06));
    --code:var(--vscode-textPreformat-foreground,#79c0ff);
    --high:var(--vscode-editorError-foreground,#f85149);
    --medium:var(--vscode-editorWarning-foreground,#d29922);
    --low:var(--vscode-editorInfo-foreground,#4493f8);
  }
}
*{box-sizing:border-box}
body{margin:0;padding:1.25rem;background:var(--bg);color:var(--fg);
  font-family:var(--font);font-size:var(--vscode-font-size,13px);line-height:1.5}
.wrap{max-width:1100px;margin:0 auto}
h1{font-size:1.3rem;font-weight:600;margin:0 0 .2rem}
.tagline{margin:0 0 .15rem;font-weight:600}
.meta{color:var(--muted);font-size:.9em;margin:0 0 1rem}
.chips{display:flex;gap:.4rem;flex-wrap:wrap;align-items:center;margin:0 0 1rem}
.chip{cursor:pointer;font-family:inherit;font-size:.9em;
  color:var(--vscode-button-secondaryForeground,var(--fg));
  background:var(--vscode-button-secondaryBackground,var(--card));
  border:1px solid var(--border);border-radius:4px;padding:.25rem .6rem}
.chip:hover{background:var(--vscode-button-secondaryHoverBackground,var(--hover))}
.chip[aria-pressed="false"]{opacity:.45}
.chip .count{font-weight:700;margin-right:.3rem}
#filter{flex:1;min-width:12rem;font-family:inherit;font-size:.95em;
  color:var(--vscode-input-foreground,var(--fg));
  background:var(--vscode-input-background,var(--card));
  border:1px solid var(--vscode-input-border,var(--border));border-radius:2px;padding:.25rem .5rem}
#filter::placeholder{color:var(--vscode-input-placeholderForeground,var(--muted))}
#filter:focus{outline:1px solid var(--vscode-focusBorder,var(--link));outline-offset:-1px}
.card{background:var(--card);border:1px solid var(--border);border-radius:4px;
  padding:.75rem 1rem;margin:0 0 .75rem}
.card h2{font-size:1em;margin:0 0 .6rem;font-weight:600;display:flex;align-items:center;gap:.5rem}
.pill{font-size:.85em;font-weight:600;color:var(--badge-fg);background:var(--badge-bg);
  border-radius:10px;padding:0 .45rem}
.mono{font-family:var(--mono)}
table.summary{width:100%;border-collapse:collapse}
table.summary th{text-align:left;color:var(--muted);font-weight:600;font-size:.9em;
  padding:0 .5rem .3rem 0;border-bottom:1px solid var(--border)}
table.summary td{padding:.3rem .5rem .3rem 0;border-bottom:1px solid var(--border);vertical-align:top}
table.summary tr:last-child td{border-bottom:0}
table.summary .num,table.summary th.num{text-align:right;padding-right:0}
table.summary .dot{margin-right:.4rem}
table.summary .rule{color:var(--code)}
ul.findings{list-style:none;margin:0;padding:0}
li.finding{padding:.4rem 0;border-bottom:1px solid var(--border)}
li.finding:last-child{border-bottom:0}
body[data-interactive="true"] li.finding{cursor:pointer;border-radius:3px;
  padding-left:.4rem;padding-right:.4rem;margin:0 -.4rem}
body[data-interactive="true"] li.finding:hover{background:var(--hover)}
body[data-interactive="true"] li.finding:focus{outline:1px solid var(--vscode-focusBorder,var(--link));outline-offset:-1px}
.line{display:flex;align-items:baseline;gap:.5rem;flex-wrap:wrap}
.where{color:var(--muted);font-size:.9em}
.msg{font-weight:600}
.badge{font-size:.85em;font-weight:600;border-radius:3px;padding:0 .35rem;font-family:var(--mono)}
.badge.high{color:var(--high);border:1px solid var(--high)}
.badge.medium{color:var(--medium);border:1px solid var(--medium)}
.badge.low{color:var(--low);border:1px solid var(--low)}
.dot{width:.5em;height:.5em;border-radius:50%;display:inline-block;flex:none}
.dot.high{background:var(--high)}.dot.medium{background:var(--medium)}.dot.low{background:var(--low)}
.suggestion{margin:.15rem 0 0 1rem;color:var(--muted)}
.co2e{margin:.1rem 0 0 1rem;color:var(--muted);font-size:.9em;opacity:.85}
footer{color:var(--muted);font-size:.9em;margin-top:1.5rem;border-top:1px solid var(--border);padding-top:.75rem}
.hidden{display:none}
`;

/* Filtering is client-side: the report is a single static document, and
   re-rendering it from the extension on every keystroke would be the same
   mistake the scanner goes to some trouble to avoid. */
const CLIENT_SCRIPT = `
(function () {
  var api = typeof acquireVsCodeApi === 'function' ? acquireVsCodeApi() : null;
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
  var filter = document.getElementById('filter');
  var off = {};

  function apply() {
    var needle = (filter.value || '').trim().toLowerCase();
    Array.prototype.forEach.call(document.querySelectorAll('[data-haystack]'), function (row) {
      var severity = row.getAttribute('data-severity');
      var hidden = (severity && off[severity]) ||
                   (needle && row.getAttribute('data-haystack').indexOf(needle) === -1);
      row.classList.toggle('hidden', !!hidden);
    });
    Array.prototype.forEach.call(document.querySelectorAll('section.file'), function (section) {
      var shown = section.querySelectorAll('li.finding:not(.hidden)').length;
      section.classList.toggle('hidden', shown === 0);
    });
  }

  chips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      var severity = chip.getAttribute('data-severity');
      off[severity] = !off[severity];
      chip.setAttribute('aria-pressed', off[severity] ? 'false' : 'true');
      apply();
    });
  });
  filter.addEventListener('input', apply);

  if (api) {
    function open(row) {
      api.postMessage({
        type: 'open',
        file: row.getAttribute('data-file'),
        line: parseInt(row.getAttribute('data-line'), 10)
      });
    }
    document.addEventListener('click', function (event) {
      var row = event.target.closest ? event.target.closest('li.finding') : null;
      if (row) { open(row); }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') { return; }
      var row = event.target.closest ? event.target.closest('li.finding') : null;
      if (row) { open(row); }
    });
  }
})();
`;
