import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

// ── Constants ───────────────────────────────────────────────────────────────

const CRITIC_SCRIPT_NAME = 'vortex-critic.py';
const FLEET_LOG_DIR = path.join(
  process.env.HOME ?? '/Users/ryyota',
  '.gemini/antigravity/fleet-logs'
);

// ── Resolve Script Paths ────────────────────────────────────────────────────

function resolveCriticScript(): string {
  const config = vscode.workspace.getConfiguration('vortex');
  const custom = config.get<string>('criticScript');
  if (custom && fs.existsSync(custom)) { return custom; }

  // Auto-detect relative to extension parent
  const candidates = [
    path.join(__dirname, '../../critic', CRITIC_SCRIPT_NAME),
    path.join(process.env.HOME ?? '', 'neural-override-proxy/critic', CRITIC_SCRIPT_NAME),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) { return c; }
  }
  return '';
}

// ── VORTEX Critic Runner ────────────────────────────────────────────────────

interface AuditResult {
  verdict: 'VERIFIED' | 'UNVERIFIED' | 'ERROR';
  text: string;
  preset: string;
  elapsed: number;
}

async function runVortexAudit(code: string, workspaceRoot: string): Promise<AuditResult> {
  const criticScript = resolveCriticScript();
  if (!criticScript) {
    return { verdict: 'ERROR', text: 'vortex-critic.py not found', preset: '', elapsed: 0 };
  }

  const config = vscode.workspace.getConfiguration('vortex');
  const preset = config.get<string>('preset') ?? '渦';

  const input = JSON.stringify({
    prompt: `Code to audit:\n\`\`\`\n${code}\n\`\`\`\nGive evidence-based audit. End with VERDICT: VERIFIED or VERDICT: UNVERIFIED.`,
    workspaceRoot,
    preset,
  });

  const start = Date.now();

  return new Promise<AuditResult>((resolve) => {
    const proc = cp.spawn('python3', [criticScript], {
      cwd: workspaceRoot || undefined,
    });

    let stdout = '';
    let stderr = '';
    proc.stdin.write(input);
    proc.stdin.end();
    proc.stdout.on('data', (d) => { stdout += d.toString(); });
    proc.stderr.on('data', (d) => { stderr += d.toString(); });
    proc.on('close', () => {
      const elapsed = Date.now() - start;
      let text = stdout;
      try {
        const parsed = JSON.parse(stdout);
        text = parsed?.hookSpecificOutput?.additionalContext ?? stdout;
      } catch { /* use raw */ }

      const upper = text.toUpperCase();
      const verdict = upper.includes('VERDICT: VERIFIED') ? 'VERIFIED' as const
        : upper.includes('VERDICT: UNVERIFIED') ? 'UNVERIFIED' as const
        : 'ERROR' as const;

      resolve({ verdict, text: text.trim(), preset, elapsed });
    });

    // Timeout after 25 seconds
    setTimeout(() => {
      proc.kill();
      resolve({ verdict: 'ERROR', text: 'Timeout (25s)', preset, elapsed: 25000 });
    }, 25000);
  });
}

// ── Sidebar: Status Tree ────────────────────────────────────────────────────

class StatusItem extends vscode.TreeItem {
  constructor(label: string, description?: string, icon?: string) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.description = description;
    if (icon) {
      this.iconPath = new vscode.ThemeIcon(icon);
    }
  }
}

class StatusProvider implements vscode.TreeDataProvider<StatusItem> {
  private _onDidChange = new vscode.EventEmitter<StatusItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  private lastResult: AuditResult | null = null;
  private criticPath = '';

  refresh() {
    this.criticPath = resolveCriticScript();
    this._onDidChange.fire(undefined);
  }

  setLastResult(result: AuditResult) {
    this.lastResult = result;
    this._onDidChange.fire(undefined);
  }

  getTreeItem(el: StatusItem) { return el; }

