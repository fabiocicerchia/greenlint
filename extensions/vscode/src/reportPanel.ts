import * as vscode from "vscode";

/** The report is a document with a section per finding; it is worth building
 * once the findings stop moving, not on every batch and every keystroke. */
const REPORT_RENDER_DEBOUNCE_MS = 400;

/** The report webview: when it exists, and when it is worth re-rendering. */
export class ReportPanel implements vscode.Disposable {
  private panel?: vscode.WebviewPanel;
  private timer?: NodeJS.Timeout;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly render: () => string,
  ) {}

  /**
   * Re-render the report, at most once per quiet moment.
   *
   * A full re-render per batch would undo the point of streaming, and one per
   * keystroke — which is what a repaint is, with the panel open — rebuilds a
   * document with a section per finding for a webview that may not even be the
   * visible tab. Both are answered by waiting for the typing to stop.
   */
  refresh(scanning: boolean): void {
    clearTimeout(this.timer);
    if (!this.panel?.visible || scanning) {
      return;
    }
    this.timer = setTimeout(() => {
      if (this.panel?.visible) {
        this.panel.webview.html = this.render();
      }
    }, REPORT_RENDER_DEBOUNCE_MS);
  }

  show(): void {
    if (!this.panel) {
      this.panel = vscode.window.createWebviewPanel(
        "greenlint.report",
        "greenlint report",
        { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
        {},
      );
      this.panel.iconPath = vscode.Uri.joinPath(this.extensionUri, "media", "leaf.svg");
      this.panel.onDidDispose(() => {
        clearTimeout(this.timer);
        this.panel = undefined;
      });
      // Nothing is rendered into a hidden webview, so it is stale by the time
      // it comes back — this is where it catches up.
      this.panel.onDidChangeViewState((event) => {
        if (event.webviewPanel.visible) {
          event.webviewPanel.webview.html = this.render();
        }
      });
    }
    this.panel.webview.html = this.render();
    this.panel.reveal(vscode.ViewColumn.Beside, true);
  }

  dispose(): void {
    clearTimeout(this.timer);
    this.panel?.dispose();
  }
}
