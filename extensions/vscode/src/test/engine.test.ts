import assert from 'node:assert/strict';
import { test } from 'node:test';

import { share } from '../engine';
import type { Finding } from '../types';

// `JSON.parse` gives every finding its own copy of its rule's message,
// suggestion and CO2e note, and of its file's path. Identity is the assertion
// because that is the whole claim: one string, not one per finding. Equality
// would pass while the memory it saves went away.
const finding = (over: Partial<Finding> = {}): Finding =>
  JSON.parse(
    JSON.stringify({
      rule: 'GL005',
      severity: 'medium',
      file: '/proj/src/db.py',
      line: 1,
      message: 'SELECT * query',
      suggestion: 'fetch only needed columns',
      co2e_estimate: '~15 gCO2e per GB of columns never read',
      ...over,
    }),
  ) as Finding;

test('holds one copy of a rule prose and one of a repeated path', () => {
  const [first, second] = share([finding(), finding({ line: 9 })]);
  assert.equal(first.message, 'SELECT * query');
  for (const field of ['message', 'suggestion', 'co2e_estimate', 'file'] as const) {
    assert.ok(first[field] === second[field], `${field} was not shared`);
  }
});

test('does not put one rule\'s prose on another rule', () => {
  const [a, b] = share([finding(), finding({ rule: 'GL003', message: 'every-minute cron' })]);
  assert.equal(a.message, 'SELECT * query');
  assert.equal(b.message, 'every-minute cron');
});

test('keeps each path when findings from two files are interleaved', () => {
  // The path is shared against the previous finding only, which is what keeps
  // it from retaining a path once the batch is gone. Interleaving is the case
  // that would break if it were shared against the wrong one.
  const shared = share([
    finding({ file: '/proj/a.py' }),
    finding({ file: '/proj/b.py' }),
    finding({ file: '/proj/a.py', line: 2 }),
  ]);
  assert.deepEqual(
    shared.map((f) => f.file),
    ['/proj/a.py', '/proj/b.py', '/proj/a.py'],
  );
});
