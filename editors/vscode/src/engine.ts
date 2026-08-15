import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

import * as vscode from 'vscode';

import type { Settings } from './config';
import type { Finding, RuleInfo, ScanStats, ServerInfo } from './types';

const START_TIMEOUT_MS = 20_000;
const REQUEST_TIMEOUT_MS = 120_000;

interface Pending {
  resolve: (value: Record<string, unknown>) => void;
  reject: (reason: Error) => void;
  op: string;
  startedAt: number;
  timer: NodeJS.Timeout;
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
   */
  private candidates(): Array<{ python: string; module?: string }> {
    const pythons = this.settings.pythonPath
      ? [this.settings.pythonPath]
      : process.platform === 'win32'
        ? ['python', 'py']
        : ['python3', 'python'];
    const modules: Array<string | undefined> = this.settings.greenlintPath
      ? [this.settings.greenlintPath]
      : [undefined, ...workspaceGreenlintModules()];
    const pairs: Array<{ python: string; module?: string }> = [];
    for (const python of pythons) {
      for (const module of modules) {
        pairs.push({ python, module });
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
    for (const candidate of this.candidates()) {
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
    throw new ScanServerError(
      `could not start the greenlint scan server.\n${failures.join('\n')}\n` +
        'Install it with `pipx install git+https://github.com/fabiocicerchia/greenlint`, ' +
        'or point `greenlint.pythonPath` / `greenlint.greenlintPath` at your copy.',
    );
  }

  private spawn(python: string, module?: string): Promise<ServerInfo> {
    const args = [this.serverScript, '--cache-entries', String(this.settings.cacheEntries)];
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
      proc.on('exit', (code, signal) => {
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
      this.log.appendLine(`[greenlint] unparseable line from the scan server: ${line}`);
      return;
    }
    if (message.event === 'ready') {
      this.onReady?.();
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

  private request<T>(op: string, payload: Record<string, unknown>): Promise<T> {
    const proc = this.proc;
    if (!proc?.stdin) {
      return Promise.reject(new ScanServerError('scan server is not running'));
    }
    const id = this.nextId++;
    const promise = new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new ScanServerError(`${op} timed out`));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(id, {
        resolve: resolve as (value: Record<string, unknown>) => void,
        reject,
        op,
        startedAt: Date.now(),
        timer,
      });
    });
    proc.stdin.write(`${JSON.stringify({ id, op, ...payload })}\n`);
    return promise;
  }

  /** Start if needed, then send. Every public call goes through here. */
  private async call<T>(op: string, payload: Record<string, unknown> = {}): Promise<T> {
    await this.start();
    return this.request<T>(op, payload);
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

  async scanProject(
    folder: vscode.WorkspaceFolder,
  ): Promise<{ findings: Finding[]; stats?: ScanStats; cancelled?: boolean }> {
    return this.call('scanProject', {
      root: folder.uri.fsPath,
      paths: [folder.uri.fsPath],
      maxFileBytes: this.settings.maxFileBytes,
    });
  }

  async rules(): Promise<RuleInfo[]> {
    const response = await this.call<{ rules: RuleInfo[] }>('rules');
    return response.rules;
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
