import * as path from 'path';

import * as vscode from 'vscode';

import { readSettings, requiresRestart } from './config';
import { GreenlintHoverProvider, SOURCE, toDiagnostic } from './diagnostics';
import { ScanServer } from './engine';
import { editorExcludeGlobs } from './excludes';
import {
  countBySeverity,
  FindingsProvider,
  type Grouping,
  type Scope,
  workspaceRelative,
} from './findingsView';
import { renderReport } from './report';
import { FindingStore } from './store';
import type { ScanStats, ScanSummary } from './types';

/** External changes are batched: a `git checkout` touches hundreds of files,
 * and scanning each one as its event lands is the thundering herd this whole
 * extension is built to avoid. */
const EXTERNAL_CHANGE_DEBOUNCE_MS = 1_500;
/** Past this many changed files, one project scan is cheaper than the batch —
 * it walks with the stat cache and only reads what actually changed. */
const BATCH_TO_PROJECT_SCAN = 50;

let controller: Controller | undefined;

export function activate(context: vscode.ExtensionContext): void {
  controller = new Controller(context);
  context.subscriptions.push(controller);
  void controller.start();
}

export function deactivate(): void {
  controller?.dispose();
  controller = undefined;
}

class Controller implements vscode.Disposable {
  private settings = readSettings();
  private readonly log = vscode.window.createOutputChannel('greenlint');
  private readonly diagnostics = vscode.languages.createDiagnosticCollection(SOURCE);
  private readonly store = new FindingStore();
  private readonly server: ScanServer;
  private readonly findings = new FindingsProvider(this.store);
  private readonly tree: vscode.TreeView<unknown>;
  private readonly status = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    50,
  );
  private readonly disposables: vscode.Disposable[] = [];

  private readonly debouncers = new Map<string, NodeJS.Timeout>();
  private readonly pendingExternal = new Set<string>();
  private externalTimer?: NodeJS.Timeout;
  private reportPanel?: vscode.WebviewPanel;
  private scannableExtensions?: Set<string>;
  private lastStats?: ScanStats;
  private lastSummary?: ScanSummary;
  private lastErrorShown?: string;
  private appliedExcludes = '';
  private scanning = false;

  constructor(private readonly context: vscode.ExtensionContext) {
    this.server = new ScanServer(
      context.asAbsolutePath(path.join('server', 'greenlint_server.py')),
      this.settings,
      this.log,
    );
    this.findings.scope = context.workspaceState.get<Scope>('scope', 'project');
    // By file, like the sibling extensions: "which of my files is this in" is
    // the first question, and severity is already the order within each group.
    this.findings.grouping = context.workspaceState.get<Grouping>('grouping', 'file');
    this.tree = vscode.window.createTreeView('greenlint.findings', {
      treeDataProvider: this.findings,
    });
    this.status.command = 'greenlint.findings.focus';
    this.status.name = 'greenlint';
  }

  async start(): Promise<void> {
    this.register();
    void vscode.commands.executeCommand('setContext', 'greenlint.scope', this.findings.scope);
    void vscode.commands.executeCommand('setContext', 'greenlint.expanded', this.findings.expanded);
    this.findings.setCurrentFile(vscode.window.activeTextEditor?.document.uri.fsPath);
    this.repaint();
    if (!this.settings.enable) {
      return;
    }
    if (this.settings.scanProjectOnStartup) {
      await this.scanProject();
    }
    for (const editor of vscode.window.visibleTextEditors) {
      this.schedule(editor.document, 0);
    }
  }

  dispose(): void {
    for (const timer of this.debouncers.values()) {
      clearTimeout(timer);
    }
    clearTimeout(this.externalTimer);
    this.reportPanel?.dispose();
    vscode.Disposable.from(...this.disposables).dispose();
    this.tree.dispose();
    this.status.dispose();
    this.diagnostics.dispose();
    this.findings.dispose();
    this.store.dispose();
    this.server.dispose();
    this.log.dispose();
  }

  // --- registration -----------------------------------------------------

  private register(): void {
    const watcher = vscode.workspace.createFileSystemWatcher('**/*');
    const config = vscode.workspace.createFileSystemWatcher('**/.greenlint.toml');
    const command = (name: string, run: () => unknown) =>
      vscode.commands.registerCommand(name, run);

    this.disposables.push(
      command('greenlint.scanFile', () => {
        const editor = vscode.window.activeTextEditor;
        return editor && this.scanDocument(editor.document);
      }),
      command('greenlint.scanProject', () => this.scanProject()),
      command('greenlint.showReport', () => this.showReport()),
      command('greenlint.showScopeFile', () => this.setScope('file')),
      command('greenlint.showScopeProject', () => this.setScope('project')),
      command('greenlint.setGrouping', () => this.pickGrouping()),
      command('greenlint.cancelScan', () => this.server.cancelProjectScan()),
      command('greenlint.writeBaseline', () => this.writeBaseline()),
      command('greenlint.expandAll', () => this.setExpanded(true)),
      command('greenlint.collapseAll', () => this.setExpanded(false)),
      command('greenlint.showOutput', () => this.log.show(true)),
      command('greenlint.restartServer', async () => {
        await this.server.restart();
        this.appliedExcludes = '';
        await this.scanProject();
      }),

      vscode.languages.registerHoverProvider(
        { scheme: 'file' },
        new GreenlintHoverProvider(this.store),
      ),

      this.store.onDidChange((files) => this.repaint(files)),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (
          event.affectsConfiguration('greenlint') ||
          // Not greenlint's own settings, but they decide what it walks.
          event.affectsConfiguration('files.exclude') ||
          event.affectsConfiguration('search.exclude')
        ) {
          void this.reconfigure();
        }
      }),
      vscode.workspace.onDidChangeTextDocument((event) => {
        if (this.settings.run === 'onType') {
          this.schedule(event.document, this.settings.debounceMs);
        }
      }),
      // A save makes the buffer and the file identical, so this costs a hash
      // check rather than a scan — but it is what keeps the project view honest
      // for a file that was never opened.
      vscode.workspace.onDidSaveTextDocument((document) => this.schedule(document, 0)),
      vscode.workspace.onDidOpenTextDocument((document) => this.schedule(document, 0)),
      vscode.workspace.onDidCloseTextDocument((document) =>
        this.debouncers.delete(document.uri.toString()),
      ),
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        this.findings.setCurrentFile(editor?.document.uri.fsPath);
        this.repaint();
        if (editor) {
          this.schedule(editor.document, 0);
        }
      }),

      watcher,
      config,
      watcher.onDidChange((uri) => this.queueExternal(uri)),
      watcher.onDidCreate((uri) => this.queueExternal(uri)),
      watcher.onDidDelete((uri) => {
        this.store.setFile(uri.fsPath, []);
        void this.server.invalidate([uri.fsPath]);
      }),
      // A config change rewrites what every cached finding means, so it drops
      // the lot rather than working out which rules moved.
      ...['onDidChange', 'onDidCreate', 'onDidDelete'].map((event) =>
        (config[event as 'onDidChange'] as typeof config.onDidChange)(() =>
          void this.reconfigure(),
        ),
      ),
    );
  }

  // --- scheduling -------------------------------------------------------

  private schedule(document: vscode.TextDocument, delay: number): void {
    if (!this.settings.enable || this.settings.run === 'manual' || !this.isScannable(document.uri)) {
      return;
    }
    const key = document.uri.toString();
    clearTimeout(this.debouncers.get(key));
    this.debouncers.set(
      key,
      setTimeout(() => {
        this.debouncers.delete(key);
        void this.scanDocument(document);
      }, delay),
    );
  }

  private queueExternal(uri: vscode.Uri): void {
    if (!this.isScannable(uri)) {
      return;
    }
    this.pendingExternal.add(uri.fsPath);
    clearTimeout(this.externalTimer);
    this.externalTimer = setTimeout(() => void this.flushExternal(), EXTERNAL_CHANGE_DEBOUNCE_MS);
  }

  private async flushExternal(): Promise<void> {
    const paths = [...this.pendingExternal];
    this.pendingExternal.clear();
    if (paths.length === 0 || !this.settings.enable) {
      return;
    }
    await this.server.invalidate(paths);
    if (paths.length >= BATCH_TO_PROJECT_SCAN) {
      this.log.appendLine(`[greenlint] ${paths.length} files changed on disk; rescanning`);
      await this.scanProject();
      return;
    }
    for (const fsPath of paths) {
      try {
        this.store.setFile(fsPath, await this.server.scanFile(vscode.Uri.file(fsPath)));
      } catch (error) {
        return this.reportError(error);
      }
    }
  }

  // --- scanning ---------------------------------------------------------

  /**
   * Extensions any rule targets, fetched once from the server.
   *
   * Without it every keystroke in a Markdown file would send the whole buffer
   * across the process boundary to be told there was nothing to look for.
   */
  private isScannable(uri: vscode.Uri): boolean {
    if (uri.scheme !== 'file' || !this.scannableExtensions) {
      return uri.scheme === 'file';
    }
    const base = path.basename(uri.fsPath);
    return this.scannableExtensions.has(base) || this.scannableExtensions.has(path.extname(base));
  }

  private async scanDocument(document: vscode.TextDocument): Promise<void> {
    if (document.isClosed || document.uri.scheme !== 'file') {
      return;
    }
    const version = document.version;
    try {
      const findings = document.isDirty
        ? await this.server.scanText(document)
        : await this.server.scanFile(document.uri);
      // A newer edit landed while this was in flight; its scan is already
      // scheduled and this answer describes text nobody is looking at.
      if (!document.isClosed && document.version === version) {
        this.store.setFile(document.uri.fsPath, findings);
      }
    } catch (error) {
      this.reportError(error);
    }
  }

  private async scanProject(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders ?? [];
    if (folders.length === 0 || !this.settings.enable || this.scanning) {
      return;
    }
    this.scanning = true;
    try {
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Window,
          title: 'greenlint: scanning workspace',
          cancellable: true,
        },
        async (progress, token) => {
          token.onCancellationRequested(() => void this.server.cancelProjectScan());
          this.scannableExtensions ??= new Set(await this.server.languages());
          await this.applyExcludes();
          // Unsaved buffers are what the developer is actually looking at; a
          // scan of their last-saved bytes would overwrite the truth with
          // history.
          const dirty = new Set(
            vscode.workspace.textDocuments.filter((d) => d.isDirty).map((d) => d.uri.fsPath),
          );
          for (const folder of folders) {
            // Findings arrive in batches and go straight into the panel, so it
            // fills as the walk goes. Nothing is pruned until the walk
            // finishes: a file the scan has not reached yet is not a file with
            // no findings.
            const reported = new Set<string>();
            const response = await this.server.scanProject(folder, (batch) => {
              progress.report({ message: `${batch.files} files, ${batch.found} findings` });
              for (const finding of batch.batch) {
                reported.add(finding.file);
              }
              this.store.mergeBatch(batch.batch, dirty);
            });
            if (response.cancelled) {
              // Nothing is pruned: the walk stopped partway, so the files it
              // never reached are not files without findings.
              this.log.appendLine('[greenlint] scan cancelled');
              return;
            }
            this.lastStats = response.stats;
            this.lastSummary = response.summary;
            this.store.pruneUnder(folder.uri.fsPath, reported, dirty);
            this.logScan(folder, response.stats, response.summary);
          }
        },
      );
    } catch (error) {
      this.reportError(error);
    } finally {
      this.scanning = false;
      this.repaint();
    }
  }

  private logScan(
    folder: vscode.WorkspaceFolder,
    stats?: ScanStats,
    summary?: ScanSummary,
  ): void {
    if (summary) {
      const { bySeverity: by, total, files } = summary;
      this.log.appendLine(
        `[greenlint] ${total} finding(s) in ${files} file(s) — ` +
          `${by.high} high, ${by.medium} medium, ${by.low} low`,
      );
    }
    if (stats) {
      // The walked path and the count, because a workspace root one level too
      // high — a folder of projects rather than a project — turns a scan of a
      // few hundred files into a scan of a disk, and nothing else in the editor
      // makes that visible.
      this.log.appendLine(
        `[greenlint] scanned ${folder.uri.fsPath}: ${stats.files} files in ${stats.ms} ms ` +
          `(${stats.scanned} read and scanned, ` +
          `${stats.reusedFromStat + stats.reusedFromHash} from cache, ${stats.skipped} skipped)`,
      );
    }
  }

  /**
   * Hand the scan server what the editor already excludes.
   *
   * Sent rather than asked for: the server cannot read VS Code's settings, and
   * these have to be in place before the first walk or it spends that walk in
   * exactly the directories nobody wanted looked at.
   */
  private async applyExcludes(): Promise<void> {
    const globs = new Set<string>(this.settings.exclude);
    if (this.settings.respectEditorExcludes) {
      for (const folder of vscode.workspace.workspaceFolders ?? []) {
        for (const glob of editorExcludeGlobs(folder)) {
          globs.add(glob);
        }
      }
    }
    const sorted = [...globs].sort();
    const fingerprint = sorted.join('\n');
    if (fingerprint === this.appliedExcludes) {
      return;
    }
    await this.server.configure(sorted);
    this.appliedExcludes = fingerprint;
    this.log.appendLine(`[greenlint] excluding ${sorted.length} glob(s): ${sorted.join(', ')}`);
  }

  private async reconfigure(): Promise<void> {
    const previous = this.settings;
    this.settings = readSettings();
    this.server.updateSettings(this.settings);
    if (!this.settings.enable) {
      this.store.clear();
      this.server.stop();
      return;
    }
    if (requiresRestart(previous, this.settings)) {
      this.scannableExtensions = undefined;
      await this.server.restart();
    }
    // Both the excludes and greenlint's own config can have moved; the cheapest
    // correct answer to "what changed?" is to scan again.
    this.appliedExcludes = '';
    await this.server.invalidate();
    await this.scanProject();
  }

  // --- presentation -----------------------------------------------------

  /** Repaint what the store now says. `files` narrows the diagnostics update to
   * the files that changed; without it the whole collection is rebuilt. */
  private repaint(files?: string[]): void {
    if (files) {
      for (const file of files) {
        this.diagnostics.set(vscode.Uri.file(file), this.store.forFile(file).map(toDiagnostic));
      }
    } else {
      this.diagnostics.clear();
      for (const [file, findings] of this.store.entries()) {
        this.diagnostics.set(vscode.Uri.file(file), findings.map(toDiagnostic));
      }
    }
    this.findings.refresh();
    const total = this.store.size;
    void vscode.commands.executeCommand('setContext', 'greenlint.hasFindings', total > 0);
    this.tree.description = this.findings.describeScope();
    this.tree.badge = total > 0 ? { value: total, tooltip: `${total} findings` } : undefined;
    this.updateStatus(total);
    // A full re-render per batch would undo the point of streaming; the report
    // gets one when the scan finishes.
    if (this.reportPanel && !this.scanning) {
      this.reportPanel.webview.html = this.reportHtml();
    }
  }

  /**
   * Accept everything currently found, so an existing codebase starts green.
   *
   * Confirmed first: it writes a file into the repository and quietens real
   * findings, which is not something to do because a menu item was near the
   * pointer.
   */
  private async writeBaseline(): Promise<void> {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      return;
    }
    const total = this.store.size;
    const confirmed = await vscode.window.showWarningMessage(
      `Accept the ${total} current finding(s) as the baseline? ` +
        'They stop being reported here and in CI; new ones still are.',
      { modal: true },
      'Write Baseline',
    );
    if (confirmed !== 'Write Baseline') {
      return;
    }
    try {
      const { path: written, accepted } = await this.server.writeBaseline(folder);
      this.log.appendLine(`[greenlint] ${accepted} finding(s) accepted in ${written}`);
      await this.scanProject();
    } catch (error) {
      this.reportError(error);
    }
  }

  private async pickGrouping(): Promise<void> {
    const pick = await vscode.window.showQuickPick(
      [
        { label: 'severity', description: 'high, then medium, then low' },
        { label: 'file', description: 'one group per file' },
        { label: 'rule', description: 'one group per rule' },
      ],
      { title: 'Group findings by' },
    );
    if (pick) {
      this.findings.grouping = pick.label as Grouping;
      void this.context.workspaceState.update('grouping', pick.label);
      this.repaint();
    }
  }

  /**
   * The status bar line, and behind it the end-of-scan aggregate.
   *
   * The counts in the bar follow the panel's scope; the tooltip reports the
   * whole project as the last scan computed it, so "3 findings in this file"
   * and "412 across the project" are both one glance away.
   */
  private updateStatus(total: number): void {
    const counts = countBySeverity(this.findings.findings());
    this.status.text =
      total === 0
        ? '$(circle-large-outline) greenlint'
        : `$(flame) ${counts.high} $(warning) ${counts.medium} $(info) ${counts.low}`;
    const tooltip = new vscode.MarkdownString(undefined, true);
    tooltip.appendMarkdown(`**greenlint** — ${this.findings.describeScope()}`);
    if (this.lastSummary) {
      const { bySeverity: by, total: all, files } = this.lastSummary;
      tooltip.appendMarkdown(
        `\n\nWhole project: ${all} finding${all === 1 ? '' : 's'} in ${files} file${
          files === 1 ? '' : 's'
        } — $(flame) ${by.high} · $(warning) ${by.medium} · $(info) ${by.low}`,
      );
    }
    if (this.lastStats) {
      tooltip.appendMarkdown(
        `\n\nLast scan: ${this.lastStats.files} files in ${this.lastStats.ms} ms ` +
          `(${this.lastStats.scanned} scanned, ` +
          `${this.lastStats.reusedFromStat + this.lastStats.reusedFromHash} cached)`,
      );
    }
    this.status.tooltip = tooltip;
    this.status.show();
  }

  private setExpanded(expanded: boolean): void {
    this.findings.expanded = expanded;
    void vscode.commands.executeCommand('setContext', 'greenlint.expanded', expanded);
    this.repaint();
  }

  private setScope(scope: Scope): void {
    this.findings.scope = scope;
    void this.context.workspaceState.update('scope', scope);
    void vscode.commands.executeCommand('setContext', 'greenlint.scope', scope);
    this.repaint();
  }

  private showReport(): void {
    if (!this.reportPanel) {
      this.reportPanel = vscode.window.createWebviewPanel(
        'greenlint.report',
        'greenlint report',
        { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
        {},
      );
      this.reportPanel.iconPath = vscode.Uri.joinPath(
        this.context.extensionUri,
        'media',
        'leaf.svg',
      );
      this.reportPanel.onDidDispose(() => {
        this.reportPanel = undefined;
      });
    }
    this.reportPanel.webview.html = this.reportHtml();
    this.reportPanel.reveal(vscode.ViewColumn.Beside, true);
  }

  private reportHtml(): string {
    return renderReport(this.findings.findings(), {
      scopeLabel: this.findings.scope === 'project' ? 'whole project' : this.findings.describeScope(),
      generatedAt: new Date(),
      version: this.server.serverInfo?.version,
      stats: this.findings.scope === 'project' ? this.lastStats : undefined,
      relative: workspaceRelative,
    });
  }

  private reportError(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    this.log.appendLine(`[greenlint] ${message}`);
    if (this.lastErrorShown === message) {
      return;
    }
    this.lastErrorShown = message;
    void vscode.window
      .showErrorMessage(`greenlint: ${message.split('\n')[0]}`, 'Show Log')
      .then((choice) => choice === 'Show Log' && this.log.show(true));
  }
}
