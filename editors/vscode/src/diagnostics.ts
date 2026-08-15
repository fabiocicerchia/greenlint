import * as vscode from 'vscode';

import type { Settings } from './config';
import type { FindingStore } from './store';
import { type Finding, ruleDocsUrl, type Severity } from './types';

export const SOURCE = 'greenlint';

const SEVERITY_ICON: Record<Severity, string> = { high: '$(flame)', medium: '$(warning)', low: '$(info)' };

/** Diagnostics carry the finding so hovers and quick fixes need no second lookup. */
interface GreenlintDiagnostic extends vscode.Diagnostic {
  finding?: Finding;
}

export function severityIcon(severity: Severity): string {
  return SEVERITY_ICON[severity];
}

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

export function toDiagnostic(finding: Finding, settings: Settings): vscode.Diagnostic {
  const diagnostic: GreenlintDiagnostic = new vscode.Diagnostic(
    rangeFor(finding),
    finding.message,
    settings.severityLevels[finding.severity],
  );
  diagnostic.source = SOURCE;
  // `code.target` makes the rule id in the Problems panel a link to its section
  // of the rules reference — the "why" is the point of the tool, so it should
  // never be more than one click away.
  diagnostic.code = { value: finding.rule, target: vscode.Uri.parse(ruleDocsUrl(finding)) };
  diagnostic.finding = finding;
  return diagnostic;
}

/** The hover/tooltip card: what was found, what to do instead, what it costs. */
export function describe(finding: Finding, settings: Settings): vscode.MarkdownString {
  const markdown = new vscode.MarkdownString(undefined, true);
  markdown.isTrusted = true;
  markdown.supportThemeIcons = true;
  markdown.appendMarkdown(
    `${severityIcon(finding.severity)} **${finding.message}**\n\n` +
      `[${finding.rule}](${ruleDocsUrl(finding)}) · ${finding.severity} severity · greenlint\n\n` +
      `**Do instead:** ${finding.suggestion}\n`,
  );
  if (settings.showCo2eEstimate && finding.co2e_estimate) {
    markdown.appendMarkdown(`\n**Rough cost:** ${finding.co2e_estimate}\n`);
  }
  return markdown;
}

export class GreenlintHoverProvider implements vscode.HoverProvider {
  constructor(
    private readonly store: FindingStore,
    private readonly settings: () => Settings,
  ) {}

  provideHover(document: vscode.TextDocument, position: vscode.Position): vscode.Hover | undefined {
    const findings = this.store
      .forFile(document.uri.fsPath)
      .filter((finding) => finding.line - 1 === position.line);
    if (findings.length === 0) {
      return undefined;
    }
    const settings = this.settings();
    const contents = findings.map((finding) => describe(finding, settings));
    return new vscode.Hover(contents, document.lineAt(position.line).range);
  }
}

/**
 * Quick fixes. greenlint has no inline suppression comment, so the only
 * mechanical action available is switching the rule off for the workspace —
 * offered explicitly rather than hidden, since it is a real decision.
 */
export class GreenlintCodeActionProvider implements vscode.CodeActionProvider {
  static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

  provideCodeActions(
    _document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext,
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];
    const seen = new Set<string>();
    for (const diagnostic of context.diagnostics) {
      const finding = (diagnostic as GreenlintDiagnostic).finding;
      if (!finding || seen.has(finding.rule)) {
        continue;
      }
      seen.add(finding.rule);
      const disable = new vscode.CodeAction(
        `greenlint: disable ${finding.rule} for this workspace`,
        vscode.CodeActionKind.QuickFix,
      );
      disable.diagnostics = [diagnostic];
      disable.command = {
        command: 'greenlint.disableRule',
        title: 'Disable rule',
        arguments: [finding.rule],
      };
      actions.push(disable);
      const explain = new vscode.CodeAction(
        `greenlint: why is ${finding.rule} wasteful?`,
        vscode.CodeActionKind.QuickFix,
      );
      explain.command = {
        command: 'vscode.open',
        title: 'Open rule reference',
        arguments: [vscode.Uri.parse(ruleDocsUrl(finding))],
      };
      actions.push(explain);
    }
    return actions;
  }
}