  getChildren(): StatusItem[] {
    const items: StatusItem[] = [];

    // Critic status
    items.push(new StatusItem(
      'Critic Script',
      this.criticPath ? '✅ Found' : '❌ Not found',
      this.criticPath ? 'check' : 'error'
    ));

    // Preset
    const preset = vscode.workspace.getConfiguration('vortex').get<string>('preset') ?? '渦';
    items.push(new StatusItem('PCC Preset', `#${preset}`, 'symbol-key'));

    // Last audit
    if (this.lastResult) {
      const icon = this.lastResult.verdict === 'VERIFIED' ? 'pass'
        : this.lastResult.verdict === 'UNVERIFIED' ? 'error' : 'warning';
      items.push(new StatusItem(
        'Last Verdict',
        `${this.lastResult.verdict} (${(this.lastResult.elapsed / 1000).toFixed(1)}s)`,
        icon
      ));
    } else {
      items.push(new StatusItem('Last Verdict', 'No audit yet', 'circle-outline'));
    }

    // Fleet logs count
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const logFile = path.join(FLEET_LOG_DIR, `fleet_${today}.jsonl`);
    let logCount = 0;
    try {
      const content = fs.readFileSync(logFile, 'utf-8');
      logCount = content.trim().split('\n').filter(Boolean).length;
    } catch { /* no logs yet */ }
    items.push(new StatusItem('Fleet Logs Today', `${logCount} entries`, 'notebook'));

    return items;
  }
}

// ── Sidebar: Fleet Logs Tree ────────────────────────────────────────────────

class LogItem extends vscode.TreeItem {
  constructor(entry: Record<string, unknown>) {
    const type = entry.event_type as string;
    const icon = type === 'success' ? '✅' : type === 'failure' ? '❌' : '🔄';
    const task = (entry.task as string) ?? 'unknown';
    super(`${icon} ${task}`, vscode.TreeItemCollapsibleState.None);
    this.description = entry.timestamp
      ? new Date(entry.timestamp as string).toLocaleTimeString()
      : '';
    this.tooltip = JSON.stringify(entry, null, 2);
  }
}

class LogsProvider implements vscode.TreeDataProvider<LogItem> {
  private _onDidChange = new vscode.EventEmitter<LogItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  refresh() { this._onDidChange.fire(undefined); }

  getTreeItem(el: LogItem) { return el; }

  getChildren(): LogItem[] {
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const logFile = path.join(FLEET_LOG_DIR, `fleet_${today}.jsonl`);
    try {
      const content = fs.readFileSync(logFile, 'utf-8');
      const lines = content.trim().split('\n').filter(Boolean);
      return lines.reverse().slice(0, 50).map((line) => {
        try { return new LogItem(JSON.parse(line)); } catch { return new LogItem({ task: line }); }
      });
    } catch {
      return [new LogItem({ task: 'No logs today', event_type: 'info' })];
    }
  }
}

// ── Sidebar: Actions Tree ───────────────────────────────────────────────────

class ActionItem extends vscode.TreeItem {
  constructor(label: string, command: string, icon: string) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.iconPath = new vscode.ThemeIcon(icon);
    this.command = { command, title: label };
  }
}

class ActionsProvider implements vscode.TreeDataProvider<ActionItem> {
  private _onDidChange = new vscode.EventEmitter<ActionItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  getTreeItem(el: ActionItem) { return el; }

  getChildren(): ActionItem[] {
    return [
      new ActionItem('🌀 Audit Active File', 'vortex.runAudit', 'shield'),
      new ActionItem('✂️ Audit Selection', 'vortex.runAuditSelection', 'selection'),
      new ActionItem('🔄 Switch Preset', 'vortex.switchPreset', 'symbol-key'),
      new ActionItem('📋 View Logs', 'vortex.viewLogs', 'notebook'),
      new ActionItem('🗑️ Clear Logs', 'vortex.clearLogs', 'trash'),
    ];
  }
}

