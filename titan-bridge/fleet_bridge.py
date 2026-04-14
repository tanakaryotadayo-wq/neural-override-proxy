#!/usr/bin/env python3
"""
fleet-bridge — Copilot CLI Fleet用MCP stdio bridge (Mac Studio ローカル版)

titan_mcp_bridge.py からクローン。
Mac Studio 上で直接動作するため、自身の fusion-gate HTTP API (localhost:9000) に接続。

用途:
  - GPT-5 mini Fleet のサブエージェントがこの MCP を使う
  - ログ記録、KI更新、パターン抽出を無料AIで回す
  - 監査は DeepSeek VORTEX Critic (別パイプライン) が担当

起動:
  copilot --model gpt-5-mini --additional-mcp-config '{"fleet-bridge":{"command":"python3","args":["/Users/ryyota/neural-override-proxy/titan-bridge/fleet_bridge.py"]}}'
"""
import json
import sys
import urllib.request
import urllib.error

# Mac Studio のローカル fusion-gate API
FUSION_GATE_URL = "http://localhost:9000"

# Fleet向けツール定義（GPT-5 mini が使うもののみ）
TOOLS = [
    # === ログ記録系 ===
    {
        "name": "fleet_log",
        "description": "セッションログを構造化記録（成功/失敗/失敗→成功パターン）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "enum": ["success", "failure", "recovery"], "description": "成功/失敗/リカバリ"},
                "task": {"type": "string", "description": "何をしようとしたか"},
                "result": {"type": "string", "description": "結果の詳細"},
                "cause": {"type": "string", "description": "失敗原因（failure/recovery時）"},
                "fix": {"type": "string", "description": "修正方法（recovery時）"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "タグ"},
            },
            "required": ["event_type", "task", "result"],
        },
    },

    # === KI系 ===
    {
        "name": "eck_read",
        "description": "ECK/KI履歴読み込み",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "eck_write",
        "description": "ECKに追記（KI更新）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean", "default": True},
            },
            "required": ["path", "content"],
        },
    },

    # === 成功事例系 ===
    {
        "name": "success_register",
        "description": "成功事例を登録する",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "カテゴリ (pcc/security/architecture/tool/config/debug/pattern)"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "solution": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["category", "title", "description", "solution"],
        },
    },
    {
        "name": "success_search",
        "description": "成功事例を検索する。キーワード、カテゴリ、タグで検索可能",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "category": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
    },

    # === メモリ系 ===
    {
        "name": "memory_search",
        "description": "過去会話のセマンティック検索",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_feedback",
        "description": "検索結果の採用/不採用フィードバック",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chunk_id": {"type": "string"},
                "source_type": {"type": "string", "enum": ["ki", "chat"]},
                "adopted": {"type": "boolean", "default": True},
                "feedback": {"type": "string"},
            },
            "required": ["chunk_id", "source_type"],
        },
    },

    # === 統計系 ===
    {
        "name": "get_stats",
        "description": "FusionGateシステム統計",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

# ログファイルパス
import os
from pathlib import Path
from datetime import datetime

LOG_DIR = Path(os.environ.get("FLEET_LOG_DIR", os.path.expanduser("~/.gemini/antigravity/fleet-logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)


def handle_fleet_log(arguments: dict) -> dict:
    """ローカルにログを構造化記録"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": arguments.get("event_type", "unknown"),
        "task": arguments.get("task", ""),
        "result": arguments.get("result", ""),
        "cause": arguments.get("cause"),
        "fix": arguments.get("fix"),
        "tags": arguments.get("tags", []),
    }
    # Remove None values
    entry = {k: v for k, v in entry.items() if v is not None}

    log_file = LOG_DIR / f"fleet_{datetime.now().strftime('%Y%m%d')}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"status": "logged", "file": str(log_file), "entry": entry}


def call_fusion_gate(tool_name: str, arguments: dict) -> dict:
    """fusion-gate の HTTP API にリクエストを送る"""
    url = f"{FUSION_GATE_URL}/api/tool/{tool_name}"
    data = json.dumps(arguments).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"error": f"FusionGate unreachable: {e}"}
    except Exception as e:
        return {"error": str(e)}


def handle_request(request: dict) -> "dict | None":
    """JSON-RPC リクエストを処理する"""
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "fleet-bridge", "version": "1.0.0"}
        }}
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]} for t in TOOLS]
        }}
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        # fleet_log はローカル処理
        if name == "fleet_log":
            result = handle_fleet_log(arguments)
        else:
            # fusion-gate API に中継
            result = call_fusion_gate(name, arguments)

        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
        }}
    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main():
    """stdio で JSON-RPC を受け取り、処理する"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            pass


if __name__ == "__main__":
    main()
