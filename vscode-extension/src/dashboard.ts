import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

export function getDashboardHtml(extensionUri: vscode.Uri, logDir: string, getStatus: () => any): string {
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const logFile = path.join(logDir, `fleet_${today}.jsonl`);
    
    let logs: any[] = [];
    let successCount = 0;
    let failureCount = 0;
    let recoveryCount = 0;

    try {
        if (fs.existsSync(logFile)) {
            const content = fs.readFileSync(logFile, 'utf-8');
            const lines = content.trim().split('\n').filter(Boolean);
            logs = lines.map(line => JSON.parse(line)).reverse().slice(0, 20); // Last 20
            
            lines.forEach(line => {
                try {
                    const parsed = JSON.parse(line);
                    if (parsed.event_type === 'success') successCount++;
                    if (parsed.event_type === 'failure') failureCount++;
                    if (parsed.event_type === 'recovery') recoveryCount++;
                } catch(e) {}
            });
        }
    } catch {
        // Ignore parsing errors
    }

    const total = successCount + failureCount + recoveryCount;
    const successRate = total > 0 ? Math.round(((successCount + recoveryCount) / total) * 100) : 0;
    const status = getStatus();

    // Premium UI Design
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VORTEX Overview</title>
    <style>
        :root {
            --bg: #0f111a;
            --surface: #1e2130;
            --surface-hover: #2a2d3e;
            --primary: #00d2ff;
            --secondary: #3a7bd5;
            --success: #2ecc71;
            --danger: #e74c3c;
            --warning: #f1c40f;
            --text: #e2e8f0;
            --text-muted: #94a3b8;
            --glass: rgba(30, 33, 48, 0.7);
            --glass-border: rgba(255, 255, 255, 0.1);
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: radial-gradient(circle at top left, #12172b 0%, var(--bg) 100%);
            color: var(--text);
            margin: 0;
            padding: 15px;
            animation: fadeIn 0.6s ease-out;
            min-height: 100vh;
            font-size: 13px;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .header {
            display: flex;
            flex-direction: column;
            gap: 15px;
            margin-bottom: 25px;
            border-bottom: 1px solid var(--glass-border);
            padding-bottom: 15px;
        }

        .header-title {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: 5px;
        }

        .logo {
            font-size: 1.8em;
            background: -webkit-linear-gradient(45deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 800;
            letter-spacing: 1px;
            margin-bottom: 2px;
        }

        .grid {
            display: flex;
            flex-direction: column;
            gap: 15px;
            margin-bottom: 25px;
        }

        .card {
            background: var(--glass);
            backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 18px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }

        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 40px 0 rgba(0, 210, 255, 0.15);
        }

        .card h3 {
            margin: 0 0 12px 0;
            color: var(--text-muted);
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .stat-value {
            font-size: 2.2em;
            font-weight: bold;
            display: flex;
            align-items: baseline;
            gap: 8px;
        }

        .stat-subtitle {
            font-size: 0.35em;
            color: var(--text-muted);
            font-weight: normal;
        }

        .color-success { color: var(--success); }
        .color-danger { color: var(--danger); }
        .color-warning { color: var(--warning); }
        .color-primary { color: var(--primary); }

        .progress-bar {
            width: 100%;
            height: 8px;
            background: #2a2d3e;
            border-radius: 4px;
            margin-top: 15px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--secondary), var(--primary));
            width: ${successRate}%;
            border-radius: 4px;
            box-shadow: 0 0 10px var(--primary);
        }

        /* Logs Table */
        .logs-container {
            background: var(--glass);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 15px;
            overflow-x: auto;
        }

        .log-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .log-item {
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 8px;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            transition: background 0.2s;
        }

        .log-item:hover {
            background: rgba(255, 255, 255, 0.02);
            border-color: rgba(255, 255, 255, 0.1);
        }

        .log-header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .log-task {
            font-weight: 500;
            font-size: 0.9em;
            color: var(--text);
            line-height: 1.3;
        }

        .log-result {
            font-size: 0.8em;
            color: var(--text-muted);
            background: rgba(0, 0, 0, 0.15);
            padding: 8px;
            border-radius: 4px;
            word-break: break-word;
        }

        .badge {
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.75em;
            font-weight: bold;
            text-transform: uppercase;
        }

        .badge-success { background: rgba(46, 204, 113, 0.2); border: 1px solid var(--success); color: var(--success); }
        .badge-failure { background: rgba(231, 76, 60, 0.2); border: 1px solid var(--danger); color: var(--danger); }
        .badge-recovery { background: rgba(241, 196, 15, 0.2); border: 1px solid var(--warning); color: var(--warning); }

        .actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            width: 100%;
            margin-top: 5px;
        }

        .btn {
            background: transparent;
            border: 1px solid var(--primary);
            color: var(--primary);
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.2s;
        }

        .btn:hover {
            background: var(--primary);
            color: var(--bg);
            box-shadow: 0 0 15px var(--primary);
        }

        .btn-primary {
            background: var(--primary);
            color: var(--bg);
        }

        .btn-primary:hover {
            background: #fff;
            border-color: #fff;
            box-shadow: 0 0 20px #fff;
        }

        .critic-panel {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--success);
            box-shadow: 0 0 8px var(--success);
            margin-right: 8px;
        }
    </style>
