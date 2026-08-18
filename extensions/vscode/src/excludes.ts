import * as path from 'path';

import * as vscode from 'vscode';

/**
 * VS Code's exclude settings, as greenlint ignore globs.
 *
 * The editor already knows what is not your code — `files.exclude` hides it
 * from the explorer, `search.exclude` keeps it out of results — and greenlint
 * had no way to know, so it walked `dist/`, `.venv/` and every vendored tree
 * the editor was busy pretending did not exist.
 *
 * The translation matters as much as the list. greenlint matches with
 * `fnmatch`, whose `*` crosses `/`, and its walk can only skip a directory
 * outright for a pattern shaped `<base>/*` — so each exclude produces both the
 * entry itself and everything under it. Getting that second form right is the
 * difference between filtering a directory's files one by one and never
 * opening the directory.
 */
export function editorExcludeGlobs(folder: vscode.WorkspaceFolder): string[] {
  const globs = new Set<string>();
  for (const section of ['files', 'search'] as const) {
    const excludes =
      vscode.workspace.getConfiguration(section, folder.uri).get<Record<string, unknown>>('exclude') ??
      {};
    for (const [pattern, enabled] of Object.entries(excludes)) {
      // A value can also be a `{ "when": ... }` condition, which is about a
      // sibling file rather than this path; only a plain `true` is a
      // straightforward "never look here".
      if (enabled !== true) {
        continue;
      }
      for (const expanded of expandBraces(pattern)) {
        for (const glob of toIgnoreGlobs(expanded, folder)) {
          globs.add(glob);
        }
      }
    }
  }
  return [...globs].sort();
}

// Brace alternatives, which fnmatch has no syntax for: a pattern matching
// `.js` or `.map` becomes one pattern for each.
export function expandBraces(pattern: string): string[] {
  const match = /\{([^{}]*)\}/.exec(pattern);
  if (!match) {
    return [pattern];
  }
  return match[1]
    .split(',')
    .flatMap((option) =>
      expandBraces(pattern.slice(0, match.index) + option + pattern.slice(match.index + match[0].length)),
    );
}

/**
 * One VS Code exclude pattern as the ignore globs it corresponds to.
 *
 * A pattern led by a doubled star means "at any depth"; anything else is
 * relative to the workspace root, so it only makes sense once anchored to that
 * root's real path.
 */
export function toIgnoreGlobs(pattern: string, folder: vscode.WorkspaceFolder): string[] {
  const trimmed = pattern.replace(/\/+$/, '').replace(/\/\*\*$/, '');
  if (!trimmed) {
    return [];
  }
  // fnmatch has no `**`: its `*` already crosses `/`, which is what `**` means.
  const flattened = trimmed.replace(/\*\*/g, '*');
  const anchored = flattened.startsWith('*/')
    ? flattened
    : `${posix(folder.uri.fsPath)}/${flattened.replace(/^\.\//, '')}`;
  // The entry itself, and — the form the walk can prune on — everything below it.
  return [anchored, `${anchored}/*`];
}

/** greenlint matches `Path.as_posix()`, which on Windows is `C:/foo`. */
function posix(fsPath: string): string {
  return fsPath.split(path.sep).join('/');
}
