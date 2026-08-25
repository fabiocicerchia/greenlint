import * as vscode from 'vscode';

import { SEVERITY_LEVELS } from './config';
import type { FindingStore } from './store';
import { type Finding, ruleDocsUrl, type Severity } from './types';

export const SOURCE = 'greenlint';

const SEVERITY_ICON: Record<Severity, string> = {
  high: '$(flame)',
  medium: '$(warning)',
  low: '$(info)',
};

/**
 * The line a finding sits on, squiggled from its first non-whitespace character
 * so the underline traces the code rather than the indentation. Files that are
 * not open get a whole-line range; VS Code clamps it when they are opened.
 */
function rangeFor(finding: Finding, document: vscode.TextDocument | undefined): vscode.Range {
  const line = Math.max(0, finding.line - 1);
  if (!document || line >= document.lineCount) {
    return new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER);
  }
  const textLine = document.lineAt(line);
  const start = textLine.isEmptyOrWhitespace ? 0 : textLine.firstNonWhitespaceCharacterIndex;
  return new vscode.Range(line, start, line, Math.max(start, textLine.text.length));
}

/** One `Uri` per distinct rule and message rather than one per finding:
 * parsing the same URL again for every squiggle in the project is a few
 * thousand identical strings. Keyed on both halves of what builds it, so a
 * greenlint whose wording changed — a contributor editing the rules in the
 * workspace — gets a new entry rather than the old link. */
const docsUri = new Map<string, vscode.Uri>();

function docsTarget(finding: Finding): vscode.Uri {
  const key = `${finding.rule} ${finding.message}`;
  let uri = docsUri.get(key);
  if (!uri) {
    uri = vscode.Uri.parse(ruleDocsUrl(finding));
    docsUri.set(key, uri);
  }
  return uri;
}

/**
 * One file's findings as diagnostics.
 *
 * Per file rather than per finding because the open document is looked up once
 * here: `textDocuments` is a linear scan, and doing it inside the loop made
 * publishing a project's diagnostics cost findings x open editors.
 */
export function toDiagnostics(file: string, findings: readonly Finding[]): vscode.Diagnostic[] {
  const document = findings.length
    ? vscode.workspace.textDocuments.find((doc) => doc.uri.fsPath === file)
    : undefined;
  return findings.map((finding) => {
    const diagnostic = new vscode.Diagnostic(
      rangeFor(finding, document),
      finding.message,
      SEVERITY_LEVELS[finding.severity],
    );
    diagnostic.source = SOURCE;
    // `code.target` makes the rule id in the Problems panel a link to its
    // section of the rules reference — the "why" is the point of the tool, so
    // it should never be more than one click away.
    diagnostic.code = { value: finding.rule, target: docsTarget(finding) };
    return diagnostic;
  });
}

/** The card behind a hover and a panel tooltip: what was found, what to do
 * instead, what it costs. */
export function describe(finding: Finding): vscode.MarkdownString {
  const markdown = new vscode.MarkdownString(undefined, true);
  markdown.isTrusted = true;
  return markdown.appendMarkdown(
    `${SEVERITY_ICON[finding.severity]} **${finding.message}**\n\n` +
      `[${finding.rule}](${ruleDocsUrl(finding)}) · ${finding.severity} severity · greenlint\n\n` +
      `**Do instead:** ${finding.suggestion}\n` +
      (finding.co2e_estimate ? `\n**Rough cost:** ${finding.co2e_estimate}\n` : ''),
  );
}

export class GreenlintHoverProvider implements vscode.HoverProvider {
  constructor(private readonly store: FindingStore) {}

  provideHover(document: vscode.TextDocument, position: vscode.Position): vscode.Hover | undefined {
    const findings = this.store
      .forFile(document.uri.fsPath)
      .filter((finding) => finding.line - 1 === position.line);
    if (findings.length === 0) {
      return undefined;
    }
    return new vscode.Hover(findings.map(describe), document.lineAt(position.line).range);
  }
}
