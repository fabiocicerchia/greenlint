import * as vscode from "vscode";

import { ScanServerError } from "./protocol";

/** Scan failures, told to the user once each — the log gets every one. */
export class ErrorNotifier {
  private lastShown?: string;

  constructor(private readonly log: vscode.OutputChannel) {}

  report(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    this.log.appendLine(`[greenlint] ${message}`);
    if (this.lastShown === message) {
      return;
    }
    this.lastShown = message;
    // greenlint missing is the one failure with a one-line fix, so the toast
    // carries the command itself — a link to the README is one click and one
    // page of reading away from the same sentence.
    const install = error instanceof ScanServerError ? error.install : undefined;
    const headline = message.split("\n")[0];
    const text = install ? `greenlint: ${headline}\n\nInstall it with: ${install}` : `greenlint: ${headline}`;
    const actions = install ? ["Install greenlint", "Copy Command", "Show Log"] : ["Show Log"];
    void vscode.window.showErrorMessage(text, ...actions).then((choice) => {
      if (choice === "Show Log") {
        this.log.show(true);
      } else if (choice === "Install greenlint" && install) {
        this.runInstall(install);
      } else if (choice === "Copy Command" && install) {
        void vscode.env.clipboard
          .writeText(install)
          .then(() => vscode.window.showInformationMessage(`Copied: ${install}`));
      }
    });
  }

  /**
   * Run the install in a terminal the user can see.
   *
   * Deliberately not a hidden `child_process`: this installs software, and it
   * can fail in ways only the output explains — no pipx on PATH, an externally
   * managed interpreter, a proxy. The terminal is both the progress bar and the
   * error message. What it cannot do is tell us when it finished, hence the
   * button rather than an automatic restart.
   */
  private runInstall(command: string): void {
    const terminal = vscode.window.createTerminal("greenlint install");
    terminal.show();
    terminal.sendText(command);
    void vscode.window
      .showInformationMessage(
        "Installing greenlint. When the terminal is done, restart the scan server.",
        "Restart Scan Server",
      )
      .then((choice) => {
        if (choice === "Restart Scan Server") {
          // The failure that got us here is fixed or not; either way the next
          // start reports for itself, so the guard must not swallow it.
          this.lastShown = undefined;
          void vscode.commands.executeCommand("greenlint.restartServer");
        }
      });
  }
}
