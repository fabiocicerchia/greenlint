import * as cp from 'child_process';

import * as vscode from 'vscode';

import type { Settings } from './config';
import { candidates, dedupe } from './interpreters';
import { LineProtocol, type ScanProgress, ScanServerError } from './protocol';
import { forgetRuleProse, share } from './share';
import { type Finding, type ScanStats, type ScanSummary, type ServerInfo, useSeverityOrder } from './types';

const START_TIMEOUT_MS = 20_000;

/** The one command that fixes "greenlint is not installed". Kept short on
 * purpose: a toast is read in a second, and the log already lists every path
 * that was tried. */
export const INSTALL_COMMAND = 'pipx install git+https://github.com/fabiocicerchia/greenlint';

/**
 * Client for `server/greenlint_server.py`.
 *
 * One process for the window, started on the first scan and kept alive: the
 * interpreter start and the ~40 regex compiles behind every `greenlint` run are
 * the single largest cost in an editor loop, and they are the same work every
 * time. Requests are line-delimited JSON correlated by id — see `protocol.ts`.
 */
export class ScanServer implements vscode.Disposable {
  private proc?: cp.ChildProcess;
  private starting?: Promise<ServerInfo>;
  private info?: ServerInfo;
  private projectScanId?: number;
  private disposed = false;
  private readonly protocol: LineProtocol;

  constructor(
    private readonly serverScript: string,
    private settings: Settings,
    private readonly log: vscode.OutputChannel,
  ) {
    this.protocol = new LineProtocol(log);
    this.protocol.trace = settings.trace;
  }

  updateSettings(settings: Settings): void {
    this.settings = settings;
    this.protocol.trace = settings.trace;
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
    this.protocol.failPending(reason);
    this.protocol.reset();
    this.proc?.kill();
    this.proc = undefined;
    this.info = undefined;
  }

  async restart(): Promise<void> {
    this.stop();
    await this.start();
  }

  // --- process lifecycle ------------------------------------------------

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
    const tries = candidates(this.settings);
    // Printed up front because the interesting failure is often what is *not*
    // in this list — no workspace greenlint.py, or a single configured path.
    this.log.appendLine(
      `[greenlint] looking for greenlint in order: ${tries
        .map((c) => `${c.python}${c.module ? ` + ${c.module}` : ' + installed package'}`)
        .join(', ')}`,
    );
    for (const candidate of tries) {
      try {
        const info = await this.spawn(candidate.python, candidate.module);
        this.log.appendLine(
          `[greenlint] scan server ready: python ${info.python}, greenlint ${info.version} ` +
            `(${info.rules} rules) from ${info.module ?? 'installed package'}`,
        );
        this.info = info;
        forgetRuleProse();
        // Sorting happens here, but the order is greenlint's.
        useSeverityOrder(info.severityOrder);
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
        : 'could not start the scan server — install or upgrade greenlint, ' +
          'or set `greenlint.pythonPath` / `greenlint.greenlintPath`.';
    throw new ScanServerError(`${headline}\nTried:\n${failures.join('\n')}`, INSTALL_COMMAND);
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
    proc.stdout?.on('data', (chunk: string) => this.protocol.consume(chunk));
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
      this.protocol.onReady = () => {
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
      this.protocol.onFailed = fail;
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
          this.protocol.failPending(reason);
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
    return this.protocol.send<T>(proc.stdin, op, payload, onProgress, onSent);
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
    return share(response.findings);
  }

  async scanFile(uri: vscode.Uri): Promise<Finding[]> {
    const response = await this.call<{ findings: Finding[] }>('scanFile', {
      path: uri.fsPath,
      root: rootFor(uri),
      maxFileBytes: this.settings.maxFileBytes,
    });
    return share(response.findings);
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
