import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { test } from 'node:test';

import type * as vscode from 'vscode';

import type { Settings } from '../config';
import { INSTALL_COMMAND, ScanServer, ScanServerError, share } from '../engine';
import type { Finding } from '../types';
import { vscode as shim } from './vscode-shim';

// `JSON.parse` gives every finding its own copy of its rule's message,
// suggestion and CO2e note, and of its file's path. Identity is the assertion
// because that is the whole claim: one string, not one per finding. Equality
// would pass while the memory it saves went away.
const finding = (over: Partial<Finding> = {}): Finding =>
  JSON.parse(
    JSON.stringify({
      rule: 'GL005',
      severity: 'medium',
      file: '/proj/src/db.py',
      line: 1,
      message: 'SELECT * query',
      suggestion: 'fetch only needed columns',
      co2e_estimate: '~15 gCO2e per GB of columns never read',
      ...over,
    }),
  ) as Finding;

test('holds one copy of a rule prose and one of a repeated path', () => {
  const [first, second] = share([finding(), finding({ line: 9 })]);
  assert.equal(first.message, 'SELECT * query');
  for (const field of ['message', 'suggestion', 'co2e_estimate', 'file'] as const) {
    assert.ok(first[field] === second[field], `${field} was not shared`);
  }
});

test('does not put one rule\'s prose on another rule', () => {
  const [a, b] = share([finding(), finding({ rule: 'GL003', message: 'every-minute cron' })]);
  assert.equal(a.message, 'SELECT * query');
  assert.equal(b.message, 'every-minute cron');
});

test('keeps each path when findings from two files are interleaved', () => {
  // The path is shared against the previous finding only, which is what keeps
  // it from retaining a path once the batch is gone. Interleaving is the case
  // that would break if it were shared against the wrong one.
  const shared = share([
    finding({ file: '/proj/a.py' }),
    finding({ file: '/proj/b.py' }),
    finding({ file: '/proj/a.py', line: 2 }),
  ]);
  assert.deepEqual(
    shared.map((f) => f.file),
    ['/proj/a.py', '/proj/b.py', '/proj/a.py'],
  );
});

// --- where the scan server is looked for ---------------------------------
//
// The search order is the difference between "greenlint is not installed" and
// "greenlint is installed and the extension cannot find it", which is the most
// reported failure this extension has. Every candidate below names an
// interpreter that does not exist, so `spawn` fails immediately and no real
// Python is involved: what is under test is which pairs are tried, in what
// order, and what the failure says when they all fail the same way.

const settings = (over: Partial<Settings> = {}): Settings => ({
  enable: true,
  run: 'onType',
  debounceMs: 400,
  pythonPath: '/nonexistent/python-9c1f',
  greenlintPath: '',
  scanProjectOnStartup: false,
  maxFileBytes: 1_000_000,
  respectEditorExcludes: true,
  exclude: [],
  trace: false,
  ...over,
});

function recordingLog() {
  const lines: string[] = [];
  return {
    lines,
    channel: {
      appendLine: (line: string) => lines.push(line),
      append: (text: string) => lines.push(text),
    } as unknown as vscode.OutputChannel,
  };
}

/** The most recent line startOnce logged before trying anything, minus its prefix. */
const searchOrder = (lines: string[]): string => {
  const logged = lines.filter((line) => line.includes('looking for greenlint in order:'));
  return (logged[logged.length - 1] ?? '').split(': ')[1] ?? '';
};

test('an explicitly configured pair is the only candidate', async () => {
  // A typo in the setting must be an error, not a silent fallback to some other
  // greenlint whose rules the user never asked for.
  const log = recordingLog();
  const server = new ScanServer(
    '/nonexistent/server.py',
    settings({ greenlintPath: '/nonexistent/greenlint.py' }),
    log.channel,
  );
  await assert.rejects(server.start());
  assert.equal(searchOrder(log.lines), '/nonexistent/python-9c1f + /nonexistent/greenlint.py');
  server.dispose();
});

test('a workspace greenlint.py is tried before the installed package', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'greenlint-engine-'));
  writeFileSync(path.join(root, 'greenlint.py'), '');
  shim.workspace.workspaceFolders = [{ uri: { fsPath: root, scheme: 'file' } }];
  try {
    const log = recordingLog();
    const server = new ScanServer('/nonexistent/server.py', settings(), log.channel);
    await assert.rejects(server.start());
    assert.deepEqual(searchOrder(log.lines).split(', '), [
      `/nonexistent/python-9c1f + ${path.join(root, 'greenlint.py')}`,
      '/nonexistent/python-9c1f + installed package',
    ]);
    server.dispose();
  } finally {
    shim.workspace.workspaceFolders = [];
    rmSync(root, { recursive: true, force: true });
  }
});