// ── Extension Activation ────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext) {
  // Sidebar providers
  const statusProvider = new StatusProvider();
  const logsProvider = new LogsProvider();
  const actionsProvider = new ActionsProvider();

  vscode.window.registerTreeDataProvider('vortex-status', statusProvider);
  vscode.window.registerTreeDataProvider('vortex-logs', logsProvider);
  vscode.window.registerTreeDataProvider('vortex-actions', actionsProvider);

  statusProvider.refresh();

  // ── Commands ────────────────────────────────────────────────────────────

  context.subscriptions.push(
    vscode.commands.registerCommand('vortex.runAudit', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showWarningMessage('No active editor');
        return;
      }
      const code = editor.document.getText();
      const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: '🌀 VORTEX Auditing...' },
        async () => {
          const result = await runVortexAudit(code, wsRoot);
          statusProvider.setLastResult(result);

          const channel = vscode.window.createOutputChannel('VORTEX Critic');
          channel.clear();
          channel.appendLine(`=== VORTEX Audit Result ===`);
          channel.appendLine(`Verdict: ${result.verdict}`);
          channel.appendLine(`Preset: PCC #${result.preset}`);
          channel.appendLine(`Time: ${(result.elapsed / 1000).toFixed(1)}s`);
          channel.appendLine(`\n${result.text}`);
          channel.show();

          if (result.verdict === 'VERIFIED') {
            vscode.window.showInformationMessage(`✅ VORTEX: VERIFIED (${(result.elapsed / 1000).toFixed(1)}s)`);
          } else if (result.verdict === 'UNVERIFIED') {
            vscode.window.showWarningMessage(`❌ VORTEX: UNVERIFIED — evidence missing`);
          } else {
            vscode.window.showErrorMessage(`⚠️ VORTEX: ${result.text}`);
          }
        }
      );
    }),

    vscode.commands.registerCommand('vortex.runAuditSelection', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.selection.isEmpty) {
        vscode.window.showWarningMessage('No selection');
        return;
      }
      const code = editor.document.getText(editor.selection);
      const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: '🌀 VORTEX Auditing selection...' },
        async () => {
          const result = await runVortexAudit(code, wsRoot);
          statusProvider.setLastResult(result);

          const channel = vscode.window.createOutputChannel('VORTEX Critic');
          channel.clear();
          channel.appendLine(`=== VORTEX Selection Audit ===`);
          channel.appendLine(`Verdict: ${result.verdict}`);
          channel.appendLine(`\n${result.text}`);
          channel.show();
        }
      );
    }),

    vscode.commands.registerCommand('vortex.viewLogs', () => {
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      const logFile = path.join(FLEET_LOG_DIR, `fleet_${today}.jsonl`);
      if (fs.existsSync(logFile)) {
        vscode.workspace.openTextDocument(logFile).then(doc => vscode.window.showTextDocument(doc));
      } else {
        vscode.window.showInformationMessage('No fleet logs today');
      }
    }),

    vscode.commands.registerCommand('vortex.clearLogs', async () => {
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      const logFile = path.join(FLEET_LOG_DIR, `fleet_${today}.jsonl`);
      if (fs.existsSync(logFile)) {
        const confirm = await vscode.window.showWarningMessage(
          'Clear today\'s fleet logs?', { modal: true }, 'Clear'
        );
        if (confirm === 'Clear') {
          fs.unlinkSync(logFile);
          logsProvider.refresh();
          vscode.window.showInformationMessage('Fleet logs cleared');
        }
      }
    }),

    vscode.commands.registerCommand('vortex.refreshSidebar', () => {
      statusProvider.refresh();
      logsProvider.refresh();
    }),

    vscode.commands.registerCommand('vortex.switchPreset', async () => {
      const presets = [
        { label: '#渦 (VORTEX)', description: 'Completion Illusion検知専用', value: '渦' },
        { label: '#監 (Auditor)', description: '証拠ベース判定', value: '監' },
        { label: '#刃 (Blade)', description: '厳格な実装レビュー', value: '刃' },
        { label: '#探 (Explorer)', description: '仮定を疑い弱点を探す', value: '探' },
        { label: '#極 (Extreme)', description: '簡潔・タスク前進のみ', value: '極' },
        { label: '#均 (Balance)', description: '長所短所のバランス', value: '均' },
      ];
      const pick = await vscode.window.showQuickPick(presets, {
        placeHolder: 'Select PCC Preset',
      });
      if (pick) {
        await vscode.workspace.getConfiguration('vortex').update('preset', pick.value, true);
        statusProvider.refresh();
        vscode.window.showInformationMessage(`PCC Preset: ${pick.label}`);
      }
    }),
  );

  // Status bar
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.text = '$(shield) VORTEX';
  statusBar.tooltip = 'Click to run VORTEX audit';
  statusBar.command = 'vortex.runAudit';
  statusBar.show();
  context.subscriptions.push(statusBar);
}

export function deactivate() {}
