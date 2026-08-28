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

// --- expand and collapse -----------------------------------------------------
//
// Setting `expanded` and firing a refresh is not enough on its own: VS Code
// reads `collapsibleState` only the first time it sees an element, then keeps
// its own expansion state against that element's id. Repainting the same ids
// is ignored, which is why Collapse All did nothing. The id carries a
// generation so a collapse presents new elements.

test('collapsing gives the groups new ids, so VS Code re-reads the state', () => {
  const view = provider([finding('/repo/a.py'), finding('/repo/b.py')]);
  const before = view.getChildren();
  const idBefore = view.getTreeItem(before[0]).id;
  assert.ok(idBefore, 'groups need an id for the expansion state to key on');

  view.setExpanded(false);
  const item = view.getTreeItem(view.getChildren()[0]);
  assert.notEqual(item.id, idBefore);
  assert.equal(item.collapsibleState, 1, 'Collapsed');

  view.setExpanded(true);
  assert.equal(view.getTreeItem(view.getChildren()[0]).collapsibleState, 2, 'Expanded');
});

test('an ordinary repaint keeps the ids, so hand-opened groups stay open', () => {
  // A streaming scan repaints every half second; if that changed the ids it
  // would slam every group shut while the user was reading one.
  const view = provider([finding('/repo/a.py')]);
  const before = view.getTreeItem(view.getChildren()[0]).id;
  view.refresh();
  assert.equal(view.getTreeItem(view.getChildren()[0]).id, before);
});

test('group ids are unique when two directories share a basename', () => {
  const view = provider([finding('/repo/a/util.py'), finding('/repo/b/util.py')]);
  const ids = view.getChildren().map((g) => view.getTreeItem(g).id);
  assert.equal(new Set(ids).size, 2, 'two groups collided on one id');
});

test('the id distinguishes the grouping, so switching regroups cleanly', () => {
  const view = provider([finding('/repo/a.py', { severity: 'high' })]);
  const byFile = view.getTreeItem(view.getChildren()[0]).id;
  view.grouping = 'severity';
  assert.notEqual(view.getTreeItem(view.getChildren()[0]).id, byFile);
});