</head>
<body>

    <div class="header">
        <div class="header-title">
            <div class="logo">🌀 VORTEX</div>
            <div style="display: flex; align-items: center;">
                <span class="status-indicator"></span> 
                <span style="color: var(--text-muted); font-size: 0.85em; font-weight: 500; letter-spacing: 1px;">SYSTEM ONLINE</span>
            </div>
        </div>
        <div class="actions">
            <button class="btn" onclick="postMessage('refresh')">🔄 Refresh</button>
            <button class="btn btn-primary" onclick="postMessage('runAudit')">⚡ Run Audit</button>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h3>Fleet Intelligence</h3>
            <div class="stat-value color-primary">
                ${successRate}% <span class="stat-subtitle">Success Rate</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill"></div>
            </div>
            <div style="margin-top: 15px; font-size: 0.75em; display: flex; justify-content: space-between; color: var(--text-muted); font-weight: 600;">
                <span style="color: var(--success)">${successCount} OK</span>
                <span style="color: var(--warning)">${recoveryCount} FIX</span>
                <span style="color: var(--danger)">${failureCount} ERR</span>
            </div>
        </div>

        <div class="card">
            <h3>Critic Status</h3>
            <div class="critic-panel">
                <div>
                    <span style="color: var(--text-muted); font-size: 0.8em;">Preset:</span> 
                    <span class="badge badge-success" style="float:right;">#${status.preset}</span>
                </div>
                <div style="margin-top: 10px;">
                    <span style="color: var(--text-muted); font-size: 0.8em;">Engine:</span> 
                    <span style="float:right;">DeepSeek VORTEX</span>
                </div>
                <div style="margin-top: 10px;">
                    <span style="color: var(--text-muted); font-size: 0.8em;">Last Verdict:</span> 
                    <span style="float:right;" class="${status.lastVerdict === 'VERIFIED' ? 'color-success' : status.lastVerdict === 'UNVERIFIED' ? 'color-danger' : 'color-warning'}">
                        ${status.lastVerdict || 'PENDING'}
                    </span>
                </div>
            </div>
        </div>
    </div>

    <div class="logs-container">
        <h3 style="margin: 0 0 20px 0; color: var(--text-muted); letter-spacing: 1px; font-size: 0.9em;">FLEET OPERATIONAL LOGS</h3>
        ${logs.length > 0 ? `
        <div class="log-list">
            ${logs.map(log => `
            <div class="log-item">
                <div class="log-header-row">
                    <span class="badge badge-${log.event_type}">${log.event_type}</span>
                    <span style="color: var(--text-muted); font-size: 0.8em;">${new Date(log.timestamp).toLocaleTimeString()}</span>
                </div>
                <div class="log-task">${log.task || '-'}</div>
                <div class="log-result">
                    ${log.result || log.cause || '-'}
                    ${(log.tags || []).length > 0 ? `<div style="margin-top: 5px; color: var(--primary); opacity: 0.8;">${(log.tags || []).map((t: string) => `#${t}`).join(' ')}</div>` : ''}
                </div>
            </div>
            `).join('')}
        </div>
        ` : `
        <div style="text-align: center; padding: 40px; color: var(--text-muted);">
            No fleet logs recorded today.
        </div>
        `}
    </div>

    <script>
        const vscode = acquireVsCodeApi();
        function postMessage(command) {
            vscode.postMessage({ command });
        }
    </script>
</body>
</html>`;
}

export function getJulesHtml(content: string, isLoading: boolean): string {
    const lines = content.split('\n');
    let formattedContent = content;
    
    if (!isLoading && content.includes('Description') && content.includes('Status')) {
        formattedContent = lines.map(line => {
            if (line.includes('ID') && line.includes('Description')) {
                return `<div style="color: var(--text-muted); font-size: 0.8em; text-transform: uppercase; letter-spacing: 1px; padding-bottom: 10px; border-bottom: 1px solid var(--glass-border); margin-bottom: 10px;">${line}</div>`;
            }
            if (!line.trim()) return '';
            
            let styledLine = line
                .replace(/\bAwa\b/, '<span class="badge badge-warning">Awa</span>')
                .replace(/\bCom\b/, '<span class="badge badge-success">Com</span>')
                .replace(/\bIn \b/, '<span class="badge badge-primary">In </span>');
            return `<div style="margin-bottom: 6px; font-family: monospace; white-space: pre; border-bottom: 1px solid rgba(255,255,255,0.02); padding-bottom: 6px;">${styledLine}</div>`;
        }).join('');
    }

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jules Operations</title>
    <style>
        :root {
            --bg: #0f111a;
            --primary: #00d2ff;
            --secondary: #3a7bd5;
            --success: #2ecc71;
            --warning: #f1c40f;
            --text: #e2e8f0;
            --text-muted: #94a3b8;
            --glass: rgba(30, 33, 48, 0.7);
            --glass-border: rgba(255, 255, 255, 0.1);
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 40px;
            animation: fadeIn 0.4s ease-out;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            border-bottom: 1px solid var(--glass-border);
            padding-bottom: 20px;
        }

        .title {
            font-size: 2em;
            background: -webkit-linear-gradient(45deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: bold;
        }

        .container {
            background: var(--glass);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            overflow-x: auto;
        }

        .badge {
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: bold;
        }

        .badge-success { color: var(--success); border: 1px solid var(--success); background: rgba(46, 204, 113, 0.1); }
        .badge-warning { color: var(--warning); border: 1px solid var(--warning); background: rgba(241, 196, 15, 0.1); }
        .badge-primary { color: var(--primary); border: 1px solid var(--primary); background: rgba(0, 210, 255, 0.1); }

        .btn {
            background: transparent;
            border: 1px solid var(--primary);
            color: var(--primary);
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.2s;
        }

        .btn:hover {
            background: var(--primary);
            color: var(--bg);
            box-shadow: 0 0 15px var(--primary);
        }

        pre {
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">🤖 Jules Operations</div>
        <button class="btn" onclick="postMessage('refresh')">🔄 Refresh</button>
    </div>
    
    <div class="container">
        ${isLoading ? 
            `<div style="color: var(--primary); text-align: center; padding: 40px; font-size: 1.2em;">
                <span style="display:inline-block; animation: pulse 1.5s infinite;">Scanning active sessions...</span>
             </div>
             <style>@keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }</style>
            ` 
            : `<pre>${formattedContent}</pre>`
        }
    </div>

    <script>
        const vscode = acquireVsCodeApi();
        function postMessage(command) {
            vscode.postMessage({ command });
        }
    </script>
</body>
</html>`;
}
