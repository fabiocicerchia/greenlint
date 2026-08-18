import assert from 'node:assert/strict';
import { test } from 'node:test';

import { FindingsProvider } from '../findingsView';
import { FindingStore } from '../store';
import type { Finding } from '../types';

const finding = (file: string, over: Partial<Finding> = {}): Finding => ({
  rule: 'GL005',
  severity: 'medium',
  file,
  line: 1,
  message: 'SELECT * query',
  suggestion: 'fetch only needed columns',
  co2e_estimate: '',
  ...over,
});

function provider(findings: Finding[]) {
  const store = new FindingStore();
  for (const f of findings) {
    store.setFile(f.file, [...store.forFile(f.file), f]);
  }
  return new FindingsProvider(store);
}

const labels = (nodes: unknown[]) => nodes.map((n) => (n as { label: string }).label);

test('groups by file out of the box, like the sibling extensions', () => {
  const view = provider([finding('/proj/a.py'), finding('/proj/sub/b.py'), finding('/proj/a.py')]);
  assert.equal(view.grouping, 'file');
  const groups = view.getChildren() as Array<{ label: string; children: Finding[] }>;
  assert.deepEqual(labels(groups).sort(), ['a.py', 'b.py']);
  assert.equal(groups.find((g) => g.label === 'a.py')?.children.length, 2);
});

test('drops the group level when it would name the file already in scope', () => {
  const view = provider([finding('/proj/a.py'), finding('/proj/b.py')]);
  view.scope = 'file';
  view.setCurrentFile('/proj/a.py');
  const nodes = view.getChildren() as Finding[];
  assert.deepEqual(
    nodes.map((n) => n.file),
    ['/proj/a.py'],
  );
});

test('still groups by severity or rule when asked', () => {
  const view = provider([
    finding('/proj/a.py', { severity: 'high', rule: 'GL003' }),
    finding('/proj/b.py', { severity: 'low', rule: 'GL002' }),
  ]);
  view.grouping = 'severity';
  assert.deepEqual(labels(view.getChildren()), ['high', 'low']);
  view.grouping = 'rule';
  assert.deepEqual(
    labels(view.getChildren()).map((l) => l.split(' ')[0]),
    ['GL003', 'GL002'],
  );
});

test('empty severity groups do not appear', () => {
  const view = provider([finding('/proj/a.py', { severity: 'medium' })]);
  view.grouping = 'severity';
  assert.deepEqual(labels(view.getChildren()), ['medium']);
});
