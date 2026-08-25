import * as path from 'path';

import * as vscode from 'vscode';

import { compareFindings, type Finding } from './types';

/**
 * Every finding the window currently knows about, keyed by file.
 *
 * Kept per file rather than as one flat list so a buffer scan replaces exactly
 * one file's findings and leaves the rest of the project scan intact — the
 * panel stays complete without rescanning anything to keep it that way.
 */
export class FindingStore {
  private readonly byFile = new Map<string, Finding[]>();
  /** The files whose findings changed, or undefined for "everything". */
  private readonly emitter = new vscode.EventEmitter<string[] | undefined>();
  readonly onDidChange = this.emitter.event;

  /** Running total. Maintained rather than recomputed: a streaming scan
   * updates the badge on every batch, and counting every finding each time
   * would make the display cost grow with the results. */
  private total = 0;
  /** `all()`, held until something changes it. One repaint asks for the whole
   * project four times over — the panel, its title, the status bar, the report
   * — and re-flattening and re-sorting every finding for each of them made a
   * streaming scan quadratic in what it had already found. */
  private flattened?: Finding[];

  private put(fsPath: string, findings: Finding[]): boolean {
    const previous = this.byFile.get(fsPath);
    this.total -= previous?.length ?? 0;
    this.flattened = undefined;
    if (findings.length === 0) {
      return this.byFile.delete(fsPath);
    }
    this.byFile.set(fsPath, [...findings].sort(compareFindings));
    this.total += findings.length;
    return true;
  }

  setFile(fsPath: string, findings: Finding[]): void {
    if (!this.put(fsPath, findings)) {
      // Nothing there before and nothing now: no event, so a clean file being
      // scanned on every keystroke does not repaint the panel each time.
      return;
    }
    this.emitter.fire([fsPath]);
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
    this.emitter.fire([...byFile.keys()]);
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
    if (removed.length > 0) {
      this.emitter.fire(removed);
    }
  }

  clear(): void {
    this.byFile.clear();
    this.total = 0;
    this.flattened = undefined;
    this.emitter.fire(undefined);
  }

  forFile(fsPath: string): Finding[] {
    return this.byFile.get(fsPath) ?? [];
  }

  entries(): Iterable<[string, Finding[]]> {
    return this.byFile.entries();
  }

  /** Every finding, worst first. The returned array is shared — treat it as
   * read-only; it is handed to the panel, the report and the status bar in the
   * same repaint. */
  all(): Finding[] {
    if (!this.flattened) {
      // Each file's list is already sorted, so this only has to merge them —
      // but a flat sort of an almost-sorted array is what V8's TimSort is good
      // at, and it is one line rather than a merge.
      this.flattened = [...this.byFile.values()].flat().sort(compareFindings);
    }
    return this.flattened;
  }

  get size(): number {
    return this.total;
  }

  dispose(): void {
    this.emitter.dispose();
  }
}
