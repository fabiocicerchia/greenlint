import type { Finding } from './types';

/** One copy of each rule's prose, keyed by rule id — see `share`. */
const ruleProse = new Map<string, { message: string; suggestion: string; co2e: string }>();

/**
 * Point every finding's repeated strings at one instance.
 *
 * greenlint's message, suggestion and CO2e note are fixed per rule, and its
 * path is fixed per file — but they cross the pipe as JSON, and `JSON.parse`
 * gives every finding its own copy of all four. On a project with thousands of
 * findings that is megabytes of the same few sentences, held for as long as the
 * window is open. The prose is shared through a map (bounded by the rule count);
 * the path only against the previous finding, which is enough because a file's
 * findings arrive together — and keeps no path alive after the batch.
 */
export function share(findings: Finding[]): Finding[] {
  let lastFile: string | undefined;
  for (const finding of findings) {
    const prose = ruleProse.get(finding.rule);
    if (prose) {
      finding.message = prose.message;
      finding.suggestion = prose.suggestion;
      finding.co2e_estimate = prose.co2e;
    } else {
      ruleProse.set(finding.rule, {
        message: finding.message,
        suggestion: finding.suggestion,
        co2e: finding.co2e_estimate,
      });
    }
    if (lastFile !== undefined && finding.file === lastFile) {
      finding.file = lastFile;
    } else {
      lastFile = finding.file;
    }
  }
  return findings;
}

/** Forget the shared prose. A restart can be an upgrade, and a rule's wording
 * is the upgraded greenlint's to state — so the copies go with the old process. */
export function forgetRuleProse(): void {
  ruleProse.clear();
}