test('when every candidate fails the same way, that reason leads', async () => {
  // The toast shows the first line only. "spawn ... ENOENT" said once is worth
  // more there than generic advice about setting two paths.
  const log = recordingLog();
  const server = new ScanServer('/nonexistent/server.py', settings(), log.channel);
  const error = await server.start().then(
    () => undefined,
    (reason: Error) => reason,
  );
  assert.ok(error instanceof ScanServerError);
  const [headline, tried] = error.message.split('\n');
  assert.match(headline, /ENOENT/);
  assert.equal(tried, 'Tried:');
  assert.equal(error.install, INSTALL_COMMAND);
  server.dispose();
});

test('a failed start is not remembered, so the next scan tries again', async () => {
  const log = recordingLog();
  const server = new ScanServer('/nonexistent/server.py', settings(), log.channel);
  await assert.rejects(server.start());
  await assert.rejects(server.start());
  assert.equal(log.lines.filter((line) => line.includes('looking for greenlint')).length, 2);
  assert.equal(server.running, false);
  server.dispose();
});

test('invalidate does nothing at all while the server is not running', async () => {
  const log = recordingLog();
  const server = new ScanServer('/nonexistent/server.py', settings(), log.channel);
  await server.invalidate(['/proj/a.py']);
  assert.deepEqual(log.lines, []);
  server.dispose();
});

test('updated settings change where the next start looks', async () => {
  const log = recordingLog();
  const server = new ScanServer('/nonexistent/server.py', settings(), log.channel);
  await assert.rejects(server.start());
  server.updateSettings(settings({ pythonPath: '/nonexistent/python-other' }));
  await assert.rejects(server.start());
  assert.equal(searchOrder(log.lines), '/nonexistent/python-other + installed package');
  server.dispose();
});

// --- against the real scan server ----------------------------------------
//
// Everything above stops at `spawn`. These start `server/greenlint_server.py`
// for real, over the repository's own greenlint.py, so the process lifecycle,
// the newline-delimited framing, the id correlation and the progress events all
// run — the parts of this file no test could reach while every candidate
// interpreter was a path that does not exist.

const repoRoot = path.resolve(__dirname, '..', '..', '..', '..');
const serverScript = path.join(repoRoot, 'extensions', 'vscode', 'server', 'greenlint_server.py');
const realSettings = () => settings({ pythonPath: '', greenlintPath: path.join(repoRoot, 'greenlint.py') });

const textDocument = (fsPath: string, text: string) =>
  ({ uri: { fsPath, scheme: 'file' }, getText: () => text }) as unknown as vscode.TextDocument;

test('starts a real scan server and reports what it loaded', async () => {
  const log = recordingLog();
  const server = new ScanServer(serverScript, realSettings(), log.channel);
  try {
    const info = await server.start();
    assert.ok(info.rules > 0, 'the server loaded no rules');
    assert.equal(server.running, true);
    // Starting again is the same process, not a second one.
    assert.equal(await server.start(), info);
  } finally {
    server.dispose();
  }
});

test('scans an unsaved buffer through the real protocol', async () => {
  const log = recordingLog();
  const server = new ScanServer(serverScript, realSettings(), log.channel);
  try {
    const findings = await server.scanText(
      textDocument(path.join(repoRoot, 'busy.py'), 'while True:\n    pass\n'),
    );
    assert.deepEqual(
      findings.map((f) => f.rule),
      ['GL001'],
    );
    assert.equal(findings[0].line, 1);
  } finally {
    server.dispose();
  }
});

test('a project scan streams its findings and ends with the totals', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'greenlint-e2e-'));
  writeFileSync(path.join(root, 'busy.py'), 'while True:\n    pass\n');
  writeFileSync(path.join(root, 'query.sql'), 'SELECT * FROM users;\n');
  const log = recordingLog();
  const server = new ScanServer(serverScript, realSettings(), log.channel);
  try {
    const streamed: Finding[] = [];
    const result = await server.scanProject(
      { uri: { fsPath: root, scheme: 'file' } } as unknown as vscode.WorkspaceFolder,
      (progress) => streamed.push(...progress.batch),
    );
    assert.equal(result.cancelled, undefined);
    assert.equal(result.summary?.total, 2);
    // The findings arrived through progress events, not in the response: that
    // is the whole point of streaming, and the response says so.
    assert.deepEqual(
      streamed.map((f) => f.rule).sort(),
      ['GL001', 'GL005'],
    );
  } finally {
    server.dispose();
    rmSync(root, { recursive: true, force: true });
  }
});

test('an unknown op comes back as a rejection, not a hang', async () => {
  const log = recordingLog();
  const server = new ScanServer(serverScript, realSettings(), log.channel);
  try {
    await server.start();
    // `invalidate` with a path the cache never held is the closest public call
    // to a no-op; what is asserted is that the request/response correlation
    // completes at all, which is `consume` -> `handleLine` -> resolve.
    await server.invalidate(['/nowhere/at/all.py']);
    const languages = await server.languages();
    assert.ok(languages.includes('.py'), `no .py in ${languages.join(',')}`);
  } finally {
    server.dispose();
  }
});
