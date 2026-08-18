import * as vscode from 'vscode';

import type { Severity } from './types';

export type RunMode = 'onType' | 'onSave' | 'manual';

export interface Settings {
  enable: boolean;
  run: RunMode;
  debounceMs: number;
  pythonPath: string;
  greenlintPath: string;
  scanProjectOnStartup: boolean;
  maxFileBytes: number;
  respectEditorExcludes: boolean;
  exclude: string[];
  trace: boolean;
}

/** greenlint's own severities as editor squiggles. Fixed rather than
 * configurable: three levels with a natural order do not need a settings UI. */
export const SEVERITY_LEVELS: Record<Severity, vscode.DiagnosticSeverity> = {
  high: vscode.DiagnosticSeverity.Warning,
  medium: vscode.DiagnosticSeverity.Information,
  low: vscode.DiagnosticSeverity.Hint,
};

export function readSettings(): Settings {
  const config = vscode.workspace.getConfiguration('greenlint');
  return {
    enable: config.get<boolean>('enable', true),
    run: config.get<RunMode>('run', 'onType'),
    debounceMs: config.get<number>('debounceMs', 400),
    pythonPath: config.get<string>('pythonPath', '').trim(),
    greenlintPath: config.get<string>('greenlintPath', '').trim(),
    scanProjectOnStartup: config.get<boolean>('scanProjectOnStartup', true),
    maxFileBytes: config.get<number>('maxFileBytes', 1_000_000),
    respectEditorExcludes: config.get<boolean>('respectEditorExcludes', true),
    exclude: config.get<string[]>('exclude', []),
    trace: config.get<boolean>('trace', false),
  };
}

/** Settings that can only take effect by restarting the scan server. */
export function requiresRestart(previous: Settings, next: Settings): boolean {
  return (
    previous.pythonPath !== next.pythonPath || previous.greenlintPath !== next.greenlintPath
  );
}
