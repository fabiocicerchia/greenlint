// The wire between the extension and `server/greenlint_server.py`.
//
// Newline-delimited JSON, one request per line out and one response per line
// in, correlated by id. Apart from the scan server because it is a different
// reason to change: framing, ids and timeouts belong to the pipe, while which
// interpreter to start and what to ask it belong to the server.

import * as vscode from 'vscode';

import { share } from './share';
import type { Finding, ScanStats } from './types';

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
  /** Set by `rearm` before the request is sent. */
  timer?: NodeJS.Timeout;
  onProgress?: (progress: ScanProgress) => void;
}

export class ScanServerError extends Error {
  /** Set only when no interpreter could run greenlint at all — the failure
   * `INSTALL_COMMAND` actually fixes. A mid-session crash must not offer it. */
  constructor(message: string, readonly install?: string) {
    super(message);
  }
}

/** Framing and id correlation for one server process. */
export class LineProtocol {
  private buffer = '';
  /** How much of `buffer` is known to hold no newline — see `consume`. */
  private searched = 0;
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  /** The process said it is up; the caller decides what to prove next. */
  onReady?: () => void;
  /** The process said it cannot start, and why. */
  onFailed?: (error: Error) => void;
  /** `greenlint.trace`: log what each request cost. */
  trace = false;

  constructor(private readonly log: vscode.OutputChannel) {}

  /** Forget the half-line and the callbacks belonging to a dead process. */
  reset(): void {
    this.buffer = '';
    this.searched = 0;
    this.onReady = undefined;
    this.onFailed = undefined;
  }

  consume(chunk: string): void {
    this.buffer += chunk;
    // The search resumes where the last one ran out rather than starting over:
    // a streamed batch is a single line of a hundred kilobytes arriving in many
    // chunks, and re-scanning everything received so far for each of them is
    // quadratic in the size of the message.
    let index = this.buffer.indexOf('\n', this.searched);
    while (index >= 0) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (line) {
        this.handleLine(line);
      }
      // What is left has not been looked at yet, so this one starts over.
      index = this.buffer.indexOf('\n');
    }
    this.searched = this.buffer.length;
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
          batch: share((message.batch as Finding[] | undefined) ?? []),
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
    if (this.trace) {
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

  failPending(error: Error): void {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(id);
    }
  }

  send<T>(
    stdin: NodeJS.WritableStream,
    op: string,
    payload: Record<string, unknown>,
    onProgress?: (progress: ScanProgress) => void,
    onSent?: (id: number) => void,
  ): Promise<T> {
    const id = this.nextId++;
    const promise = new Promise<T>((resolve, reject) => {
      const pending: Pending = {
        resolve: resolve as (value: Record<string, unknown>) => void,
        reject,
        op,
        startedAt: Date.now(),
        onProgress,
      };
      this.pending.set(id, pending);
      this.rearm(id, pending);
    });
    stdin.write(`${JSON.stringify({ id, op, ...payload })}\n`);
    onSent?.(id);
    return promise;
  }
}
