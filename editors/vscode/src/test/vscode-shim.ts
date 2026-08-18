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

export const vscode = {
  EventEmitter,
  Uri: { file: (fsPath: string) => ({ fsPath, scheme: 'file' }) },
  workspace: {
    getConfiguration: (section: string) => ({
      get: <T>(_key: string, fallback?: T) => (configuration[section] ?? fallback ?? {}) as T,
    }),
    asRelativePath: (uri: { fsPath: string }) => uri.fsPath,
    workspaceFolders: [] as unknown[],
  },
};
