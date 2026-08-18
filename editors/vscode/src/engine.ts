import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

import * as vscode from 'vscode';

import type { Settings } from './config';
import type { Finding, ScanStats, ScanSummary, ServerInfo } from './types';

const START_TIMEOUT_MS = 20_000;
const REQUEST_TIMEOUT_MS = 120_000;

export interface ScanProgress {
  /** Files walked so far. */
  files: number;
  /** Findings made so far, across every batch. */
  found: number;
  /** Findings made since the previous progress event. */
  batch: Finding[];
}

interface Pending {
  resolve: (value: Record<string, unknown>) => void;
  reject: (reason: Error) => void;
  op: string;
  startedAt: number;
  timer: NodeJS.Timeout;
  onProgress?: (progress: ScanProgress) => void;
}

export class ScanServerError extends Error {}

/**
 * Client for `server/greenlint_server.py`.
 *
 * One process for the window, started on the first scan and kept alive: the
 * interpreter start and the ~40 regex compiles behind every `greenlint` run are
 * the single largest cost in an editor loop, and they are the same work every
 * time. Requests are line-delimited JSON correlated by id.
 */
export class ScanServer implements vscode.Disposable {
  private proc?: cp.ChildProcess;
  private starting?: Promise<ServerInfo>;
  private info?: ServerInfo;
  private buffer = '';
  private nextId = 1;
  private projectScanId?: number;
  private readonly pending = new Map<number, Pending>();
  private onReady?: () => void;
  private onFailed?: (error: Error) => void;
  private disposed = false;

  constructor(
    private readonly serverScript: string,
    private settings: Settings,
    private readonly log: vscode.OutputChannel,
  ) {}

  updateSettings(settings: Settings): void {
    this.settings = settings;
  }

  get running(): boolean {
    return this.proc !== undefined && this.proc.exitCode === null;
  }

  get serverInfo(): ServerInfo | undefined {
    return this.info;
  }

  dispose(): void {
    this.disposed = true;
    this.stop();
  }

  stop(): void {
    this.killProcess(new ScanServerError('scan server stopped'));
    this.starting = undefined;
  }

  private killProcess(reason: Error): void {
    this.failPending(reason);
    this.proc?.kill();
    this.proc = undefined;
    this.info = undefined;
    this.buffer = '';
    this.onReady = undefined;
    this.onFailed = undefined;
  }

  async restart(): Promise<void> {
    this.stop();
    await this.start();
  }

  // --- process lifecycle ------------------------------------------------

  /**
   * Candidate (interpreter, greenlint module) pairs, most likely first.
   *
   * An explicitly configured path is the only candidate — a typo there should
   * be an error, not a silent fallback to some other greenlint whose rules the
   * user never asked for.
   *
   * Otherwise a greenlint.py in the workspace comes before the installed
   * package, for two reasons that turn out to be the same one: someone editing
   * the rules wants to see their edits, and an installed release can be older
   * than the module surface this extension needs. A candidate whose greenlint
   * is too old refuses to start, so the loop simply moves on to the next.
   */
  private candidates(): Array<{ python: string; module?: string }> {
    if (this.settings.pythonPath && this.settings.greenlintPath) {
      return [{ python: this.settings.pythonPath, module: this.settings.greenlintPath }];
    }
    const plain = this.settings.pythonPath
      ? [this.settings.pythonPath]
      : process.platform === 'win32'
        ? ['python', 'py']
        : ['python3', 'python'];
    const pairs: Array<{ python: string; module?: string }> = [];
    // A module loaded from a path needs no particular interpreter — any Python
    // that runs will import it — so these come first and only need `plain`.
    for (const module of this.settings.greenlintPath
      ? [this.settings.greenlintPath]
      : workspaceGreenlintModules()) {
      for (const python of plain) {
        pairs.push({ python, module });
      }
    }
    if (!this.settings.greenlintPath) {
      // `import greenlint`, which is a question about the interpreter rather
      // than about greenlint: pipx and venv installs are deliberately invisible
      // to the `python3` on PATH, so the interpreter that owns the `greenlint`
      // command gets a turn too.
      for (const python of this.settings.pythonPath
        ? plain
        : dedupe([...plain, ...interpretersOwningGreenlint()])) {
        pairs.push({ python });
      }
    }
    return pairs;
  }

