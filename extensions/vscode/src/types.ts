/** The shape greenlint's own `_finding()` produces, unchanged. */
export type Severity = 'high' | 'medium' | 'low';

export interface Finding {
  rule: string;
  severity: Severity;
  /** Absolute path, as the scan server was given it. */
  file: string;
  /** 1-based, as everything outside an editor counts lines. */
  line: number;
  message: string;
  suggestion: string;
  co2e_estimate: string;
}

/** What a project scan cost, so the caching is observable rather than claimed. */
export interface ScanStats {
  files: number;
  reusedFromStat: number;
  reusedFromHash: number;
  scanned: number;
  skipped: number;
  ms: number;
  cache: { entries: number; statHits: number; hashHits: number; misses: number };
}

/** The end-of-scan aggregate, computed once over the whole set.
 *
 * Counts and nothing else: the CO2e hints are prose about different physical
 * quantities — grams per GB, grams per instance-day, "negligible per call" —
 * so a single number summing them would have no unit and a false air of
 * precision, which is the one thing greenlint is careful not to produce.
 */
export interface ScanSummary {
  total: number;
  bySeverity: Record<Severity, number>;
  byRule: Record<string, number>;
  files: number;
}

export interface ServerInfo {
  protocol: number;
  version: string;
  rules: number;
  python: string;
  module: string | null;
  /** greenlint's severity ordering. Absent from a server older than this field. */
  severityOrder?: Record<string, number>;
}

/**
 * greenlint's own ordering, as the scan server reports it.
 *
 * The panel merges findings from several scans — a freshly typed buffer on top
 * of a cached project walk — so it has to sort the merged list here. *Which*
 * order that is remains greenlint's decision (`finding_sort_key`), so it is
 * read from the server rather than restated: a severity added over there needs
 * no change here, and cannot end up sorted differently in the two places.
 *
 * The fallback is only in play before the first ping answers.
 */
let severityRank: Record<string, number> = { high: 0, medium: 1, low: 2 };

export function useSeverityOrder(order: Record<string, number> | undefined): void {
  if (order && Object.keys(order).length > 0) {
    severityRank = { ...order };
  }
}

/** An unknown severity sorts last rather than sorting randomly. */
const rankOf = (severity: string): number => severityRank[severity] ?? Number.MAX_SAFE_INTEGER;

/** Code-unit order for the path, not `localeCompare`: greenlint's own
 * `finding_sort_key` compares Python strings, so a locale-aware collation here
 * would put the merged list in a different order from the one the CLI prints —
 * and it costs an ICU call per comparison, which a project-wide sort makes
 * thousands of. */
const comparePaths = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

export function compareFindings(a: Finding, b: Finding): number {
  return rankOf(a.severity) - rankOf(b.severity) || comparePaths(a.file, b.file) || a.line - b.line;
}

/**
 * Anchor for a rule's section in `docs/rules.md`, following GitHub's slug rules
 * (lowercase, punctuation dropped, spaces to hyphens). The headings there are
 * `## GL001 — busy loop without sleep`, so the em dash leaves the doubled
 * hyphen you see in the result.
 */
export function ruleDocsUrl(finding: { rule: string; message: string }): string {
  const slug = `${finding.rule} — ${finding.message}`
    .toLowerCase()
    .replace(/[^a-z0-9 _-]/g, '')
    .replace(/ /g, '-');
  return `https://github.com/fabiocicerchia/greenlint/blob/main/docs/rules.md#${slug}`;
}
