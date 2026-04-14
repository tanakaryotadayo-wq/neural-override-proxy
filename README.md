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