  async start(): Promise<ServerInfo> {
    if (this.info && this.running) {
      return this.info;
    }
    if (!this.starting) {
      this.starting = this.startOnce().catch((error: Error) => {
        this.starting = undefined;
        throw error;
      });
    }
    return this.starting;
  }

  private async startOnce(): Promise<ServerInfo> {
    const failures: string[] = [];
    const candidates = this.candidates();
    // Printed up front because the interesting failure is often what is *not*
    // in this list — no workspace greenlint.py, or a single configured path.
    this.log.appendLine(
      `[greenlint] looking for greenlint in order: ${candidates
        .map((c) => `${c.python}${c.module ? ` + ${c.module}` : ' + installed package'}`)
        .join(', ')}`,
    );
    for (const candidate of candidates) {
      try {
        const info = await this.spawn(candidate.python, candidate.module);
        this.log.appendLine(
          `[greenlint] scan server ready: python ${info.python}, greenlint ${info.version} ` +
            `(${info.rules} rules) from ${info.module ?? 'installed package'}`,
        );
        this.info = info;
        return info;
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        failures.push(
          `${candidate.python}${candidate.module ? ` (${candidate.module})` : ''}: ${reason}`,
        );
        this.killProcess(new ScanServerError(reason));
      }
    }
    // First line first: it is the only part a notification toast shows. When
    // every candidate failed the same way — an installed greenlint that is too
    // old, say — that reason is far more useful than generic advice, so it
    // leads instead.
    const reasons = dedupe(failures.map((failure) => failure.replace(/^[^:]*: /, '')));
    const headline =
      reasons.length === 1
        ? reasons[0]
        : 'could not start the scan server — install or upgrade greenlint ' +
          '(`pip install -U git+https://github.com/fabiocicerchia/greenlint`, or `pipx` ' +
          'if you have it), or set `greenlint.pythonPath` / `greenlint.greenlintPath`.';
    throw new ScanServerError(`${headline}\nTried:\n${failures.join('\n')}`);
  }

  private spawn(python: string, module?: string): Promise<ServerInfo> {
    const args = [this.serverScript];
    if (module) {
      args.push('--greenlint', module);
    }
    this.log.appendLine(`[greenlint] starting: ${python} ${args.join(' ')}`);
    const proc = cp.spawn(python, args, {
      cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.proc = proc;
    proc.stdout?.setEncoding('utf8');
    proc.stdout?.on('data', (chunk: string) => this.consume(chunk));
    proc.stderr?.setEncoding('utf8');
    proc.stderr?.on('data', (chunk: string) => this.log.append(`[greenlint:stderr] ${chunk}`));

    return new Promise<ServerInfo>((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(
        () => fail(new ScanServerError('timed out waiting for the scan server')),
        START_TIMEOUT_MS,
      );
      function done(): boolean {
        if (settled) {
          return true;
        }
        settled = true;
        clearTimeout(timer);
        return false;
      }
      const fail = (error: Error) => {
        if (!done()) {
          reject(error);
        }
      };
      this.onReady = () => {
        // `ready` only says the process is alive; the ping is what proves it
        // found a rule set to scan with.
        this.request<ServerInfo>('ping', {}).then(
          (info) => {
            if (!done()) {
              resolve(info);
            }
          },
          fail,
        );
      };
      this.onFailed = fail;
      proc.on('error', (error) => fail(new ScanServerError(error.message)));
      // `close`, not `exit`: a server that refuses to start writes *why* to
      // stdout and then exits, and `exit` can beat the last stdout chunk. That
      // race is the difference between "greenlint 0.1.0 is too old, upgrade it"
      // and "exited (code 1)".
      proc.on('close', (code, signal) => {
        const reason = new ScanServerError(`scan server exited (code ${code}, signal ${signal})`);
        fail(reason);
        // Only the current process may tear down shared state: a candidate
        // that already lost the race exiting later must not kill the winner.
        if (proc === this.proc) {
          this.failPending(reason);
          this.proc = undefined;
          this.starting = undefined;
          this.info = undefined;
          if (!this.disposed && code !== 0) {
            this.log.appendLine(`[greenlint] ${reason.message}; it will restart on the next scan`);
          }
        }
      });
    });
  }

  private failPending(error: Error): void {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(id);
    }
  }

  // --- protocol ---------------------------------------------------------

  private consume(chunk: string): void {
    this.buffer += chunk;
    let index = this.buffer.indexOf('\n');
    while (index >= 0) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (line) {
        this.handleLine(line);
      }
      index = this.buffer.indexOf('\n');
    }
  }

