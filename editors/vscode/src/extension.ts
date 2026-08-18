import * as path from 'path';

import * as vscode from 'vscode';

import { readSettings, requiresRestart, type Settings } from './config';
import {
  GreenlintCodeActionProvider,
  GreenlintHoverProvider,
  SOURCE,
  toDiagnostic,
} from './diagnostics';
import { ScanServer } from './engine';
import { editorExcludeGlobs } from './excludes';
import { FindingsProvider, type Grouping, type Scope, workspaceRelative } from './findingsView';
import { renderReport } from './report';
import { FindingStore } from './store';
import type { Finding, ScanStats, ScanSummary, Severity } from './types';

/** External changes are batched: a `git checkout` touches hundreds of files,
 * and scanning each one as its event lands is the thundering herd this whole
 * extension is built to avoid. */
const EXTERNAL_CHANGE_DEBOUNCE_MS = 1_500;
/** Past this many changed files, one project scan is cheaper than the batch —
 * it walks with the stat cache and only reads what actually changed. */
const BATCH_TO_PROJECT_SCAN = 50;
/** A walk larger than this is usually a workspace root one level too high. */
const BIG_WALK_FILES = 20_000;

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
  private settings: Settings;
  private readonly log = vscode.window.createOutputChannel('greenlint');
  private readonly diagnostics = vscode.languages.createDiagnosticCollection(SOURCE);
  private readonly store = new FindingStore();
  private readonly server: ScanServer;
  private readonly findings: FindingsProvider;
  private readonly tree: vscode.TreeView<unknown>;
  private readonly status: vscode.StatusBarItem;
  private readonly disposables: vscode.Disposable[] = [];

  private readonly debouncers = new Map<string, NodeJS.Timeout>();
  private readonly pendingExternal = new Set<string>();
  private externalTimer?: NodeJS.Timeout;
  private intervalTimer?: NodeJS.Timeout;
  private reportPanel?: vscode.WebviewPanel;
  private reportTimer?: NodeJS.Timeout;
  private supportedExtensions?: Set<string>;
  private lastStats?: ScanStats;
  private lastSummary?: ScanSummary;
  private lastErrorShown?: string;
  private readonly warnedAboutWalkSize = new Set<string>();
  private appliedExcludes = '';
  private projectScanRunning = false;

  constructor(private readonly context: vscode.ExtensionContext) {
    this.settings = readSettings();
    this.server = new ScanServer(
      context.asAbsolutePath(path.join('server', 'greenlint_server.py')),
      this.settings,
      this.log,
    );
    this.findings = new FindingsProvider(this.store, () => this.settings);
    this.findings.scope = context.workspaceState.get<Scope>('scope', 'project');
    this.findings.grouping = context.workspaceState.get<Grouping>('grouping', 'severity');
    this.tree = vscode.window.createTreeView('greenlint.findings', {
      treeDataProvider: this.findings,
      showCollapseAll: true,
    });
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
    this.status.command = 'greenlint.findings.focus';
    this.status.name = 'greenlint';
  }

  async start(): Promise<void> {
    this.registerCommands();
    this.registerProviders();
    this.registerListeners();
    void vscode.commands.executeCommand('setContext', 'greenlint.scope', this.findings.scope);
    this.render({ files: [], replaced: true });

    if (!this.settings.enable) {
      return;
    }
    await this.applyExcludes();
    if (this.settings.scanProjectOnStartup) {
      await this.scanProject();
    }
    for (const editor of vscode.window.visibleTextEditors) {
      this.schedule(editor.document, 0);
    }
    this.applyInterval();
  }

  dispose(): void {
    for (const timer of this.debouncers.values()) {
      clearTimeout(timer);
    }
    clearTimeout(this.externalTimer);
    clearTimeout(this.reportTimer);
    clearInterval(this.intervalTimer);
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

  private registerCommands(): void {
    const on = (command: string, run: (...args: never[]) => unknown) =>
      this.disposables.push(vscode.commands.registerCommand(command, run));

    on('greenlint.scanFile', () => {
      const editor = vscode.window.activeTextEditor;
      if (editor) {
        void this.scanDocument(editor.document, { force: true });
      }
    });
    on('greenlint.scanProject', () => this.scanProject());
    on('greenlint.showReport', () => this.showReport());
    on('greenlint.exportReport', () => this.exportReport());
    on('greenlint.showScopeFile', () => this.setScope('file'));
    on('greenlint.showScopeProject', () => this.setScope('project'));
    on('greenlint.setGrouping', () => this.pickGrouping());
    on('greenlint.setSeverityFilter', () => this.pickSeverities());
    on('greenlint.disableRule', (rule: string) => this.disableRule(rule));
    on('greenlint.clearCache', () => this.clearCache());
    on('greenlint.showOutput', () => this.log.show(true));
    on('greenlint.restartServer', async () => {
      await this.server.restart();
      await this.scanProject();
    });
  }

  private registerProviders(): void {
    const selector: vscode.DocumentSelector = { scheme: 'file' };
    this.disposables.push(
      vscode.languages.registerHoverProvider(
        selector,
        new GreenlintHoverProvider(this.store, () => this.settings),
      ),
      vscode.languages.registerCodeActionsProvider(selector, new GreenlintCodeActionProvider(), {
        providedCodeActionKinds: GreenlintCodeActionProvider.providedCodeActionKinds,
      }),
    );
  }

  private registerListeners(): void {
    this.disposables.push(
      this.store.onDidChange((change) => this.render(change)),

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
      vscode.workspace.onDidSaveTextDocument((document) => {
        // A save makes the buffer and the file identical, so this costs a hash
        // check rather than a scan — but it is what keeps the project view
        // honest for a file that was never opened.
        this.schedule(document, 0);
      }),
      vscode.workspace.onDidOpenTextDocument((document) => this.schedule(document, 0)),
      vscode.workspace.onDidCloseTextDocument((document) => {
        this.debouncers.delete(document.uri.toString());
      }),
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        this.findings.setCurrentFile(editor?.document.uri.fsPath);
        this.updateStatus();
        if (editor) {
          this.schedule(editor.document, 0);
        }
      }),

      ...this.watchWorkspace(),
    );
    this.findings.setCurrentFile(vscode.window.activeTextEditor?.document.uri.fsPath);
  }

  private watchWorkspace(): vscode.Disposable[] {
    const watcher = vscode.workspace.createFileSystemWatcher('**/*');
    const config = vscode.workspace.createFileSystemWatcher('**/.greenlint.toml');
    return [
      watcher,
      config,
      watcher.onDidChange((uri) => this.queueExternal(uri)),
      watcher.onDidCreate((uri) => this.queueExternal(uri)),
      watcher.onDidDelete((uri) => {
        this.store.forget(uri.fsPath);
        this.diagnostics.delete(uri);
        void this.server.invalidate([uri.fsPath]);
      }),
      // A config change rewrites what every cached finding means, so it drops
      // the lot rather than trying to work out which rules moved.
      config.onDidChange(() => void this.clearCache()),
      config.onDidCreate(() => void this.clearCache()),
      config.onDidDelete(() => void this.clearCache()),
    ];
  }

  // --- scheduling -------------------------------------------------------

  private schedule(document: vscode.TextDocument, delay: number): void {
    if (!this.settings.enable || this.settings.run === 'manual' || document.uri.scheme !== 'file') {
      return;
    }
    if (!this.isScannable(document.uri)) {
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
    if (uri.scheme !== 'file' || !this.isScannable(uri)) {
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
      this.log.appendLine(`[greenlint] ${paths.length} files changed on disk; rescanning the project`);
      await this.scanProject();
      return;
    }
    for (const fsPath of paths) {
      try {
        const findings = await this.server.scanFile(vscode.Uri.file(fsPath));
        this.store.setFile(fsPath, findings);
      } catch (error) {
        this.reportError(error);
        return;
      }
    }
  }

  private applyInterval(): void {
    clearInterval(this.intervalTimer);
    this.intervalTimer = undefined;
    const minutes = this.settings.projectScanIntervalMinutes;
    if (minutes > 0) {
      this.intervalTimer = setInterval(() => void this.scanProject({ quiet: true }), minutes * 60_000);
    }
  }

  // --- scanning ---------------------------------------------------------

  /**
   * Extensions any rule targets, fetched once from the server.
   *
   * Without it every keystroke in a Markdown file would cross the process
   * boundary to be told there is nothing to look for.
   */
  private isScannable(uri: vscode.Uri): boolean {
    if (!this.supportedExtensions) {
      return true;
    }
    const base = path.basename(uri.fsPath);
    return this.supportedExtensions.has(base) || this.supportedExtensions.has(path.extname(base));
  }

  private async loadRuleLanguages(): Promise<void> {
    if (this.supportedExtensions) {
      return;
    }
    try {
      const rules = await this.server.rules();
      this.supportedExtensions = new Set(rules.flatMap((rule) => rule.langs));
    } catch (error) {
      this.reportError(error);
    }
  }

  private async scanDocument(document: vscode.TextDocument, options: { force?: boolean } = {}): Promise<void> {
    if (document.isClosed || document.uri.scheme !== 'file') {
      return;
    }
    if (!options.force && !this.isScannable(document.uri)) {
      return;
    }
    const version = document.version;
    try {
      await this.loadRuleLanguages();
      const findings = document.isDirty
        ? await this.server.scanText(document)
        : await this.server.scanFile(document.uri);
      // A newer edit landed while this was in flight; its scan is already
      // scheduled and this answer describes text nobody is looking at.
      if (document.isClosed || document.version !== version) {
        return;
      }
      this.store.setFile(document.uri.fsPath, findings);
    } catch (error) {
      this.reportError(error);
    }
  }

  private async scanProject(options: { quiet?: boolean } = {}): Promise<void> {
    const folders = vscode.workspace.workspaceFolders ?? [];
    if (folders.length === 0 || !this.settings.enable || this.projectScanRunning) {
      return;
    }
    this.projectScanRunning = true;
    const run = async (report?: (message: string) => void) => {
      await this.loadRuleLanguages();
      await this.applyExcludes();
      // Unsaved buffers are what the developer is actually looking at; a scan
      // of their last-saved bytes would overwrite the truth with history.
      const dirty = new Set(
        vscode.workspace.textDocuments.filter((doc) => doc.isDirty).map((doc) => doc.uri.fsPath),
      );
      for (const folder of folders) {
        // Findings arrive in batches and go straight into the panel, so it
        // fills as the walk goes. Nothing is pruned until the walk finishes:
        // a file the scan has not reached yet is not a file with no findings.
        const reported = new Set<string>();
        const response = await this.server.scanProject(folder, (progress) => {
          report?.(`${progress.files} files, ${progress.found} findings`);
          for (const finding of progress.batch) {
            reported.add(finding.file);
          }
          this.store.mergeBatch(progress.batch, dirty);
        });
        if (response.cancelled) {
          continue;
        }
        this.lastStats = response.stats;
        this.lastSummary = response.summary;
        this.store.pruneUnder(folder.uri.fsPath, reported, dirty);
        if (response.summary) {
          const { bySeverity, total, files } = response.summary;
          this.log.appendLine(
            `[greenlint] ${total} finding${total === 1 ? '' : 's'} in ${files} file${
              files === 1 ? '' : 's'
            } — ${bySeverity.high} high, ${bySeverity.medium} medium, ${bySeverity.low} low`,
          );
        }
        if (response.stats) {
          this.log.appendLine(
            `[greenlint] scanned ${folder.uri.fsPath}: ` +
              `${response.stats.files} files in ${response.stats.ms} ms ` +
              `(${response.stats.scanned} read and scanned, ` +
              `${response.stats.reusedFromStat + response.stats.reusedFromHash} from cache, ` +
              `${response.stats.skipped} skipped)`,
          );
          this.warnIfWalkingTooMuch(folder, response.stats.files);
        }
      }
    };
    try {
      if (options.quiet) {
        await run();
      } else {
        await vscode.window.withProgress(
          { location: vscode.ProgressLocation.Window, title: 'greenlint: scanning workspace' },
          (progress) => run((message) => progress.report({ message })),
        );
      }
    } catch (error) {
      this.reportError(error);
    } finally {
      this.projectScanRunning = false;
      // The aggregate, once, over the finished set.
      this.refreshReport(true);
      this.updateStatus();
    }
  }

  /**
   * Hand the scan server what the editor already excludes.
   *
   * Sent rather than asked for: the server has no way to read VS Code's
   * settings, and these have to be in place before the first walk or it spends
   * that walk in exactly the directories nobody wanted looked at. Cheap enough
   * to re-check before every project scan, and a no-op when nothing moved.
   */
  private async applyExcludes(): Promise<void> {
    const globs = this.excludeGlobs();
    const fingerprint = globs.join('\n');
    if (fingerprint === this.appliedExcludes) {
      return;
    }
    try {
      await this.server.configure(globs);
      this.appliedExcludes = fingerprint;
      this.log.appendLine(
        globs.length === 0
          ? '[greenlint] no editor excludes applied'
          : `[greenlint] excluding ${globs.length} glob(s) from the editor's settings: ` +
              `${globs.slice(0, 8).join(', ')}${globs.length > 8 ? ', …' : ''}`,
      );
    } catch (error) {
      this.reportError(error);
    }
  }

  private excludeGlobs(): string[] {
    const globs = new Set<string>(this.settings.exclude);
    if (this.settings.respectEditorExcludes) {
      for (const folder of vscode.workspace.workspaceFolders ?? []) {
        for (const glob of editorExcludeGlobs(folder)) {
          globs.add(glob);
        }
      }
    }
    return [...globs].sort();
  }

  /**
   * A workspace root one level too high — a folder of projects rather than a
   * project — turns a scan of a few hundred files into a scan of a disk. It is
   * invisible from inside the editor, so it gets said out loud once.
   */
  private warnIfWalkingTooMuch(folder: vscode.WorkspaceFolder, files: number): void {
    if (files < BIG_WALK_FILES || this.warnedAboutWalkSize.has(folder.uri.fsPath)) {
      return;
    }
    this.warnedAboutWalkSize.add(folder.uri.fsPath);
    const message =
      `greenlint walked ${files.toLocaleString()} files under ${folder.uri.fsPath}. ` +
      'If that is more than you meant to scan, add `ignore` globs to .greenlint.toml ' +
      '(CI reads the same ones) or turn off greenlint.scanProjectOnStartup.';
    this.log.appendLine(`[greenlint] ${message}`);
    void vscode.window.showWarningMessage(message, 'Show Log').then((choice) => {
      if (choice === 'Show Log') {
        this.log.show(true);
      }
    });
  }

  private async clearCache(): Promise<void> {
    try {
      await this.server.invalidate();
    } catch (error) {
      this.reportError(error);
    }
    this.store.clear();
    await this.scanProject();
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      await this.scanDocument(editor.document, { force: true });
    }
  }

  private async reconfigure(): Promise<void> {
    const previous = this.settings;
    this.settings = readSettings();
    this.server.updateSettings(this.settings);
    this.applyInterval();
    if (!this.settings.enable) {
      this.diagnostics.clear();
      this.store.clear();
      this.server.stop();
      return;
    }
    if (requiresRestart(previous, this.settings)) {
      this.supportedExtensions = undefined;
      await this.server.restart();
    }
    this.render({ files: [], replaced: true });
    await this.scanProject();
  }

  // --- presentation -----------------------------------------------------

  private render(change: { files: string[]; replaced: boolean }): void {
    if (change.replaced) {
      this.diagnostics.clear();
      const grouped = new Map<string, vscode.Diagnostic[]>();
      for (const finding of this.store.all()) {
        const list = grouped.get(finding.file) ?? [];
        list.push(toDiagnostic(finding, this.settings));
        grouped.set(finding.file, list);
      }
      for (const [file, diagnostics] of grouped) {
        this.diagnostics.set(vscode.Uri.file(file), diagnostics);
      }
    } else {
      for (const file of change.files) {
        const findings = this.store.forFile(file);
        this.diagnostics.set(
          vscode.Uri.file(file),
          findings.map((finding) => toDiagnostic(finding, this.settings)),
        );
      }
    }
    this.findings.refresh();
    this.updateStatus();
    this.refreshReport();
  }

  private updateStatus(): void {
    const total = this.store.size;
    void vscode.commands.executeCommand('setContext', 'greenlint.hasFindings', total > 0);
    this.tree.description = this.findings.describeScope();
    this.tree.badge =
      total > 0 ? { value: total, tooltip: `${total} greenlint findings` } : undefined;
    const counts = this.store.totals();
    this.status.text = total === 0 ? '$(circle-large-outline) greenlint' : `$(flame) ${counts.high} $(warning) ${counts.medium} $(info) ${counts.low}`;
    this.status.tooltip = this.describeLastScan(total);
    this.status.show();
  }

  /**
   * The end-of-scan aggregate, as computed once over the finished set rather
   * than accumulated from the batches — so it reflects the whole project even
   * while the panel is showing one file.
   */
  private describeLastScan(total: number): vscode.MarkdownString {
    const tooltip = new vscode.MarkdownString(undefined, true);
    if (total === 0 && !this.lastSummary) {
      tooltip.appendMarkdown('greenlint: nothing found');
      return tooltip;
    }
    const summary = this.lastSummary;
    tooltip.appendMarkdown(
      summary
        ? `**greenlint** — ${summary.total} finding${summary.total === 1 ? '' : 's'} ` +
            `in ${summary.files} file${summary.files === 1 ? '' : 's'}\n\n` +
            `$(flame) ${summary.bySeverity.high} high · ` +
            `$(warning) ${summary.bySeverity.medium} medium · ` +
            `$(info) ${summary.bySeverity.low} low`
        : `**greenlint** — ${total} finding${total === 1 ? '' : 's'}`,
    );
    if (this.lastStats) {
      tooltip.appendMarkdown(
        `\n\nLast scan: ${this.lastStats.files} files in ${this.lastStats.ms} ms ` +
          `(${this.lastStats.scanned} scanned, ` +
          `${this.lastStats.reusedFromStat + this.lastStats.reusedFromHash} cached)`,
      );
    }
    return tooltip;
  }

  private setScope(scope: Scope): void {
    this.findings.scope = scope;
    void this.context.workspaceState.update('scope', scope);
    void vscode.commands.executeCommand('setContext', 'greenlint.scope', scope);
    this.findings.refresh();
    this.updateStatus();
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
      this.findings.refresh();
    }
  }

  private async pickSeverities(): Promise<void> {
    const all: Severity[] = ['high', 'medium', 'low'];
    const picks = await vscode.window.showQuickPick(
      all.map((severity) => ({ label: severity, picked: this.findings.severities.has(severity) })),
      { title: 'Show severities', canPickMany: true },
    );
    if (picks) {
      this.findings.severities = new Set(picks.map((pick) => pick.label as Severity));
      this.findings.refresh();
      this.updateStatus();
    }
  }

  // --- report -----------------------------------------------------------

  private reportFindings(): { findings: Finding[]; scope: string } {
    return { findings: this.findings.visible(), scope: this.findings.scopeName() };
  }

  private showReport(): void {
    if (this.reportPanel) {
      this.reportPanel.reveal(vscode.ViewColumn.Beside);
      this.refreshReport(true);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      'greenlint.report',
      'greenlint report',
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
      { enableScripts: true, retainContextWhenHidden: false },
    );
    panel.iconPath = vscode.Uri.joinPath(this.context.extensionUri, 'media', 'leaf.svg');
    panel.onDidDispose(() => {
      this.reportPanel = undefined;
    });
    panel.webview.onDidReceiveMessage((message: { type: string; file: string; line: number }) => {
      if (message.type === 'open') {
        const position = new vscode.Position(Math.max(0, message.line - 1), 0);
        void vscode.window.showTextDocument(vscode.Uri.file(message.file), {
          selection: new vscode.Range(position, position),
          viewColumn: vscode.ViewColumn.One,
        });
      }
    });
    this.reportPanel = panel;
    this.refreshReport(true);
  }

  /** Repainting a webview is not free, so a burst of scans coalesces into one. */
  private refreshReport(immediate = false): void {
    if (!this.reportPanel) {
      return;
    }
    // A streaming scan repaints this on every batch otherwise, which is a full
    // re-render of the document for a partial answer. It gets one at the end.
    if (this.projectScanRunning && !immediate) {
      return;
    }
    clearTimeout(this.reportTimer);
    const paint = () => {
      if (!this.reportPanel) {
        return;
      }
      const { findings, scope } = this.reportFindings();
      const nonce = randomNonce();
      this.reportPanel.webview.html = renderReport(findings, {
        scopeLabel: scope,
        generatedAt: new Date(),
        version: this.server.serverInfo?.version,
        stats: this.findings.scope === 'project' ? this.lastStats : undefined,
        showCo2e: this.settings.showCo2eEstimate,
        interactive: true,
        nonce,
        cspSource: this.reportPanel.webview.cspSource,
        relative: workspaceRelative,
      });
    };
    if (immediate) {
      paint();
    } else {
      this.reportTimer = setTimeout(paint, 300);
    }
  }

  private async exportReport(): Promise<void> {
    const { findings, scope } = this.reportFindings();
    const folder = vscode.workspace.workspaceFolders?.[0];
    const target = await vscode.window.showSaveDialog({
      title: 'Export greenlint report',
      defaultUri: folder
        ? vscode.Uri.joinPath(folder.uri, 'greenlint-report.html')
        : vscode.Uri.file('greenlint-report.html'),
      filters: { HTML: ['html'] },
    });
    if (!target) {
      return;
    }
    const html = renderReport(findings, {
      scopeLabel: scope,
      generatedAt: new Date(),
      version: this.server.serverInfo?.version,
      stats: this.findings.scope === 'project' ? this.lastStats : undefined,
      showCo2e: this.settings.showCo2eEstimate,
      interactive: false,
      relative: workspaceRelative,
    });
    await vscode.workspace.fs.writeFile(target, Buffer.from(html, 'utf8'));
    const open = await vscode.window.showInformationMessage(
      `greenlint report written to ${path.basename(target.fsPath)}`,
      'Open',
    );
    if (open) {
      await vscode.env.openExternal(target);
    }
  }

  // --- config editing ---------------------------------------------------

  private async disableRule(rule: string): Promise<void> {
    const folder =
      (vscode.window.activeTextEditor
        ? vscode.workspace.getWorkspaceFolder(vscode.window.activeTextEditor.document.uri)
        : undefined) ?? vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      void vscode.window.showWarningMessage('greenlint: no workspace folder to write .greenlint.toml into.');
      return;
    }
    const uri = vscode.Uri.joinPath(folder.uri, '.greenlint.toml');
    let text = '';
    try {
      text = Buffer.from(await vscode.workspace.fs.readFile(uri)).toString('utf8');
    } catch {
      text = '';
    }
    if (new RegExp(`["']${rule}["']`).test(text)) {
      void vscode.window.showInformationMessage(`greenlint: ${rule} is already disabled.`);
      return;
    }
    const list = /^\s*disable\s*=\s*\[/m.exec(text);
    const updated = list
      ? `${text.slice(0, list.index + list[0].length)}\n  "${rule}",${text.slice(list.index + list[0].length)}`
      : `${text}${text.endsWith('\n') || text === '' ? '' : '\n'}disable = ["${rule}"]\n`;
    await vscode.workspace.fs.writeFile(uri, Buffer.from(updated, 'utf8'));
    await vscode.window.showTextDocument(uri, { preview: true });
    // The config watcher picks the change up and drops the cache.
  }

  // --- errors -----------------------------------------------------------

  private reportError(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    this.log.appendLine(`[greenlint] ${message}`);
    if (this.lastErrorShown === message) {
      return;
    }
    this.lastErrorShown = message;
    void vscode.window
      .showErrorMessage(`greenlint: ${message.split('\n')[0]}`, 'Show Log')
      .then((choice) => {
        if (choice === 'Show Log') {
          this.log.show(true);
        }
      });
  }
}

function randomNonce(): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let nonce = '';
  for (let index = 0; index < 32; index += 1) {
    nonce += alphabet[Math.floor(Math.random() * alphabet.length)];
  }
  return nonce;
}
