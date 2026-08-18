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
}

export const SEVERITY_ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2 };

export function compareFindings(a: Finding, b: Finding): number {
  return (
    SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
    a.file.localeCompare(b.file) ||
    a.line - b.line
  );
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
