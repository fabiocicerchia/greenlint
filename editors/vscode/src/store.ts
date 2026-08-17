import * as path from 'path';

import * as vscode from 'vscode';

import { compareFindings, type Finding, type Severity } from './types';

export interface StoreChange {
  /** Files whose findings changed. Empty when `replaced` is set. */
  files: string[];
  /** True when a project scan swapped out everything under a root. */
  replaced: boolean;
}

/**
 * Every finding the window currently knows about, keyed by file.
 *
 * Kept per file rather than as one flat list so a buffer scan replaces exactly
 * one file's findings and leaves the rest of the project scan intact — the
 * panel stays complete without rescanning anything to keep it that way.
 */
export class FindingStore {
  private readonly byFile = new Map<string, Finding[]>();
  private readonly emitter = new vscode.EventEmitter<StoreChange>();
  readonly onDidChange = this.emitter.event;
  lastProjectScan?: Date;

  /** Running totals. Maintained rather than recomputed: a streaming scan
   * updates the badge and the panel title on every batch, and walking every
   * finding each time would make the display cost grow with the results. */
  private readonly totalsBySeverity: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
  private total = 0;

  private track(findings: Finding[], sign: 1 | -1): void {
    for (const finding of findings) {
      this.totalsBySeverity[finding.severity] += sign;
      this.total += sign;
    }
  }

  private put(fsPath: string, findings: Finding[]): boolean {
    const previous = this.byFile.get(fsPath);
    if (previous) {
      this.track(previous, -1);
    }
    if (findings.length === 0) {
      return this.byFile.delete(fsPath);
    }
    this.byFile.set(fsPath, [...findings].sort(compareFindings));
    this.track(findings, 1);
    return true;
  }

  setFile(fsPath: string, findings: Finding[]): void {
    if (!this.put(fsPath, findings)) {
      // Nothing there before and nothing now: no event, so a clean file being
      // scanned on every keystroke does not repaint the panel each time.
      return;
    }
    this.emitter.fire({ files: [fsPath], replaced: false });
  }

  /**
   * Fold in one batch of a streaming project scan.
   *
   * One event for the whole batch, not one per file: the panel repaints once
   * per batch either way, and the diagnostics update is per file regardless.
   */
  mergeBatch(findings: Finding[], skip: ReadonlySet<string> = new Set()): void {
    const byFile = new Map<string, Finding[]>();
    for (const finding of findings) {
      if (skip.has(finding.file)) {
        continue;
      }
      const bucket = byFile.get(finding.file);
      if (bucket) {
        bucket.push(finding);
      } else {
        byFile.set(finding.file, [finding]);
      }
    }
    if (byFile.size === 0) {
      return;
    }
    for (const [file, bucket] of byFile) {
      // A file is scanned once per walk, so its findings arrive in one batch
      // and this replaces rather than accumulates.
      this.put(file, bucket);
    }
    this.emitter.fire({ files: [...byFile.keys()], replaced: false });
  }

  /**
   * End of a streaming scan: drop what the walk did not report.
   *
   * `keep` is the files the scan found something in, so anything else under
   * the root has been fixed or deleted since the last scan. Only correct once
   * the walk has finished — pruning a partial scan would delete findings for
   * files it simply had not reached yet.
   */
  pruneUnder(root: string, keep: ReadonlySet<string>, dirty: ReadonlySet<string>): void {
    const prefix = root.endsWith(path.sep) ? root : root + path.sep;
    const removed: string[] = [];
    for (const file of [...this.byFile.keys()]) {
      if ((file === root || file.startsWith(prefix)) && !keep.has(file) && !dirty.has(file)) {
        this.put(file, []);
        removed.push(file);
      }
    }
    this.lastProjectScan = new Date();
    if (removed.length > 0) {
      this.emitter.fire({ files: removed, replaced: false });
    }
  }

  forget(fsPath: string): void {
    if (this.put(fsPath, [])) {
      this.emitter.fire({ files: [fsPath], replaced: false });
    }
  }

  clear(): void {
    this.byFile.clear();
    this.total = 0;
    this.totalsBySeverity.high = 0;
    this.totalsBySeverity.medium = 0;
    this.totalsBySeverity.low = 0;
    this.lastProjectScan = undefined;
    this.emitter.fire({ files: [], replaced: true });
  }

  forFile(fsPath: string): Finding[] {
    return this.byFile.get(fsPath) ?? [];
  }

  files(): string[] {
    return [...this.byFile.keys()];
  }

  all(): Finding[] {
    return [...this.byFile.values()].flat().sort(compareFindings);
  }

  get size(): number {
    return this.total;
  }

  /** The running totals, free to read. */
  totals(): Record<Severity, number> {
    return { ...this.totalsBySeverity };
  }

  /** Totals over an arbitrary list — a filtered view, say — which has to be
   * counted because it is not what the store is keeping track of. */
  countsBySeverity(findings: Finding[]): Record<Severity, number> {
    const counts: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
    for (const finding of findings) {
      counts[finding.severity] += 1;
    }
    return counts;
  }

  dispose(): void {
    this.emitter.dispose();
  }
}
