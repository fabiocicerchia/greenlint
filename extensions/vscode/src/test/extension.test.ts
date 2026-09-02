// activate() and deactivate(), against the shimmed editor.
//
// The extension's entry point returns nothing and keeps its state private, so
// what it does IS what it asks the editor to do: register these commands, seed
// these context keys, and on the way out dispose everything it created. All
// three are contract — package.json names the commands and the `when` clauses
// name the keys — so they are asserted against package.json itself rather than
// against a list copied into the test, which would agree with the code and
// disagree with what VS Code loads.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as path from 'node:path';
import { test } from 'node:test';

import { activate, deactivate } from '../extension';
import { recorded, resetRecorded } from './vscode-shim';

interface Manifest {
  contributes: { commands: Array<{ command: string }> };
}

const manifest = JSON.parse(
  readFileSync(path.join(__dirname, '..', '..', 'package.json'), 'utf8'),
) as Manifest;

const contributedCommands = manifest.contributes.commands.map((entry) => entry.command).sort();

function fakeContext() {
  return {
    subscriptions: [] as Array<{ dispose: () => void }>,
    asAbsolutePath: (relative: string) => `/ext/${relative}`,
    extensionUri: { fsPath: '/ext', scheme: 'file' },
    workspaceState: {
      get: <T>(_key: string, fallback: T) => fallback,
      update: async () => undefined,
    },
  };
}

/** activate, let its synchronous start settle, and hand back the context. */
async function activated() {
  resetRecorded();
  const context = fakeContext();
  activate(context as never);
  await Promise.resolve();
  await Promise.resolve();
  return context;
}

test('registers exactly the commands package.json contributes', async () => {
  await activated();
  assert.deepEqual([...recorded.commands].sort(), contributedCommands);
  deactivate();
});

test('registers each command once', async () => {
  await activated();
  assert.equal(new Set(recorded.commands).size, recorded.commands.length);
  deactivate();
});

test('seeds the context keys the menus and welcome view read', async () => {
  await activated();
  const setContext = new Map(
    recorded.executed
      .filter((call) => call[0] === 'setContext')
      .map((call) => [call[1] as string, call[2]]),
  );
  // `greenlint.scope` and `greenlint.expanded` drive view/title menus;
  // `greenlint.hasFindings` drives viewsWelcome. Unset, the panel shows the
  // wrong buttons on the first paint and nothing corrects it until a scan.
  assert.equal(setContext.get('greenlint.scope'), 'project');
  assert.equal(setContext.get('greenlint.expanded'), true);
  assert.equal(setContext.get('greenlint.hasFindings'), false);
  deactivate();
});

test('hands the editor exactly one disposable to own', async () => {
  const context = await activated();
  assert.equal(context.subscriptions.length, 1);
  deactivate();
});

test('deactivate disposes the view, the status bar, the diagnostics and the log', async () => {
  await activated();
  deactivate();
  for (const label of ['treeView', 'statusBarItem', 'diagnosticCollection', 'outputChannel']) {
    assert.ok(recorded.disposed.includes(label), `${label} was not disposed`);
  }
});

test('deactivate unregisters every command it registered', async () => {
  await activated();
  deactivate();
  const unregistered = recorded.disposed
    .filter((label) => label.startsWith('command:'))
    .map((label) => label.slice('command:'.length))
    .sort();
  assert.deepEqual(unregistered, contributedCommands);
});

test('deactivate disposes the file watchers and their listeners', async () => {
  await activated();
  deactivate();
  // Two watchers (`**/*` and `**/.greenlint.toml`) plus the six listeners hung
  // off them. A watcher left alive keeps firing into a disposed controller.
  assert.equal(recorded.disposed.filter((l) => l === 'fileSystemWatcher').length, 2);
  assert.ok(recorded.disposed.includes('watcher.onDidChange'));
  assert.ok(recorded.disposed.includes('watcher.onDidCreate'));
  assert.ok(recorded.disposed.includes('watcher.onDidDelete'));
});

test('deactivate disposes the document and editor listeners', async () => {
  await activated();
  deactivate();
  for (const label of [
    'workspace.onDidChangeConfiguration',
    'workspace.onDidChangeTextDocument',
    'workspace.onDidSaveTextDocument',
    'workspace.onDidOpenTextDocument',
    'workspace.onDidCloseTextDocument',
    'window.onDidChangeActiveTextEditor',
    'hoverProvider',
  ]) {
    assert.ok(recorded.disposed.includes(label), `${label} was not disposed`);
  }
});

test('deactivate is safe when nothing is active, and twice over', async () => {
  await activated();
  deactivate();
  const after = recorded.disposed.length;
  deactivate();
  deactivate();
  assert.equal(recorded.disposed.length, after);
});

test('activate after deactivate registers the commands again', async () => {
  await activated();
  deactivate();
  await activated();
  assert.deepEqual([...recorded.commands].sort(), contributedCommands);
  deactivate();
});
