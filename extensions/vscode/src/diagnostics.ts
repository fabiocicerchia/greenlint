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
function rangeFor(finding: Finding): vscode.Range {
  const line = Math.max(0, finding.line - 1);
  const document = vscode.workspace.textDocuments.find((doc) => doc.uri.fsPath === finding.file);
  if (!document || line >= document.lineCount) {
    return new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER);
  }
  const textLine = document.lineAt(line);
  const start = textLine.isEmptyOrWhitespace ? 0 : textLine.firstNonWhitespaceCharacterIndex;
  return new vscode.Range(line, start, line, Math.max(start, textLine.text.length));
}

export function toDiagnostic(finding: Finding): vscode.Diagnostic {
  const diagnostic = new vscode.Diagnostic(
    rangeFor(finding),
    finding.message,
    SEVERITY_LEVELS[finding.severity],
  );
  diagnostic.source = SOURCE;
  // `code.target` makes the rule id in the Problems panel a link to its section
  // of the rules reference — the "why" is the point of the tool, so it should
  // never be more than one click away.
  diagnostic.code = { value: finding.rule, target: vscode.Uri.parse(ruleDocsUrl(finding)) };
  return diagnostic;
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
