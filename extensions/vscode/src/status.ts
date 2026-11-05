import * as vscode from "vscode";

import { countBySeverity, type FindingsProvider } from "./findingsView";
import type { ScanStats, ScanSummary } from "./types";

/**
 * The status bar line, and behind it the end-of-scan aggregate.
 *
 * The counts in the bar follow the panel's scope; the tooltip reports the
 * whole project as the last scan computed it, so "3 findings in this file"
 * and "412 across the project" are both one glance away.
 */
export function paintStatus(
  status: vscode.StatusBarItem,
  findings: FindingsProvider,
  total: number,
  lastStats?: ScanStats,
  lastSummary?: ScanSummary,
): void {
  const counts = countBySeverity(findings.findings());
  status.text =
    total === 0
      ? lastStats
        ? "$(check) greenlint"
        : "$(circle-large-outline) greenlint"
      : `$(flame) ${counts.high} $(warning) ${counts.medium} $(info) ${counts.low}`;
  const tooltip = new vscode.MarkdownString(undefined, true);
  tooltip.appendMarkdown(`**greenlint** — ${findings.describeScope()}`);
  if (lastSummary) {
    const { bySeverity: by, total: all, files } = lastSummary;
    tooltip.appendMarkdown(
      `\n\nWhole project: ${all} finding${all === 1 ? "" : "s"} in ${files} file${
        files === 1 ? "" : "s"
      } — $(flame) ${by.high} · $(warning) ${by.medium} · $(info) ${by.low}`,
    );
  }
  if (lastStats) {
    tooltip.appendMarkdown(
      `\n\nLast scan: ${lastStats.files} files in ${lastStats.ms} ms ` +
        `(${lastStats.scanned} scanned, ` +
        `${lastStats.reusedFromStat + lastStats.reusedFromHash} cached)`,
    );
  }
  status.tooltip = tooltip;
  status.show();
}
