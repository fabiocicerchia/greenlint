import * as path from 'path';

import * as vscode from 'vscode';

import type { Settings } from './config';
import { describe } from './diagnostics';
import type { FindingStore } from './store';
import { compareFindings, type Finding, type Severity } from './types';

export type Scope = 'file' | 'project';
export type Grouping = 'severity' | 'file' | 'rule';

const SEVERITY_THEME: Record<Severity, { icon: string; colour: string }> = {
  high: { icon: 'flame', colour: 'charts.red' },
  medium: { icon: 'warning', colour: 'charts.yellow' },
  low: { icon: 'info', colour: 'charts.blue' },
};

type Node = GroupNode | FindingNode;

class GroupNode {
  readonly kind = 'group';
  constructor(
    readonly label: string,
    readonly description: string,
    readonly children: Finding[],
    readonly icon: vscode.ThemeIcon,
    readonly resource?: vscode.Uri,
  ) {}
}

class FindingNode {
  readonly kind = 'finding';
  constructor(
    readonly finding: Finding,
    readonly showFile: boolean,
  ) {}
}

/**
 * The Findings panel.
 *
 * Two axes the user asked for and one they will: scope (this file or the whole
 * project), grouping, and a severity filter. All three are view state — none of
 * them rescans anything, they only re-read what the store already holds.
 */
export class FindingsProvider implements vscode.TreeDataProvider<Node> {
  private readonly emitter = new vscode.EventEmitter<Node | undefined>();
  readonly onDidChangeTreeData = this.emitter.event;

  scope: Scope = 'project';
  grouping: Grouping = 'severity';
  severities: Set<Severity> = new Set<Severity>(['high', 'medium', 'low']);
  private currentFile?: string;

  constructor(
    private readonly store: FindingStore,
    private readonly settings: () => Settings,
  ) {}

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

  /** The findings the current scope and filter select, already ordered. */
  visible(): Finding[] {
    const source =
      this.scope === 'file'
        ? this.currentFile
          ? this.store.forFile(this.currentFile)
          : []
        : this.store.all();
    return source.filter((finding) => this.severities.has(finding.severity)).sort(compareFindings);
  }

  /** What the current scope covers, without any counts — the report adds its own. */
  scopeName(): string {
    if (this.scope === 'project') {
      return 'whole project';
    }
    return this.currentFile ? workspaceRelative(this.currentFile) : 'no file open';
  }

  describeScope(): string {
    const counts = this.store.countsBySeverity(this.visible());
    const where =
      this.scope === 'file'
        ? this.currentFile
          ? path.basename(this.currentFile)
          : 'no file'
        : 'whole project';
    const total = counts.high + counts.medium + counts.low;
    if (total === 0) {
      return `${where} — nothing found`;
    }
    return `${where} — ${total} finding${total === 1 ? '' : 's'} (${counts.high} high, ${counts.medium} medium, ${counts.low} low)`;
  }

  getTreeItem(node: Node): vscode.TreeItem {
    if (node.kind === 'group') {
      const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.Expanded);
      item.description = node.description;
      item.iconPath = node.icon;
      item.resourceUri = node.resource;
      item.contextValue = 'greenlint.group';
      return item;
    }
    const { finding } = node;
    const item = new vscode.TreeItem(finding.message, vscode.TreeItemCollapsibleState.None);
    const where = node.showFile ? `${workspaceRelative(finding.file)}:${finding.line}` : `line ${finding.line}`;
    item.description = `${finding.rule} · ${where}`;
    item.tooltip = describe(finding, this.settings());
    item.iconPath = severityIconPath(finding.severity);
    item.contextValue = 'greenlint.finding';
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

  getChildren(node?: Node): Node[] {
    if (node?.kind === 'finding') {
      return [];
    }
    if (node?.kind === 'group') {
      return node.children.map(
        (finding) => new FindingNode(finding, this.grouping !== 'file' && this.scope === 'project'),
      );
    }
    return this.groups();
  }

  private groups(): Node[] {
    const findings = this.visible();
    if (findings.length === 0) {
      return [];
    }
    if (this.grouping === 'file') {
      return group(findings, (finding) => finding.file).map(
        ([file, items]) =>
          new GroupNode(
            path.basename(file),
            `${path.dirname(workspaceRelative(file))} · ${items.length}`,
            items,
            vscode.ThemeIcon.File,
            vscode.Uri.file(file),
          ),
      );
    }
    if (this.grouping === 'rule') {
      return group(findings, (finding) => finding.rule).map(
        ([rule, items]) =>
          new GroupNode(
            `${rule} — ${items[0].message}`,
            `${items.length}`,
            items,
            severityIconPath(items[0].severity),
          ),
      );
    }
    return (['high', 'medium', 'low'] as Severity[])
      .map((severity) => [severity, findings.filter((f) => f.severity === severity)] as const)
      .filter(([, items]) => items.length > 0)
      .map(
        ([severity, items]) =>
          new GroupNode(severity, `${items.length}`, [...items], severityIconPath(severity)),
      );
  }

  dispose(): void {
    this.emitter.dispose();
  }
}

function severityIconPath(severity: Severity): vscode.ThemeIcon {
  const theme = SEVERITY_THEME[severity];
  return new vscode.ThemeIcon(theme.icon, new vscode.ThemeColor(theme.colour));
}

function group<T>(items: T[], key: (item: T) => string): Array<[string, T[]]> {
  const buckets = new Map<string, T[]>();
  for (const item of items) {
    const bucket = buckets.get(key(item));
    if (bucket) {
      bucket.push(item);
    } else {
      buckets.set(key(item), [item]);
    }
  }
  return [...buckets.entries()];
}

export function workspaceRelative(fsPath: string): string {
  return vscode.workspace.asRelativePath(vscode.Uri.file(fsPath), false);
}
