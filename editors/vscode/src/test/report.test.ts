import assert from 'node:assert/strict';
import { test } from 'node:test';

import { renderReport } from '../report';
import type { Finding } from '../types';

const finding = (over: Partial<Finding> = {}): Finding => ({
  rule: 'GL005',
  severity: 'medium',
  file: '/proj/src/db.py',
  line: 44,
  message: 'SELECT * query',
  suggestion: 'fetch only needed columns',
  co2e_estimate: '~15 gCO2e per GB',
  ...over,
});

const meta = {
  scopeLabel: 'whole project',
  generatedAt: new Date('2026-08-15T10:30:00Z'),
  relative: (p: string) => p.replace('/proj/', ''),
};

test('reports each finding with its rule, suggestion and cost', () => {
  const html = renderReport([finding()], meta);
  assert.match(html, /GL005/);
  assert.match(html, /SELECT \* query/);
  assert.match(html, /fetch only needed columns/);
  assert.match(html, /~15 gCO2e per GB/);
  assert.match(html, /src\/db\.py:44/);
});

test('escapes findings into the page rather than through it', () => {
  // Rule text is greenlint's own, but a path is whatever is on disk.
  const html = renderReport(
    [finding({ file: '/proj/<img src=x onerror=alert(1)>.py', message: 'a & b' })],
    meta,
  );
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /a &amp; b/);
});

test('ships no script, so the webview needs no script-src', () => {
  const html = renderReport([finding()], meta);
  assert.doesNotMatch(html, /<script/i);
  assert.match(html, /default-src 'none'; style-src 'unsafe-inline';/);
});

test('says so when there is nothing to report', () => {
  const html = renderReport([], meta);
  assert.match(html, /Nothing found/);
  assert.match(html, /0 findings/);
});

test('counts one finding without the plural', () => {
  assert.match(renderReport([finding()], meta), /1 finding</);
});