  private handleLine(line: string): void {
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(line) as Record<string, unknown>;
    } catch {
      this.log.appendLine(`[greenlint] unparsable line from the scan server: ${line}`);
      return;
    }
    if (message.event === 'ready') {
      this.onReady?.();
      return;
    }
    if (message.event === 'progress') {
      // Liveness, not an answer: a scan that is still walking must not time
      // out, and must not resolve either.
      const pending = this.pending.get(message.id as number);
      if (pending) {
        this.rearm(message.id as number, pending);
        pending.onProgress?.({
          files: Number(message.files ?? 0),
          found: Number(message.found ?? 0),
          batch: (message.batch as Finding[] | undefined) ?? [],
        });
      }
      return;
    }
    if (message.fatal) {
      this.onFailed?.(new ScanServerError(String(message.error)));
      return;
    }
    const pending = this.pending.get(message.id as number);
    if (!pending) {
      return;
    }
    clearTimeout(pending.timer);
    this.pending.delete(message.id as number);
    if (this.settings.trace) {
      const stats = message.stats as ScanStats | undefined;
      const detail = stats
        ? ` files=${stats.files} scanned=${stats.scanned} stat=${stats.reusedFromStat} hash=${stats.reusedFromHash} skip=${stats.skipped}`
        : message.source
          ? ` source=${String(message.source)}`
          : '';
      this.log.appendLine(
        `[greenlint] ${pending.op} took ${Date.now() - pending.startedAt}ms${detail}`,
      );
    }
    if (message.ok === false) {
      pending.reject(new ScanServerError(String(message.error)));
      return;
    }
    pending.resolve(message);
  }

  /** Restart a pending request's timeout. The timeout measures silence, not
   * total duration: a project scan of a large tree is slow but not stuck. */
  private rearm(id: number, pending: Pending): void {
    clearTimeout(pending.timer);
    pending.timer = setTimeout(() => {
      this.pending.delete(id);
      pending.reject(
        new ScanServerError(
          `${pending.op} timed out after ${REQUEST_TIMEOUT_MS / 1000}s with no progress`,
        ),
      );
    }, REQUEST_TIMEOUT_MS);
  }

  private request<T>(
    op: string,
    payload: Record<string, unknown>,
    onProgress?: (progress: ScanProgress) => void,
    onSent?: (id: number) => void,
  ): Promise<T> {
    const proc = this.proc;
    if (!proc?.stdin) {
      return Promise.reject(new ScanServerError('scan server is not running'));
    }
    const id = this.nextId++;
    const promise = new Promise<T>((resolve, reject) => {
      const pending: Pending = {
        resolve: resolve as (value: Record<string, unknown>) => void,
        reject,
        op,
        startedAt: Date.now(),
        timer: setTimeout(() => undefined, 0),
        onProgress,
      };
      this.pending.set(id, pending);
      this.rearm(id, pending);
    });
    proc.stdin.write(`${JSON.stringify({ id, op, ...payload })}\n`);
    onSent?.(id);
    return promise;
  }

  /** Start if needed, then send. Every public call goes through here. */
  private async call<T>(
    op: string,
    payload: Record<string, unknown> = {},
    onProgress?: (progress: ScanProgress) => void,
    onSent?: (id: number) => void,
  ): Promise<T> {
    await this.start();
    return this.request<T>(op, payload, onProgress, onSent);
  }

  // --- operations -------------------------------------------------------

  async scanText(document: vscode.TextDocument): Promise<Finding[]> {
    const response = await this.call<{ findings: Finding[] }>('scanText', {
      path: document.uri.fsPath,
      text: document.getText(),
      root: rootFor(document.uri),
    });
    return response.findings;
  }

  async scanFile(uri: vscode.Uri): Promise<Finding[]> {
    const response = await this.call<{ findings: Finding[] }>('scanFile', {
      path: uri.fsPath,
      root: rootFor(uri),
      maxFileBytes: this.settings.maxFileBytes,
    });
    return response.findings;
  }

  /**
   * Walk a workspace folder, delivering findings through `onProgress` as they
   * are made. The resolved value carries the totals, not the findings — they
   * have already been handed over batch by batch.
   */
  async scanProject(
    folder: vscode.WorkspaceFolder,
    onProgress?: (progress: ScanProgress) => void,
  ): Promise<{ summary?: ScanSummary; stats?: ScanStats; cancelled?: boolean }> {
    this.log.appendLine(`[greenlint] scanning ${folder.uri.fsPath}`);
    return this.call(
      'scanProject',
      {
        root: folder.uri.fsPath,
        paths: [folder.uri.fsPath],
        maxFileBytes: this.settings.maxFileBytes,
        stream: true,
      },
      onProgress,
      (id) => {
        this.projectScanId = id;
      },
    );
  }

  /**
   * Ask the server to stop the project scan in flight.
   *
   * The walk checks for this between batches of files, so it stops at the next
   * batch rather than mid-file — which is why the scan can be abandoned without
   * leaving the cache half-written.
   */
  async cancelProjectScan(): Promise<void> {
    if (this.projectScanId !== undefined && this.running) {
      await this.call('cancel', { cancel: this.projectScanId });
    }
  }

  /** File extensions any rule targets, so the client can skip asking about a
   * file no rule would look at. Derived from the rule table, not hardcoded. */
  async languages(): Promise<string[]> {
    const response = await this.call<{ extensions: string[] }>('languages');
    return response.extensions;
  }

  /** Ignore globs on top of `.greenlint.toml`, for what the editor already
   * knows is not your code. Applied to every scan until changed. */
  async configure(ignore: string[]): Promise<string[]> {
    const response = await this.call<{ ignore: string[] }>('configure', { ignore });
    return response.ignore;
  }

  /** Record everything currently found as accepted, so only new findings
   * nag from here on. Returns where it was written and how many it took. */
  async writeBaseline(folder: vscode.WorkspaceFolder): Promise<{ path: string; accepted: number }> {
    return this.call('writeBaseline', { root: folder.uri.fsPath });
  }

  async invalidate(paths?: string[]): Promise<void> {
    if (!this.running) {
      return;
    }
    await this.call('invalidate', paths ? { paths } : {});
  }
}

