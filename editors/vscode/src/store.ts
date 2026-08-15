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

  setFile(fsPath: string, findings: Finding[]): void {
    if (findings.length === 0) {
      if (!this.byFile.delete(fsPath)) {
        // Nothing there before and nothing now: no event, so a clean file being
        // scanned on every keystroke does not repaint the panel each time.
        return;
      }
    } else {
      this.byFile.set(fsPath, [...findings].sort(compareFindings));
    }
    this.emitter.fire({ files: [fsPath], replaced: false });
  }

  /** Swap in a project scan's results, keeping the given paths untouched
   * (unsaved buffers, whose on-disk contents are not what is being edited). */
  replaceUnder(root: string, findings: Finding[], keep: ReadonlySet<string>): void {
    const prefix = root.endsWith(path.sep) ? root : root + path.sep;
    for (const file of [...this.byFile.keys()]) {
      if ((file === root || file.startsWith(prefix)) && !keep.has(file)) {
        this.byFile.delete(file);
      }
    }
    for (const finding of findings) {
      if (keep.has(finding.file)) {
        continue;
      }
      const bucket = this.byFile.get(finding.file);
      if (bucket) {
        bucket.push(finding);
      } else {
        this.byFile.set(finding.file, [finding]);
      }
    }
    for (const bucket of this.byFile.values()) {
      bucket.sort(compareFindings);
    }
    this.lastProjectScan = new Date();
    this.emitter.fire({ files: [], replaced: true });
  }

  forget(fsPath: string): void {
    if (this.byFile.delete(fsPath)) {
      this.emitter.fire({ files: [fsPath], replaced: false });
    }
  }

  clear(): void {
    this.byFile.clear();
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
    let total = 0;
    for (const bucket of this.byFile.values()) {
      total += bucket.length;
    }
    return total;
  }

  countsBySeverity(findings: Finding[] = this.all()): Record<Severity, number> {
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
