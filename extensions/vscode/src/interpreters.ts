// Which Python, and which greenlint, to try — and in what order.
//
// Apart from the scan server because it answers a question about the machine
// rather than about the protocol: where a pipx install hides, what a console
// script's shebang says, whether the workspace has its own greenlint.py. The
// search order is the difference between "greenlint is not installed" and
// "greenlint is installed and the extension cannot find it", which is the most
// reported failure this extension has.

import * as fs from 'fs';
import * as path from 'path';

import * as vscode from 'vscode';

import type { Settings } from './config';

/**
 * Candidate (interpreter, greenlint module) pairs, most likely first.
 *
 * An explicitly configured path is the only candidate — a typo there should
 * be an error, not a silent fallback to some other greenlint whose rules the
 * user never asked for.
 *
 * Otherwise a greenlint.py in the workspace comes before the installed
 * package, for two reasons that turn out to be the same one: someone editing
 * the rules wants to see their edits, and an installed release can be older
 * than the module surface this extension needs. A candidate whose greenlint
 * is too old refuses to start, so the loop simply moves on to the next.
 */
export function candidates(settings: Settings): Array<{ python: string; module?: string }> {
  if (settings.pythonPath && settings.greenlintPath) {
    return [{ python: settings.pythonPath, module: settings.greenlintPath }];
  }
  const plain = settings.pythonPath
    ? [settings.pythonPath]
    : process.platform === 'win32'
      ? ['python', 'py']
      : ['python3', 'python'];
  const pairs: Array<{ python: string; module?: string }> = [];
  // A module loaded from a path needs no particular interpreter — any Python
  // that runs will import it — so these come first and only need `plain`.
  for (const module of settings.greenlintPath
    ? [settings.greenlintPath]
    : workspaceGreenlintModules()) {
    for (const python of plain) {
      pairs.push({ python, module });
    }
  }
  if (!settings.greenlintPath) {
    // `import greenlint`, which is a question about the interpreter rather
    // than about greenlint: pipx and venv installs are deliberately invisible
    // to the `python3` on PATH, so the interpreter that owns the `greenlint`
    // command gets a turn too.
    for (const python of settings.pythonPath
      ? plain
      : dedupe([...plain, ...interpretersOwningGreenlint()])) {
      pairs.push({ python });
    }
  }
  return pairs;
}

export function dedupe(values: string[]): string[] {
  return [...new Set(values)];
}

/** Workspace folders that contain a greenlint.py, for contributors working on
 * the rules themselves — their checkout should win over an installed release. */
function workspaceGreenlintModules(): string[] {
  const found: string[] = [];
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const candidate = path.join(folder.uri.fsPath, 'greenlint.py');
    if (fs.existsSync(candidate)) {
      found.push(candidate);
    }
  }
  return found;
}

/**
 * Interpreters that can plausibly `import greenlint` even though the `python3`
 * on PATH cannot.
 *
 * The documented install is `pipx`, which puts greenlint in its own virtualenv
 * precisely so it does not appear in any interpreter on PATH — so looking only
 * at `python3` fails for exactly the users who followed the instructions. Two
 * cheap ways to find the real one: the shebang of the `greenlint` command
 * (a console script names its own interpreter on line one), and pipx's
 * standard venv layout.
 */
function interpretersOwningGreenlint(): string[] {
  const found: string[] = [];
  const script = onPath('greenlint');
  if (script) {
    try {
      const shebang = /^#!\s*("?)(\S+?)\1(?:\s|$)/.exec(
        fs.readFileSync(script, 'utf8').slice(0, 512).split('\n')[0] ?? '',
      );
      // A pyenv or asdf shim is a shell script, so its shebang is a shell —
      // only take the line seriously when it actually names a Python.
      if (shebang && /python/i.test(path.basename(shebang[2]))) {
        found.push(shebang[2]);
      }
    } catch {
      // Unreadable or binary: nothing to learn, and not worth reporting.
    }
  }
  const home = process.env.HOME ?? process.env.USERPROFILE;
  if (home) {
    const pipx =
      process.platform === 'win32'
        ? path.join(home, 'pipx', 'venvs', 'greenlint', 'Scripts', 'python.exe')
        : path.join(home, '.local', 'pipx', 'venvs', 'greenlint', 'bin', 'python');
    if (fs.existsSync(pipx)) {
      found.push(pipx);
    }
  }
  return found;
}

/** First executable named `command` on PATH. */
function onPath(command: string): string | undefined {
  const extensions = process.platform === 'win32' ? ['.exe', '.cmd', '.bat', ''] : [''];
  for (const dir of (process.env.PATH ?? '').split(path.delimiter)) {
    if (!dir) {
      continue;
    }
    for (const extension of extensions) {
      const candidate = path.join(dir, command + extension);
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    }
  }
  return undefined;
}
