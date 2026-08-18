import type { Finding, ScanStats } from './types';

export interface ReportMeta {
  /** "whole project", "src/db.py" — what the numbers below are about. */
  scopeLabel: string;
  generatedAt: Date;
  version?: string;
  stats?: ScanStats;
  /** Paths shown to the reader, keyed by absolute path. */
  relative: (fsPath: string) => string;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * The report, as one static document.
 *
 * Styled entirely from VS Code's own theme variables, so it is the editor's UI
 * rather than a second design sitting inside it — the user's theme, contrast
 * setting and font size all apply without this code knowing which they chose.
 * No script: navigating to a finding is what the Findings panel and the
 * Problems panel are for, and a report that cannot run anything needs no
 * content-security dance to be safe.
 */
export function renderReport(findings: Finding[], meta: ReportMeta): string {
  const byFile = new Map<string, Finding[]>();
  const byRule = new Map<string, Finding[]>();
  for (const finding of findings) {
    bucket(byFile, finding.file).push(finding);
    bucket(byRule, finding.rule).push(finding);
  }
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
<title>greenlint report</title>
<style>${STYLES}</style>
</head>
<body>
<div class="wrap">
  <h1>greenlint report</h1>
  <p class="tagline">${escapeHtml(meta.scopeLabel)} — ${findings.length} finding${
    findings.length === 1 ? '' : 's'
  }</p>
  <p class="meta">${escapeHtml(meta.generatedAt.toLocaleString())}${
    meta.version ? ` · greenlint ${escapeHtml(meta.version)}` : ''
  }${scanCost(meta.stats)}</p>
  ${findings.length === 0 ? '<section class="card"><h2>Nothing found</h2></section>' : ''}
  ${byRule.size > 0 ? ruleSummary(byRule) : ''}
  ${[...byFile.entries()].map(([file, items]) => fileSection(file, items, meta)).join('\n')}
  <footer>
    Every finding says why it wastes energy and what to do instead. CO2e figures
    are order-of-magnitude steers, not measurements.
  </footer>
</div>
</body>
</html>`;
}

function bucket(map: Map<string, Finding[]>, key: string): Finding[] {
  let existing = map.get(key);
  if (!existing) {
    existing = [];
    map.set(key, existing);
  }
  return existing;
}

function scanCost(stats?: ScanStats): string {
  if (!stats) {
    return '';
  }
  const reused = stats.reusedFromStat + stats.reusedFromHash;
  return ` · ${stats.files} files in ${stats.ms} ms (${stats.scanned} scanned, ${reused} reused from cache, ${stats.skipped} skipped)`;
}

function ruleSummary(byRule: Map<string, Finding[]>): string {
  const rows = [...byRule.entries()]
    .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
    .map(
      ([rule, items]) => `<tr>
        <td class="mono rule"><span class="dot ${items[0].severity}"></span>${escapeHtml(rule)}</td>
        <td>${escapeHtml(items[0].message)}</td>
        <td class="num">${items.length}</td>
      </tr>`,
    )
    .join('\n');
  return `<section class="card">
    <h2>By rule</h2>
    <table><thead><tr><th>Rule</th><th>Message</th><th class="num">Count</th></tr></thead>
    <tbody>${rows}</tbody></table>
  </section>`;
}

function fileSection(file: string, findings: Finding[], meta: ReportMeta): string {
  const label = escapeHtml(meta.relative(file));
  const rows = findings
    .map(
      (finding) => `<li>
        <div class="line">
          <span class="dot ${finding.severity}"></span>
          <span class="mono where">${label}:${finding.line}</span>
          <span class="badge ${finding.severity}">${escapeHtml(finding.rule)}</span>
          <span class="msg">${escapeHtml(finding.message)}</span>
        </div>
        <p class="suggestion">↳ ${escapeHtml(finding.suggestion)}</p>
        ${finding.co2e_estimate ? `<p class="co2e">~ ${escapeHtml(finding.co2e_estimate)}</p>` : ''}
      </li>`,
    )
    .join('\n');
  return `<section class="card">
    <h2 class="mono">${label} <span class="pill">${findings.length}</span></h2>
    <ul>${rows}</ul>
  </section>`;
}

/* Every colour, font and radius is a VS Code theme variable, so the report
   follows the editor's theme without knowing which one it is. */
const STYLES = `
:root{
  --fg:var(--vscode-foreground,#1f2328);
  --bg:var(--vscode-editor-background,#fff);
  --muted:var(--vscode-descriptionForeground,#57606a);
  --card:var(--vscode-editorWidget-background,#f6f8fa);
  --border:var(--vscode-widget-border,#d0d7de);
  --badge-bg:var(--vscode-badge-background,#0969da);
  --badge-fg:var(--vscode-badge-foreground,#fff);
  --code:var(--vscode-textPreformat-foreground,#0550ae);
  --high:var(--vscode-editorError-foreground,#cf222e);
  --medium:var(--vscode-editorWarning-foreground,#9a6700);
  --low:var(--vscode-editorInfo-foreground,#0969da);
  --mono:var(--vscode-editor-font-family,ui-monospace,SFMono-Regular,Menlo,monospace);
}
@media (prefers-color-scheme: dark){
  :root{
    --fg:var(--vscode-foreground,#e6edf3);
    --bg:var(--vscode-editor-background,#0d1117);
    --muted:var(--vscode-descriptionForeground,#8b949e);
    --card:var(--vscode-editorWidget-background,#161b22);
    --border:var(--vscode-widget-border,#30363d);
    --code:var(--vscode-textPreformat-foreground,#79c0ff);
    --high:var(--vscode-editorError-foreground,#f85149);
    --medium:var(--vscode-editorWarning-foreground,#d29922);
    --low:var(--vscode-editorInfo-foreground,#4493f8);
  }
}
*{box-sizing:border-box}
body{margin:0;padding:1.25rem;background:var(--bg);color:var(--fg);line-height:1.5;
  font-family:var(--vscode-font-family,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif);
  font-size:var(--vscode-font-size,13px)}
.wrap{max-width:1100px;margin:0 auto}
h1{font-size:1.3rem;font-weight:600;margin:0 0 .2rem}
.tagline{margin:0 0 .15rem;font-weight:600}
.meta{color:var(--muted);font-size:.9em;margin:0 0 1rem}
.card{background:var(--card);border:1px solid var(--border);border-radius:4px;
  padding:.75rem 1rem;margin:0 0 .75rem}
.card h2{font-size:1em;margin:0 0 .6rem;font-weight:600;display:flex;align-items:center;gap:.5rem}
.pill{font-size:.85em;font-weight:600;color:var(--badge-fg);background:var(--badge-bg);
  border-radius:10px;padding:0 .45rem}
.mono{font-family:var(--mono)}
table{width:100%;border-collapse:collapse}
th{text-align:left;color:var(--muted);font-weight:600;font-size:.9em;
  padding:0 .5rem .3rem 0;border-bottom:1px solid var(--border)}
td{padding:.3rem .5rem .3rem 0;border-bottom:1px solid var(--border);vertical-align:top}
tr:last-child td{border-bottom:0}
.num,th.num{text-align:right;padding-right:0}
.rule{color:var(--code)}
td .dot{margin-right:.4rem}
ul{list-style:none;margin:0;padding:0}
li{padding:.4rem 0;border-bottom:1px solid var(--border)}
li:last-child{border-bottom:0}
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
footer{color:var(--muted);font-size:.9em;margin-top:1.5rem;border-top:1px solid var(--border);
  padding-top:.75rem}
`;
