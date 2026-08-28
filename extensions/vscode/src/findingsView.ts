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
  /** The raw grouping key — unique, unlike the displayed label. */
  key: string;
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
  grouping: Grouping = 'file';
  /** Whether groups start open. */
  expanded = true;
  /**
   * Bumped whenever expand/collapse is asked for.
   *
   * It goes into each group's TreeItem id, and that is what makes the request
   * take effect: VS Code reads `collapsibleState` only the first time it sees
   * an element, and from then on keeps its own expansion state against that
   * id. Repainting the same ids is therefore ignored, so setting `expanded`
   * and firing a refresh looked like it did nothing. A new id is a new
   * element, so the state is read afresh.
   *
   * Only expand/collapse bumps it. An ordinary repaint — a streaming scan
   * fires one every half second — keeps the ids, so whatever the user has
   * opened by hand stays open.
   */
  private generation = 0;
  private currentFile?: string;

  constructor(private readonly store: FindingStore) {}

  refresh(): void {
    this.emitter.fire(undefined);
  }

  /** Expand or collapse every group. */
  setExpanded(expanded: boolean): void {
    this.expanded = expanded;
    this.generation += 1;
    this.refresh();
  }

  /** The id a group renders with — exposed so a test can prove it changes. */
  idFor(key: string): string {
    return `${this.generation}:${this.scope}:${this.grouping}:${key}`;
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
    // Grouping by file while scoped to one file is a single group named after
    // the file you are already looking at: indentation and nothing else.
    if (this.scope === 'file' && this.grouping === 'file') {
      return this.findings();
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
          key: severity,
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
      key,
      label: byFile ? path.basename(key) : `${key} — ${items[0].message}`,
      description: byFile ? `${path.dirname(workspaceRelative(key))} · ${items.length}` : `${items.length}`,
      icon: byFile ? vscode.ThemeIcon.File : severityIcon(items[0].severity),
      resource: byFile ? vscode.Uri.file(key) : undefined,
      children: items,
    }));
  }

  getTreeItem(node: Node): vscode.TreeItem {
    if (isGroup(node)) {
      const item = new vscode.TreeItem(
        node.label,
        this.expanded
          ? vscode.TreeItemCollapsibleState.Expanded
          : vscode.TreeItemCollapsibleState.Collapsed,
      );
      // Keyed on the group key, not the label: grouping by file shows
      // basenames, and two directories can hold the same one.
      item.id = this.idFor(node.key);
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

  /** The hover card, built when it is hovered.
   *
   * A tooltip is a `MarkdownString` assembled from four fields, and the panel
   * renders every visible row on every repaint — which during a streaming scan
   * is twice a second. VS Code asks for this only when the pointer stops. */
  resolveTreeItem(item: vscode.TreeItem, node: Node): vscode.TreeItem {
    if (!isGroup(node)) {
      item.tooltip = describe(node);
    }
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
