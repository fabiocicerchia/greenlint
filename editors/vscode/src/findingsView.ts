import * as path from 'path';

import * as vscode from 'vscode';

import { describe } from './diagnostics';
import type { FindingStore } from './store';
import type { Finding, Severity } from './types';

export type Scope = 'file' | 'project';
export type Grouping = 'severity' | 'file' | 'rule';

const SEVERITY_THEME: Record<Severity, { icon: string; colour: string }> = {
  high: { icon: 'flame', colour: 'charts.red' },
  medium: { icon: 'warning', colour: 'charts.yellow' },
  low: { icon: 'info', colour: 'charts.blue' },
};

interface Group {
  label: string;
  description: string;
  icon: vscode.ThemeIcon;
  resource?: vscode.Uri;
  children: Finding[];
}

type Node = Group | Finding;

const isGroup = (node: Node): node is Group => 'children' in node;

function severityIcon(severity: Severity): vscode.ThemeIcon {
  const theme = SEVERITY_THEME[severity];
  return new vscode.ThemeIcon(theme.icon, new vscode.ThemeColor(theme.colour));
}

/** The Findings panel: two scopes — this file or the whole project — and three
 * ways to group what is in them. */
export class FindingsProvider implements vscode.TreeDataProvider<Node> {
  private readonly emitter = new vscode.EventEmitter<undefined>();
  readonly onDidChangeTreeData = this.emitter.event;

  scope: Scope = 'project';
  grouping: Grouping = 'severity';
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

  /** The findings the current scope selects, already ordered worst-first. */
  findings(): Finding[] {
    if (this.scope === 'project') {
      return this.store.all();
    }
    return this.currentFile ? this.store.forFile(this.currentFile) : [];
  }

  getChildren(node?: Node): Node[] {
    if (node) {
      return isGroup(node) ? node.children : [];
    }
    return this.groups();
  }

  private groups(): Group[] {
    const findings = this.findings();
    if (this.grouping === 'severity') {
      return (['high', 'medium', 'low'] as Severity[])
        .map((severity) => ({ severity, items: findings.filter((f) => f.severity === severity) }))
        .filter(({ items }) => items.length > 0)
        .map(({ severity, items }) => ({
          label: severity,
          description: `${items.length}`,
          icon: severityIcon(severity),
          children: items,
        }));
    }
    const byFile = this.grouping === 'file';
    const groups = new Map<string, Finding[]>();
    for (const finding of findings) {
      const key = byFile ? finding.file : finding.rule;
      const bucket = groups.get(key);
      if (bucket) {
        bucket.push(finding);
      } else {
        groups.set(key, [finding]);
      }
    }
    return [...groups.entries()].map(([key, items]) => ({
      label: byFile ? path.basename(key) : `${key} — ${items[0].message}`,
      description: byFile ? `${path.dirname(workspaceRelative(key))} · ${items.length}` : `${items.length}`,
      icon: byFile ? vscode.ThemeIcon.File : severityIcon(items[0].severity),
      resource: byFile ? vscode.Uri.file(key) : undefined,
      children: items,
    }));
  }

  getTreeItem(node: Node): vscode.TreeItem {
    if (isGroup(node)) {
      const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.Expanded);
      item.description = node.description;
      item.iconPath = node.icon;
      item.resourceUri = node.resource;
      return item;
    }
    const item = new vscode.TreeItem(node.message, vscode.TreeItemCollapsibleState.None);
    // The path is redundant when the group already is the file.
    const where =
      this.grouping === 'file' || this.scope === 'file'
        ? `line ${node.line}`
        : `${workspaceRelative(node.file)}:${node.line}`;
    item.description = `${node.rule} · ${where}`;
    item.tooltip = describe(node);
    item.iconPath = severityIcon(node.severity);
    item.resourceUri = vscode.Uri.file(node.file);
    item.command = {
      command: 'vscode.open',
      title: 'Open finding',
      arguments: [
        vscode.Uri.file(node.file),
        {
          selection: new vscode.Range(node.line - 1, 0, node.line - 1, 0),
          preview: true,
        } satisfies vscode.TextDocumentShowOptions,
      ],
    };
    return item;
  }

  /** What the panel title says: where we are looking and what is there. */
  describeScope(): string {
    const findings = this.findings();
    const where =
      this.scope === 'file'
        ? this.currentFile
          ? path.basename(this.currentFile)
          : 'no file'
        : 'whole project';
    if (findings.length === 0) {
      return `${where} — nothing found`;
    }
    const counts = countBySeverity(findings);
    return (
      `${where} — ${findings.length} finding${findings.length === 1 ? '' : 's'} ` +
      `(${counts.high} high, ${counts.medium} medium, ${counts.low} low)`
    );
  }

  dispose(): void {
    this.emitter.dispose();
  }
}

export function countBySeverity(findings: Finding[]): Record<Severity, number> {
  const counts: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
  for (const finding of findings) {
    counts[finding.severity] += 1;
  }
  return counts;
}

export function workspaceRelative(fsPath: string): string {
  return vscode.workspace.asRelativePath(vscode.Uri.file(fsPath), false);
}
