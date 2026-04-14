import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { getDashboardHtml, getJulesHtml } from './dashboard';

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

// ── Sidebar: Webview Provider ───────────────────────────────────────────────

class VortexSidebarProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'vortex-sidebar-webview';
  private _view?: vscode.WebviewView;

  constructor(private readonly _extensionUri: vscode.Uri) {}

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };

    const updateWebview = () => {
      const status = {
        preset: vscode.workspace.getConfiguration('vortex').get<string>('preset') ?? '渦',
        lastVerdict: lastAuditResult?.verdict || null
      };
      webviewView.webview.html = getDashboardHtml(this._extensionUri, FLEET_LOG_DIR, () => status);
    };

    updateWebview();

    webviewView.webview.onDidReceiveMessage((msg) => {
      if (msg.command === 'refresh') {
        updateWebview();
      } else if (msg.command === 'runAudit') {
        vscode.commands.executeCommand('vortex.runAudit');
      }
    });
  }

  public refresh() {
    if (this._view) {
      this._view.webview.postMessage({ command: 'refresh' });
      // Or fully reload HTML:
      const status = {
        preset: vscode.workspace.getConfiguration('vortex').get<string>('preset') ?? '渦',
        lastVerdict: lastAuditResult?.verdict || null
      };
      this._view.webview.html = getDashboardHtml(this._extensionUri, FLEET_LOG_DIR, () => status);
    }
  }
}

let lastAuditResult: AuditResult | null = null;

// ── Extension Activation ────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext) {
  // Sidebar provider
  const sidebarProvider = new VortexSidebarProvider(context.extensionUri);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(VortexSidebarProvider.viewType, sidebarProvider)
  );

  // ── Commands ────────────────────────────────────────────────────────────

  let julesPanel: vscode.WebviewPanel | undefined;

  context.subscriptions.push(
    vscode.commands.registerCommand('vortex.openJulesDashboard', () => {
      if (julesPanel) {
        julesPanel.reveal(vscode.ViewColumn.One);
      } else {
        julesPanel = vscode.window.createWebviewPanel(
          'julesDashboard',
          '🤖 Jules Operations',
          vscode.ViewColumn.One,
          { enableScripts: true }
        );

        const updateJulesView = () => {
          if (!julesPanel) return;
          julesPanel.webview.html = getJulesHtml("Loading Jules Sessions...", true);

          cp.exec('/opt/homebrew/bin/jules remote list --session', (err, stdout, stderr) => {
            if (!julesPanel) return;
            if (err) {
              julesPanel.webview.html = getJulesHtml(`Error: ${stderr || err.message}`, false);
            } else {
              julesPanel.webview.html = getJulesHtml(stdout, false);
            }
          });
        };

        updateJulesView();

        julesPanel.webview.onDidReceiveMessage((msg) => {
          if (msg.command === 'refresh') {
            updateJulesView();
          }
        }, undefined, context.subscriptions);

        julesPanel.onDidDispose(() => {
          julesPanel = undefined;
        }, null, context.subscriptions);
      }
    }),

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
          lastAuditResult = result;
          sidebarProvider.refresh();

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
          // The sidebar refreshes automatically via sidebarProvider.refresh() above
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
          lastAuditResult = result;
          sidebarProvider.refresh();

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
          sidebarProvider.refresh();
          vscode.window.showInformationMessage('Fleet logs cleared');
        }
      }
    }),

    vscode.commands.registerCommand('vortex.refreshSidebar', () => {
      sidebarProvider.refresh();
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
        sidebarProvider.refresh();
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
