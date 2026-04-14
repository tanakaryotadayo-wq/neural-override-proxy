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
            padding: 30px;
            animation: fadeIn 0.6s ease-out;
            min-height: 100vh;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            border-bottom: 1px solid var(--glass-border);
            padding-bottom: 20px;
        }

        .header-title {
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .logo {
            font-size: 2em;
            background: -webkit-linear-gradient(45deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 800;
            letter-spacing: 2px;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }

        .card {
            background: var(--glass);
            backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }

        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 40px 0 rgba(0, 210, 255, 0.15);
        }

        .card h3 {
            margin: 0 0 15px 0;
            color: var(--text-muted);
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .stat-value {
            font-size: 2.5em;
            font-weight: bold;
            display: flex;
            align-items: baseline;
            gap: 10px;
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
            padding: 24px;
            overflow: hidden;
        }

        .logs-table {
            width: 100%;
            border-collapse: collapse;
        }

        .logs-table th, .logs-table td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }

        .logs-table th {
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.8em;
            letter-spacing: 1px;
        }

        .logs-table tr:hover {
            background: rgba(255,255,255,0.02);
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
            display: flex;
            gap: 10px;
            margin-top: 20px;
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
            <div>
                <span class="status-indicator"></span> 
                <span style="color: var(--text-muted); font-size: 0.9em;">SYSTEM ONLINE</span>
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
            <div style="margin-top: 15px; font-size: 0.8em; display: flex; justify-content: space-between; color: var(--text-muted);">
                <span>${successCount} Success</span>
                <span>${recoveryCount} Recoveries</span>
                <span>${failureCount} Failures</span>
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
        <table class="logs-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Status</th>
                    <th>Task</th>
                    <th>Result / Tags</th>
                </tr>
            </thead>
            <tbody>
                ${logs.map(log => `
                <tr>
                    <td style="color: var(--text-muted); font-size: 0.85em;">${new Date(log.timestamp).toLocaleTimeString()}</td>
                    <td><span class="badge badge-${log.event_type}">${log.event_type}</span></td>
                    <td style="font-weight: 500;">${log.task || '-'}</td>
                    <td style="font-size: 0.85em; color: var(--text-muted);">
                        ${log.result || log.cause || '-'} 
                        <br/>
                        ${(log.tags || []).map((t: string) => `<span style="opacity: 0.5; margin-right: 5px;">#${t}</span>`).join('')}
                    </td>
                </tr>
                `).join('')}
            </tbody>
        </table>
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
