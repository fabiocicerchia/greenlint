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
  Uri: { file: (fsPath: string) => ({ fsPath, scheme: 'file' }) },
  workspace: {
    getConfiguration: (section: string) => ({
      get: <T>(_key: string, fallback?: T) => (configuration[section] ?? fallback ?? {}) as T,
    }),
    asRelativePath: (uri: { fsPath: string }) => uri.fsPath.replace(/^\/proj\//, ''),
    textDocuments: [] as unknown[],
    workspaceFolders: [] as unknown[],
  },
};
