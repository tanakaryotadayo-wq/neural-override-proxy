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

interface NewgateStatus {
  connected: boolean;
  bridgeUrl: string;
  version: string;
  embeddingModel: string;
  recallStatus: string;
  storeStatus: string;
  p0Count: number;
  error?: string;
  profile?: any;
}

function getBridgeUrl(): string {
  const configured = vscode.workspace.getConfiguration().get<string>('geminicodeassist.a2a.address') ?? '';
  return configured.trim().replace(/\/$/, '');
}

async function fetchNewgateStatus(): Promise<NewgateStatus> {
  const bridgeUrl = getBridgeUrl();
  if (!bridgeUrl) {
    return {
      connected: false,
      bridgeUrl: '',
      version: '-',
      embeddingModel: '-',
      recallStatus: 'unknown',
      storeStatus: 'unknown',
      p0Count: 0,
      error: 'geminicodeassist.a2a.address が未設定',
    };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);

  try {
    const response = await (globalThis as any).fetch(`${bridgeUrl}/newgate/profile`, {
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const snapshot = await response.json() as any;
    const profile = snapshot?.profile ?? {};
    const priorities = Array.isArray(profile.priorities) ? profile.priorities : [];

    return {
      connected: true,
      bridgeUrl,
      version: String(profile.version ?? '-'),
      embeddingModel: String(profile.embedding?.primaryModel ?? '-'),
      recallStatus: String(profile.memory?.recall?.status ?? 'unknown'),
      storeStatus: String(profile.memory?.store?.status ?? 'unknown'),
      p0Count: priorities.filter((item: any) => item?.priority === 'P0').length,
      profile,
    };
  } catch (error: any) {
    const message = error?.name === 'AbortError' ? 'bridge timeout' : (error?.message ?? 'bridge error');
    return {
      connected: false,
      bridgeUrl,
      version: '-',
      embeddingModel: '-',
      recallStatus: 'unknown',
      storeStatus: 'unknown',
      p0Count: 0,
      error: message,
    };
  } finally {
    clearTimeout(timeout);
  }
}

// ── Resolve Script Paths ────────────────────────────────────────────────────

function resolveCriticScript(context: vscode.ExtensionContext): string {
  const config = vscode.workspace.getConfiguration('vortex');
  const custom = config.get<string>('criticScript');
  if (custom && fs.existsSync(custom)) { return custom; }

  // Bundle package script
  const bundled = path.join(context.extensionPath, 'assets', 'critic', CRITIC_SCRIPT_NAME);
  if (fs.existsSync(bundled)) { return bundled; }
  return '';
}

// ── VORTEX Critic Runner ────────────────────────────────────────────────────

interface AuditResult {
  verdict: 'VERIFIED' | 'UNVERIFIED' | 'ERROR';
  text: string;
  preset: string;
  elapsed: number;
}

async function runVortexAudit(code: string, workspaceRoot: string, context: vscode.ExtensionContext): Promise<AuditResult> {
  const criticScript = resolveCriticScript(context);
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

    const updateWebview = async () => {
      const status = {
        preset: vscode.workspace.getConfiguration('vortex').get<string>('preset') ?? '渦',
        lastVerdict: lastAuditResult?.verdict || null,
        newgate: await fetchNewgateStatus(),
      };
      webviewView.webview.html = getDashboardHtml(this._extensionUri, FLEET_LOG_DIR, () => status);
    };

    void updateWebview();

    webviewView.webview.onDidReceiveMessage((msg) => {
      if (msg.command === 'refresh') {
        void updateWebview();
      } else if (msg.command === 'runAudit') {
        vscode.commands.executeCommand('vortex.runAudit');
      } else if (msg.command === 'openNewgate') {
        vscode.commands.executeCommand('vortex.openNewgateSnapshot');
      }
    });
  }

  public async refresh() {
    if (this._view) {
      this._view.webview.postMessage({ command: 'refresh' });
      const status = {
        preset: vscode.workspace.getConfiguration('vortex').get<string>('preset') ?? '渦',
        lastVerdict: lastAuditResult?.verdict || null,
        newgate: await fetchNewgateStatus(),
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
    vscode.commands.registerCommand('vortex.openAsyncTaskDashboard', async () => {
      if (julesPanel) {
        julesPanel.reveal(vscode.ViewColumn.One);
        return;
      }
      
      let token = '';
      try {
        const session = await vscode.authentication.getSession('github', ['repo'], { createIfNone: true });
        token = session.accessToken;
      } catch (err) {
        vscode.window.showErrorMessage('GitHub Authentication is required to access Jules operations.');
        return;
      }

      julesPanel = vscode.window.createWebviewPanel(
        'asyncTaskDashboard',
        '✨ Async Tasks (GitHub Issues)',
        vscode.ViewColumn.One,
        { enableScripts: true, retainContextWhenHidden: true }
      );

      const updateJulesView = async () => {
        if (!julesPanel) return;
        julesPanel.webview.html = getJulesHtml("Loading Jules Sessions from GitHub...", true);
        try {
          // Fetch open issues mentioning jules involving the current user
          const res = await (globalThis as any).fetch(`https://api.github.com/search/issues?q=involves:@me+"jules"+is:open+is:issue`, {
            headers: { 'Authorization': `Bearer ${token}`, 'Accept': 'application/vnd.github.v3+json' }
          });
          const data = await res.json() as any;
          if (data.items) {
             // Pass the raw JSON array to the dashboard parser instead of a CLI string
             julesPanel.webview.html = getJulesHtml(JSON.stringify(data.items), false);
          } else {
             julesPanel.webview.html = getJulesHtml(`Error: ${JSON.stringify(data)}`, false);
          }
        } catch (err: any) {
          julesPanel.webview.html = getJulesHtml(`Error: ${err.message}`, false);
        }
      };

      updateJulesView();

      julesPanel.webview.onDidReceiveMessage(async (msg) => {
        if (msg.command === 'refresh') {
          updateJulesView();
        } else if (msg.command === 'fetchComments') {
          // Fetch issue comments
          try {
            const res = await (globalThis as any).fetch(msg.commentsUrl, {
              headers: { 'Authorization': `Bearer ${token}`, 'Accept': 'application/vnd.github.v3+json' }
            });
            const comments = await res.json();
            julesPanel?.webview.postMessage({ command: 'renderComments', comments, issueId: msg.issueId });
          } catch (err: any) {
            vscode.window.showErrorMessage('Failed to fetch comments: ' + err.message);
          }
        } else if (msg.command === 'postReply') {
          try {
            const res = await (globalThis as any).fetch(msg.commentsUrl, {
              method: 'POST',
              headers: { 'Authorization': `Bearer ${token}`, 'Accept': 'application/vnd.github.v3+json', 'Content-Type': 'application/json' },
              body: JSON.stringify({ body: msg.body })
            });
            if (res.ok) {
              vscode.window.showInformationMessage('Reply sent to Jules successfully!');
              // Re-fetch comments to show the new one
              julesPanel?.webview.postMessage({ command: 'refreshComments', commentsUrl: msg.commentsUrl, issueId: msg.issueId });
            } else {
              vscode.window.showErrorMessage(`Failed to send reply: ${res.statusText}`);
            }
          } catch (err: any) {
            vscode.window.showErrorMessage('Failed to send reply: ' + err.message);
          }
        }
      }, undefined, context.subscriptions);

      julesPanel.onDidDispose(() => {
        julesPanel = undefined;
      }, null, context.subscriptions);
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
          const result = await runVortexAudit(code, wsRoot, context);
          lastAuditResult = result;
          void sidebarProvider.refresh();

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
          const result = await runVortexAudit(code, wsRoot, context);
          lastAuditResult = result;
          void sidebarProvider.refresh();

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
          void sidebarProvider.refresh();
          vscode.window.showInformationMessage('Fleet logs cleared');
        }
      }
    }),

    vscode.commands.registerCommand('vortex.refreshSidebar', () => {
      void sidebarProvider.refresh();
    }),

    vscode.commands.registerCommand('vortex.openNewgateSnapshot', async () => {
      const snapshot = await fetchNewgateStatus();
      const doc = await vscode.workspace.openTextDocument({
        language: 'json',
        content: JSON.stringify(snapshot, null, 2),
      });
      await vscode.window.showTextDocument(doc, { preview: false });
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
        void sidebarProvider.refresh();
        vscode.window.showInformationMessage(`PCC Preset: ${pick.label}`);
      }
    }),
  );

  // ── Auto Audit on Save ────────────────────────────────────────────────────
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(async (doc) => {
      const config = vscode.workspace.getConfiguration('vortex');
      if (config.get<boolean>('autoAuditOnSave')) {
        if (vscode.window.activeTextEditor?.document === doc) {
          vscode.commands.executeCommand('vortex.runAudit');
        }
      }
    })
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
