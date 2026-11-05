// The user journey end to end: activate, run "Scan Current File" on an unsaved
// buffer, and read the Problems panel.
//
// extension.test.ts stops at what activate registers; engine.test.ts drives the
// scan server without the extension. This is the path between them — command
// handler, Controller.scanDocument, the real server over the repository's own
// greenlint.py, the store, publishDiagnostics — which is what a user actually
// sees work or not.
import assert from "node:assert/strict";
import * as path from "node:path";
import { test } from "node:test";

import { activate, deactivate } from "../extension";
import { greenlintSettings, recorded, resetRecorded, vscode } from "./vscode-shim";

const extensionRoot = path.resolve(__dirname, "..", "..");
const repoRoot = path.resolve(extensionRoot, "..", "..");

interface Published {
  message: string;
  source?: string;
  code: { value: string };
}

test("scan current file puts the finding in the Problems panel, and a fix clears it", async () => {
  resetRecorded();
  // No workspace folder, so startup has no project to walk: the only scan is
  // the one the command asks for.
  Object.assign(greenlintSettings, { greenlintPath: path.join(repoRoot, "greenlint.py") });
  const file = path.join(repoRoot, "busy.py");
  const document = {
    uri: vscode.Uri.file(file),
    isClosed: false,
    isDirty: true,
    version: 1,
    text: "while True:\n    pass\n",
    getText() {
      return this.text;
    },
  };
  vscode.window.activeTextEditor = { document };
  activate({
    subscriptions: [],
    asAbsolutePath: (relative: string) => path.join(extensionRoot, relative),
    extensionUri: { fsPath: extensionRoot, scheme: "file" },
    workspaceState: { get: <T>(_key: string, fallback: T) => fallback, update: async () => undefined },
  } as never);
  try {
    const scanFile = recorded.handlers.get("greenlint.scanFile");
    assert.ok(scanFile, "greenlint.scanFile was not registered");

    await scanFile();
    const published = recorded.diagnostics.get(file) as Published[] | undefined;
    assert.deepEqual(
      published?.map((d) => d.code.value),
      ["GL001"],
    );
    assert.equal(published?.[0].source, "greenlint");

    document.version = 2;
    document.text = "import time\nwhile True:\n    time.sleep(1)\n";
    await scanFile();
    assert.equal(recorded.diagnostics.has(file), false);
  } finally {
    deactivate();
    vscode.window.activeTextEditor = undefined;
    for (const key of Object.keys(greenlintSettings)) {
      delete greenlintSettings[key];
    }
  }
});
