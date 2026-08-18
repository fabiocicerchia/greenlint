import assert from 'node:assert/strict';
import { test } from 'node:test';

import { editorExcludeGlobs, expandBraces, toIgnoreGlobs } from '../excludes';
import { configuration } from './vscode-shim';

const folder = { uri: { fsPath: '/home/fabio/proj' } } as never;

test('expands brace alternatives, which fnmatch has no syntax for', () => {
  assert.deepEqual(expandBraces('**/*.{log,tmp}'), ['**/*.log', '**/*.tmp']);
  assert.deepEqual(expandBraces('**/node_modules'), ['**/node_modules']);
  assert.deepEqual(expandBraces('{a,b}/{c,d}'), ['a/c', 'a/d', 'b/c', 'b/d']);
});

test('emits both the entry and everything under it', () => {
  // The second form is the one greenlint's walk can prune a directory on.
  assert.deepEqual(toIgnoreGlobs('**/node_modules', folder), [
    '*/node_modules',
    '*/node_modules/*',
  ]);
});

test('anchors a root-relative pattern to the real workspace path', () => {
  // `out` means this project's out, not every out on the disk.
  assert.deepEqual(toIgnoreGlobs('out', folder), [
    '/home/fabio/proj/out',
    '/home/fabio/proj/out/*',
  ]);
});

test('treats a trailing globstar as the directory itself', () => {
  assert.deepEqual(toIgnoreGlobs('**/dist/**', folder), ['*/dist', '*/dist/*']);
});

test('takes both exclude settings, and only the plain true ones', () => {
  configuration.files = {
    '**/.git': true,
    '**/conditional': { when: '$(basename).ts' }, // a condition, not a skip
    '**/disabled': false,
    out: true,
  };
  configuration.search = { '**/node_modules': true };
  const globs = editorExcludeGlobs(folder);
  assert.deepEqual(globs, [
    '*/.git',
    '*/.git/*',
    '*/node_modules',
    '*/node_modules/*',
    '/home/fabio/proj/out',
    '/home/fabio/proj/out/*',
  ]);
  assert.equal(
    globs.some((g) => g.includes('conditional') || g.includes('disabled')),
    false,
  );
});
