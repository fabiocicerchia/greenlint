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
  projectScanIntervalMinutes: number;
  maxFileBytes: number;
  respectEditorExcludes: boolean;
  exclude: string[];
  cacheEntries: number;
  severityLevels: Record<Severity, vscode.DiagnosticSeverity>;
  showCo2eEstimate: boolean;
  trace: boolean;
}

const LEVELS: Record<string, vscode.DiagnosticSeverity> = {
  Error: vscode.DiagnosticSeverity.Error,
  Warning: vscode.DiagnosticSeverity.Warning,
  Information: vscode.DiagnosticSeverity.Information,
  Hint: vscode.DiagnosticSeverity.Hint,
};

const DEFAULT_LEVELS: Record<Severity, vscode.DiagnosticSeverity> = {
  high: vscode.DiagnosticSeverity.Warning,
  medium: vscode.DiagnosticSeverity.Information,
  low: vscode.DiagnosticSeverity.Hint,
};

export function readSettings(scope?: vscode.Uri): Settings {
  const config = vscode.workspace.getConfiguration('greenlint', scope);
  const configured = config.get<Record<string, string>>('severityLevels') ?? {};
  const severityLevels = { ...DEFAULT_LEVELS };
  for (const severity of ['high', 'medium', 'low'] as Severity[]) {
    const level = LEVELS[configured[severity]];
    if (level !== undefined) {
      severityLevels[severity] = level;
    }
  }
  return {
    enable: config.get<boolean>('enable', true),
    run: config.get<RunMode>('run', 'onType'),
    debounceMs: config.get<number>('debounceMs', 400),
    pythonPath: config.get<string>('pythonPath', '').trim(),
    greenlintPath: config.get<string>('greenlintPath', '').trim(),
    scanProjectOnStartup: config.get<boolean>('scanProjectOnStartup', true),
    projectScanIntervalMinutes: config.get<number>('projectScanIntervalMinutes', 0),
    maxFileBytes: config.get<number>('maxFileBytes', 1_000_000),
    respectEditorExcludes: config.get<boolean>('respectEditorExcludes', true),
    exclude: config.get<string[]>('exclude', []),
    cacheEntries: config.get<number>('cacheEntries', 4096),
    severityLevels,
    showCo2eEstimate: config.get<boolean>('showCo2eEstimate', true),
    trace: config.get<boolean>('trace', false),
  };
}

/** Settings that can only take effect by restarting the scan server. */
export function requiresRestart(previous: Settings, next: Settings): boolean {
  return (
    previous.pythonPath !== next.pythonPath ||
    previous.greenlintPath !== next.greenlintPath ||
    previous.cacheEntries !== next.cacheEntries
  );
}
