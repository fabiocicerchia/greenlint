import assert from 'node:assert/strict';
import { test } from 'node:test';

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

test('replaces one file without touching the rest', () => {
  const store = new FindingStore();
  store.setFile('/p/a.py', [finding('/p/a.py')]);
  store.setFile('/p/b.py', [finding('/p/b.py')]);
  store.setFile('/p/a.py', []);
  assert.deepEqual(store.forFile('/p/a.py'), []);
  assert.equal(store.forFile('/p/b.py').length, 1);
  assert.equal(store.size, 1);
});

test('stays quiet when a clean file is scanned again', () => {
  // Otherwise every keystroke in a file with no findings repaints the panel.
  const store = new FindingStore();
  let events = 0;
  store.onDidChange(() => (events += 1));
  store.setFile('/p/a.py', []);
  store.setFile('/p/a.py', []);
  assert.equal(events, 0);
});

test('announces a batch once, naming the files it moved', () => {
  const store = new FindingStore();
  const seen: Array<string[] | undefined> = [];
  store.onDidChange((files) => seen.push(files));
  store.mergeBatch([finding('/p/a.py'), finding('/p/b.py'), finding('/p/a.py', { line: 9 })]);
  assert.equal(seen.length, 1);
  assert.deepEqual(seen[0], ['/p/a.py', '/p/b.py']);
  assert.equal(store.size, 3);
});

test('leaves unsaved buffers out of a batch', () => {
  // The buffer's own scan is the truth; the walk read the last-saved bytes.
  const store = new FindingStore();
  store.mergeBatch([finding('/p/a.py'), finding('/p/dirty.py')], new Set(['/p/dirty.py']));
  assert.equal(store.forFile('/p/dirty.py').length, 0);
  assert.equal(store.forFile('/p/a.py').length, 1);
});

test('prunes what the finished walk did not report, and nothing else', () => {
  const store = new FindingStore();
  store.setFile('/p/fixed.py', [finding('/p/fixed.py')]);
  store.setFile('/p/still.py', [finding('/p/still.py')]);
  store.setFile('/p/dirty.py', [finding('/p/dirty.py')]);
  store.setFile('/other/x.py', [finding('/other/x.py')]);
  store.pruneUnder('/p', new Set(['/p/still.py']), new Set(['/p/dirty.py']));
  assert.deepEqual(
    [...store.entries()].map(([file]) => file).sort(),
    ['/other/x.py', '/p/dirty.py', '/p/still.py'],
  );
});

test('keeps findings ordered worst-first however they arrived', () => {
  const store = new FindingStore();
  store.setFile('/p/a.py', [
    finding('/p/a.py', { severity: 'low', line: 3 }),
    finding('/p/a.py', { severity: 'high', line: 9 }),
  ]);
  store.mergeBatch([finding('/p/b.py', { severity: 'medium' })]);
  assert.deepEqual(store.all().map((f) => f.severity), ['high', 'medium', 'low']);
});