function rootFor(uri: vscode.Uri): string | undefined {
  return vscode.workspace.getWorkspaceFolder(uri)?.uri.fsPath;
}

/** Workspace folders that contain a greenlint.py, for contributors working on
 * the rules themselves — their checkout should win over an installed release. */
function workspaceGreenlintModules(): string[] {
  const found: string[] = [];
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const candidate = path.join(folder.uri.fsPath, 'greenlint.py');
    if (fs.existsSync(candidate)) {
      found.push(candidate);
    }
  }
  return found;
}

function dedupe(values: string[]): string[] {
  return [...new Set(values)];
}

/**
 * Interpreters that can plausibly `import greenlint` even though the `python3`
 * on PATH cannot.
 *
 * The documented install is `pipx`, which puts greenlint in its own virtualenv
 * precisely so it does not appear in any interpreter on PATH — so looking only
 * at `python3` fails for exactly the users who followed the instructions. Two
 * cheap ways to find the real one: the shebang of the `greenlint` command
 * (a console script names its own interpreter on line one), and pipx's
 * standard venv layout.
 */
function interpretersOwningGreenlint(): string[] {
  const found: string[] = [];
  const script = onPath('greenlint');
  if (script) {
    try {
      const shebang = /^#!\s*("?)(\S+?)\1(?:\s|$)/.exec(
        fs.readFileSync(script, 'utf8').slice(0, 512).split('\n')[0] ?? '',
      );
      // A pyenv or asdf shim is a shell script, so its shebang is a shell —
      // only take the line seriously when it actually names a Python.
      if (shebang && /python/i.test(path.basename(shebang[2]))) {
        found.push(shebang[2]);
      }
    } catch {
      // Unreadable or binary: nothing to learn, and not worth reporting.
    }
  }
  const home = process.env.HOME ?? process.env.USERPROFILE;
  if (home) {
    const pipx =
      process.platform === 'win32'
        ? path.join(home, 'pipx', 'venvs', 'greenlint', 'Scripts', 'python.exe')
        : path.join(home, '.local', 'pipx', 'venvs', 'greenlint', 'bin', 'python');
    if (fs.existsSync(pipx)) {
      found.push(pipx);
    }
  }
  return found;
}

/** First executable named `command` on PATH. */
function onPath(command: string): string | undefined {
  const extensions = process.platform === 'win32' ? ['.exe', '.cmd', '.bat', ''] : [''];
  for (const dir of (process.env.PATH ?? '').split(path.delimiter)) {
    if (!dir) {
      continue;
    }
    for (const extension of extensions) {
      const candidate = path.join(dir, command + extension);
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    }
  }
  return undefined;
}
