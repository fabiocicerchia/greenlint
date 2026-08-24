import assert from 'node:assert/strict';
import { test } from 'node:test';

import { compareFindings, ruleDocsUrl, useSeverityOrder } from '../types';
import type { Finding } from '../types';

const finding = (over: Partial<Finding> = {}): Finding => ({
  rule: 'GL005',
  severity: 'medium',
  file: 'b.py',
  line: 10,
  message: 'SELECT * query',
  suggestion: 'fetch only needed columns',
  co2e_estimate: '',
  ...over,
});

test('orders by severity, then file, then line', () => {
  const findings = [
    finding({ severity: 'low', file: 'a.py', line: 1 }),
    finding({ severity: 'high', file: 'z.py', line: 99 }),
    finding({ severity: 'medium', file: 'b.py', line: 20 }),
    finding({ severity: 'medium', file: 'b.py', line: 2 }),
    finding({ severity: 'medium', file: 'a.py', line: 50 }),
  ];
  assert.deepEqual(
    [...findings].sort(compareFindings).map((f) => `${f.severity}:${f.file}:${f.line}`),
    ['high:z.py:99', 'medium:a.py:50', 'medium:b.py:2', 'medium:b.py:20', 'low:a.py:1'],
  );
});

test('builds the GitHub anchor for a rule, doubled hyphen and all', () => {
  // The headings in docs/rules.md are `## GL001 — busy loop without sleep`;
  // GitHub drops the em dash and leaves the two spaces around it as hyphens.
  assert.equal(
    ruleDocsUrl({ rule: 'GL001', message: 'busy loop without sleep' }),
    'https://github.com/fabiocicerchia/greenlint/blob/main/docs/rules.md#gl001--busy-loop-without-sleep',
  );
  // Punctuation is dropped, not encoded.
  assert.match(
    ruleDocsUrl({ rule: 'GL007', message: 'quadratic rebuild in a loop (whole sequence copied)' }),
    /#gl007--quadratic-rebuild-in-a-loop-whole-sequence-copied$/,
  );
});

const at = (severity: string, file = 'a.py', line = 1): Finding =>
  finding({ severity: severity as Finding['severity'], file, line });

test('sorts by the order the scan server published', () => {
  // greenlint decides the order; this only applies it. A severity greenlint
  // added would arrive here without a change to this file.
  useSeverityOrder({ critical: 0, high: 1, medium: 2, low: 3 });
  assert.deepEqual(
    [at('low'), at('critical'), at('medium'), at('high')].sort(compareFindings).map((f) => f.severity),
    ['critical', 'high', 'medium', 'low'],
  );
});

test('sorts a severity the server did not mention last, not at random', () => {
  useSeverityOrder({ high: 0, medium: 1, low: 2 });
  assert.deepEqual(
    [at('nonsense'), at('low'), at('high')].sort(compareFindings).map((f) => f.severity),
    ['high', 'low', 'nonsense'],
  );
});

test('keeps the fallback when the server publishes no order', () => {
  useSeverityOrder({ high: 0, medium: 1, low: 2 });
  useSeverityOrder(undefined);
  useSeverityOrder({});
  assert.deepEqual(
    [at('low'), at('high'), at('medium')].sort(compareFindings).map((f) => f.severity),
    ['high', 'medium', 'low'],
  );
});
