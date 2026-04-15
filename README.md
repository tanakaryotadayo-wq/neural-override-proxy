# Neural Override Proxy

ToS準拠の透過的 Gemini API プロンプトインターセプター。
`systemInstruction` に日本語ロケール制約を安全にインジェクトする。

## 機能

- Gemini API (`generativelanguage.googleapis.com`) への POST リクエストを中継
- `systemInstruction.parts` に日本語制約を自動追記
- SSE ストリーミングレスポンス対応
- SSRF 対策（パスホワイトリスト）
- 標準ライブラリのみ（外部依存ゼロ）

## 使い方

```bash
python3 prompt_hook.py --port 18008
```

## セキュリティ

- パスは `/v1/`, `/v1beta/`, `/v1alpha/` のみ許可
- Content-Type が `application/json` でないリクエストは拒否
- 認証情報はログに出力しない
- upstream URL のスキーム検証

## 監査履歴

- v1: Gemini 3.1 Pro 作成 → Dual Umpire Audit **FAIL**
- v2: Claude Opus 4.6 が全問題を修正 → 本バージョン

## Docker Deployment (Issue #8)

To run the full stack via Docker, including `neural-override-proxy` and `mitmweb`:

```bash
# 1. Generate local CA certificates for mitmproxy
./generate_ca.sh

# 2. Start the services
docker-compose up -d
```

- **mitmweb UI**: http://localhost:18081
- **proxy endpoint**: http://localhost:18080 (configure Antigravity IDE HTTP_PROXY to this)

## Issue #7: Protobuf Dump Analyzer

`analyze_protobuf.py` を用いて、mitmproxyで出力した `.bin` ダンプファイルを直接パース・解析できます。

```bash
# 標準出力
./analyze_protobuf.py captures/req_XXXX.bin

# JSON 出力
./analyze_protobuf.py --json captures/req_XXXX.bin
```

## Gemini Code Assist Local A2A Bridge

Gemini Code Assist の既存 UI をそのまま使いながら、A2A backend だけをローカル lane に差し替える bridge を追加した。

```bash
venv/bin/python titan-bridge/gemini_a2a_bridge.py --host 127.0.0.1 --port 8765
```

デフォルト配線:

| Lane | Port | Default model |
| --- | --- | --- |
| conversation | 8103 | `Gemma-4-26B-A4B-Heretic-MLX-8bit` |
| agent | 8102 | `Qwen3-Coder-Next-Abliterated-8bit` |
| utility | 8101 | `Qwen3.5-9B-abliterated-MLX-4bit` |

VS Code 側は `geminicodeassist.a2a.address` を bridge に向ける:

```json
"geminicodeassist.a2a.address": "http://127.0.0.1:8765"
```

補足:

- `/.well-known/agent-card.json` と `/v1/*` の A2A HTTP+JSON surface を提供する
- `JSONRPC` fallback も同じ endpoint で受ける
- Gemini UI 向け custom command として `acp_deepthink` / `acp_deepsearch` を追加し、`gemini` / `claude` / `copilot` CLI を PCC 注入つきで呼べる
- Newgate 要約も bridge に埋め込み、`newgate_status` / `newgate_compare` / `newgate_roadmap` / `newgate_memory_pipeline` / `newgate_deepthink` / `newgate_deepsearch` を叩ける
- Newgate の埋め込みモデル前提は `qwen3-embedding-8b` (4096d)
- 画像入力は現状 fail-fast。信頼できる VL backend をまだ配線していないため、text-first として扱う
