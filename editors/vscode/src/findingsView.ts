import * as path from 'path';

import * as vscode from 'vscode';

import { describe } from './diagnostics';
import type { FindingStore } from './store';
import type { Finding, Severity } from './types';

export type Scope = 'file' | 'project';

const SEVERITY_THEME: Record<Severity, { icon: string; colour: string }> = {
  high: { icon: 'flame', colour: 'charts.red' },
  medium: { icon: 'warning', colour: 'charts.yellow' },
  low: { icon: 'info', colour: 'charts.blue' },
};

/**
 * The Findings panel: one row per finding, worst first.
 *
 * Flat rather than a tree. The findings are already ordered by severity, and
 * the two views worth having — this file, or the whole project — are a toggle
 * rather than a hierarchy.
 */
export class FindingsProvider implements vscode.TreeDataProvider<Finding> {
  private readonly emitter = new vscode.EventEmitter<undefined>();
  readonly onDidChangeTreeData = this.emitter.event;

  scope: Scope = 'project';
  private currentFile?: string;

  constructor(private readonly store: FindingStore) {}

  refresh(): void {
    this.emitter.fire(undefined);
  }

  setCurrentFile(fsPath: string | undefined): void {
    if (this.currentFile !== fsPath) {
      this.currentFile = fsPath;
      if (this.scope === 'file') {
        this.refresh();
      }
    }
  }

  getChildren(finding?: Finding): Finding[] {
    if (finding) {
      return [];
    }
    return this.scope === 'file'
      ? this.currentFile
        ? this.store.forFile(this.currentFile)
        : []
      : this.store.all();
  }

  getTreeItem(finding: Finding): vscode.TreeItem {
    const item = new vscode.TreeItem(finding.message, vscode.TreeItemCollapsibleState.None);
    const where =
      this.scope === 'project'
        ? `${workspaceRelative(finding.file)}:${finding.line}`
        : `line ${finding.line}`;
    item.description = `${finding.rule} · ${where}`;
    item.tooltip = describe(finding);
    const theme = SEVERITY_THEME[finding.severity];
    item.iconPath = new vscode.ThemeIcon(theme.icon, new vscode.ThemeColor(theme.colour));
    item.resourceUri = vscode.Uri.file(finding.file);
    item.command = {
      command: 'vscode.open',
      title: 'Open finding',
      arguments: [
        vscode.Uri.file(finding.file),
        {
          selection: new vscode.Range(finding.line - 1, 0, finding.line - 1, 0),
          preview: true,
        } satisfies vscode.TextDocumentShowOptions,
      ],
    };
    return item;
  }

  /** What the panel title says: where we are looking and what is there. */
  describeScope(): string {
    const findings = this.getChildren();
    const where =
      this.scope === 'file'
        ? this.currentFile
          ? path.basename(this.currentFile)
          : 'no file'
        : 'whole project';
    if (findings.length === 0) {
      return `${where} — nothing found`;
    }
    const counts = { high: 0, medium: 0, low: 0 };
    for (const finding of findings) {
      counts[finding.severity] += 1;
    }
    return (
      `${where} — ${findings.length} finding${findings.length === 1 ? '' : 's'} ` +
      `(${counts.high} high, ${counts.medium} medium, ${counts.low} low)`
    );
  }

  dispose(): void {
    this.emitter.dispose();
  }
}

export function workspaceRelative(fsPath: string): string {
  return vscode.workspace.asRelativePath(vscode.Uri.file(fsPath), false);
}
