// Enough of the `vscode` module to exercise the parts of the extension that do
// not need an editor.
//
// The alternative is running tests inside a downloaded VS Code, which is slow,
// networked, and tests the editor rather than this code. The modules worth
// covering — glob translation, the finding store, ordering, the report — touch
// almost none of the API, so a stub of what they touch buys real coverage for
// a page of code.

class EventEmitter<T> {
  private listeners: Array<(value: T) => void> = [];
  readonly event = (listener: (value: T) => void) => {
    this.listeners.push(listener);
    return { dispose: () => undefined };
  };
  fire(value: T): void {
    for (const listener of [...this.listeners]) {
      listener(value);
    }
  }
  dispose(): void {
    this.listeners = [];
  }
}

/** Set by a test to decide what `getConfiguration(section).get('exclude')` returns. */
export const configuration: Record<string, Record<string, unknown>> = {};

class ThemeIcon {
  static readonly File = new ThemeIcon('file');
  constructor(
    readonly id: string,
    readonly color?: unknown,
  ) {}
}

class TreeItem {
  description?: string;
  iconPath?: unknown;
  resourceUri?: unknown;
  tooltip?: unknown;
  command?: unknown;
  constructor(
    readonly label: string,
    readonly collapsibleState?: number,
  ) {}
}

/**
 * What the editor was asked to do, for a test to assert on.
 *
 * `activate` has no return value and no state a test may read: its whole
 * product is the calls it makes into the editor — the commands it registers,
 * the context keys the menus read, and what it later disposes. Recording them
 * is the only way to assert on it without a running VS Code.
 */
export const recorded = {
  /** Command ids passed to `commands.registerCommand`, in order. */
  commands: [] as string[],
  /** Every `commands.executeCommand` call, arguments included. */
  executed: [] as unknown[][],
  /** Labels of the disposables that were disposed, in order. */
  disposed: [] as string[],
};

export function resetRecorded(): void {
  recorded.commands.length = 0;
  recorded.executed.length = 0;
  recorded.disposed.length = 0;
}

const disposable = (label: string) => ({
  dispose: () => {
    recorded.disposed.push(label);
  },
});

const emitter = (label: string) => (_listener: unknown) => disposable(label);

export const vscode = {
  EventEmitter,
  ThemeIcon,
  ThemeColor: class {
    constructor(readonly id: string) {}
  },
  TreeItem,
  TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
  DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
  Range: class {
    constructor(
      readonly startLine: number,
      readonly startCharacter: number,
      readonly endLine: number,
      readonly endCharacter: number,
    ) {}
  },
  MarkdownString: class {
    value = '';
    constructor(
      _value?: string,
      readonly supportThemeIcons?: boolean,
    ) {}
    isTrusted = false;
    appendMarkdown(text: string) {
      this.value += text;
      return this;
    }
  },
  Uri: {
    file: (fsPath: string) => ({ fsPath, scheme: 'file', toString: () => `file://${fsPath}` }),
    parse: (value: string) => ({ fsPath: value, scheme: 'https', toString: () => value }),
    joinPath: (base: { fsPath: string }, ...parts: string[]) => ({
      fsPath: [base.fsPath, ...parts].join('/'),
      scheme: 'file',
    }),
  },
  Diagnostic: class {
    code?: unknown;
    source?: string;
    constructor(
      readonly range: unknown,
      readonly message: string,
      readonly severity?: number,
    ) {}
  },
  Hover: class {
    constructor(
      readonly contents: unknown,
      readonly range?: unknown,
    ) {}
  },
  Disposable: {
    from: (...items: Array<{ dispose: () => void }>) => ({
      dispose: () => {
        for (const item of items) {
          item.dispose();
        }
      },
    }),
  },
  StatusBarAlignment: { Left: 1, Right: 2 },
  ProgressLocation: { SourceControl: 1, Window: 10, Notification: 15 },
  ViewColumn: { Active: -1, Beside: -2, One: 1 },
  env: { clipboard: { writeText: async (_text: string) => undefined } },
  commands: {
    registerCommand: (name: string, _run: () => unknown) => {
      recorded.commands.push(name);
      return disposable(`command:${name}`);
    },
    executeCommand: (name: string, ...args: unknown[]) => {
      recorded.executed.push([name, ...args]);
      return Promise.resolve(undefined);
    },
  },
  languages: {
    createDiagnosticCollection: (name: string) => ({
      name,
      set: () => undefined,
      delete: () => undefined,
      clear: () => undefined,
      dispose: () => recorded.disposed.push('diagnosticCollection'),
    }),
    registerHoverProvider: (_selector: unknown, _provider: unknown) =>
      disposable('hoverProvider'),
  },
  window: {
    activeTextEditor: undefined as unknown,
    visibleTextEditors: [] as unknown[],
    createOutputChannel: (name: string) => ({
      name,
      appendLine: () => undefined,
      append: () => undefined,
      show: () => undefined,
      dispose: () => recorded.disposed.push('outputChannel'),
    }),
    createTreeView: (id: string, options: unknown) => ({
      id,
      options,
      description: undefined as string | undefined,
      badge: undefined as unknown,
      message: undefined as string | undefined,
      dispose: () => recorded.disposed.push('treeView'),
    }),
    createStatusBarItem: (alignment: number, priority: number) => ({
      alignment,
      priority,
      command: undefined as string | undefined,
      name: undefined as string | undefined,
      text: '',
      tooltip: undefined as unknown,
      show: () => undefined,
      dispose: () => recorded.disposed.push('statusBarItem'),
    }),
    onDidChangeActiveTextEditor: emitter('window.onDidChangeActiveTextEditor'),
    withProgress: async <T>(
      _options: unknown,
      task: (
        progress: { report: (value: unknown) => void },
        token: { onCancellationRequested: (listener: () => void) => void },
      ) => Promise<T>,
    ) => task({ report: () => undefined }, { onCancellationRequested: () => undefined }),
    showQuickPick: async (_items: unknown, _options?: unknown) => undefined,
    showWarningMessage: async (_message: string, ..._rest: unknown[]) => undefined,
    showErrorMessage: async (_message: string, ..._rest: unknown[]) => undefined,
    showInformationMessage: async (_message: string, ..._rest: unknown[]) => undefined,
  },
  workspace: {
    getConfiguration: (section: string) => ({
      get: <T>(_key: string, fallback?: T) => (configuration[section] ?? fallback ?? {}) as T,
    }),
    asRelativePath: (uri: { fsPath: string }) => uri.fsPath.replace(/^\/proj\//, ''),
    getWorkspaceFolder: (_uri: unknown) => undefined,
    createFileSystemWatcher: (_glob: string) => ({
      onDidChange: emitter('watcher.onDidChange'),
      onDidCreate: emitter('watcher.onDidCreate'),
      onDidDelete: emitter('watcher.onDidDelete'),
      dispose: () => recorded.disposed.push('fileSystemWatcher'),
    }),
    onDidChangeConfiguration: emitter('workspace.onDidChangeConfiguration'),
    onDidChangeTextDocument: emitter('workspace.onDidChangeTextDocument'),
    onDidSaveTextDocument: emitter('workspace.onDidSaveTextDocument'),
    onDidOpenTextDocument: emitter('workspace.onDidOpenTextDocument'),
    onDidCloseTextDocument: emitter('workspace.onDidCloseTextDocument'),
    textDocuments: [] as unknown[],
    workspaceFolders: [] as unknown[],
  },
};
