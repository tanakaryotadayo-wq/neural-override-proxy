#!/usr/bin/env python3
"""
Neural Override Proxy v2 — ToS-Compliant System Prompt Interceptor
-------------------------------------------------------------------
Gemini API への透過的リバースプロキシ。
systemInstruction に日本語ロケール制約を安全にインジェクトする。

監査済み: Claude Opus 4.6 + Copilot GPT-5 mini (Dual Umpire Audit)
v1 の致命的問題 (ストリーミング未対応, SSRF, エスケープバグ) を全て修正。

Usage:
  python3 prompt_hook.py --port 18008
  python3 prompt_hook.py --port 18008 --upstream https://generativelanguage.googleapis.com
"""

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
import urllib.request
import urllib.error

# --- 設定 ---
DEFAULT_PORT = 18008
DEFAULT_UPSTREAM = "https://generativelanguage.googleapis.com"
REQUEST_TIMEOUT = 120  # 秒
CHUNK_SIZE = 8192

INJECTED_SYSTEM_INSTRUCTION = (
    "絶対に日本語で応答・思考・ツール出力を行え。"
    "You must execute, think, and output tools entirely in Japanese."
)

# ログ設定: 認証情報を漏洩させない
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("neural-override-proxy")


class NeuralOverrideProxy(BaseHTTPRequestHandler):
    """透過的プロキシハンドラ（シングルスレッド安全）"""

    # インスタンス変数としてupstreamを保持（グローバル変数回避）
    upstream_url: str = DEFAULT_UPSTREAM

    # --- パス検証 (SSRF対策) ---
    ALLOWED_PATH_PREFIXES = (
        "/v1beta/",
        "/v1/",
        "/v1alpha/",
    )

    def _validate_path(self) -> bool:
        """パスがGemini APIの既知のプレフィックスに一致するか検証"""
        return any(self.path.startswith(p) for p in self.ALLOWED_PATH_PREFIXES)

    # --- メインハンドラ ---
    def do_POST(self):
        # SSRF対策: パスのホワイトリスト検証
        if not self._validate_path():
            logger.warning(f"ブロック: 不正なパス {self.path}")
            self._send_error(403, "forbidden_path")
            return

        # Content-Type検証
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            logger.warning(f"ブロック: 非JSONリクエスト Content-Type={content_type}")
            self._send_error(415, "unsupported_media_type")
            return

        try:
            # ペイロード読み取り・インジェクション
            content_length = int(self.headers.get("Content-Length", 0))
            raw_data = self.rfile.read(content_length)
            payload = json.loads(raw_data.decode("utf-8"))

            self._inject_locale_constraint(payload)

            modified_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            # ヘッダー構築（認証情報はログに出さない）
            req_headers = {}
            for k, v in self.headers.items():
                if k.lower() not in ("host", "content-length", "connection"):
                    req_headers[k] = v
            req_headers["Content-Length"] = str(len(modified_data))

            target_url = f"{self.upstream_url}{self.path}"

            req = urllib.request.Request(
                target_url,
                data=modified_data,
                headers=req_headers,
                method="POST",
            )

            # タイムアウト付きリクエスト
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                # レスポンスヘッダーを先に送信
                self.send_response(response.status)

                is_streaming = False
                for k, v in response.headers.items():
                    k_lower = k.lower()
                    if k_lower in ("transfer-encoding", "connection"):
                        continue
                    if k_lower == "content-type" and "text/event-stream" in v:
                        is_streaming = True
                    self.send_header(k, v)

                if is_streaming:
                    # ストリーミング: Content-Lengthを削除してチャンク転送
                    self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                if is_streaming:
                    # SSEストリーミング: チャンク単位でリアルタイム転送
                    self._stream_response(response)
                else:
                    # 通常レスポンス: 一括読み取り
                    resp_body = response.read()
                    self.wfile.write(resp_body)

            logger.info(f"✅ 中継完了: {self.path} (streaming={is_streaming})")

        except urllib.error.HTTPError as e:
            logger.warning(f"上流エラー: {e.code} {self.path}")
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(e.read())
        except json.JSONDecodeError as e:
            logger.error(f"JSONパースエラー: {e}")
            self._send_error(400, "invalid_json")
        except TimeoutError:
            logger.error(f"タイムアウト: {self.path}")
            self._send_error(504, "upstream_timeout")
        except Exception as e:
            # スタックトレースは出すが、ヘッダー情報は含めない
            logger.error(f"プロキシエラー: {type(e).__name__}: {e}")
            self._send_error(500, "proxy_error")

    def do_GET(self):
        """Handle GET requests for health check."""
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path in ('/health', '/healthcheck'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"status": "ok", "service": "neural-override-proxy"}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
            
        self.send_response(405)
        self.end_headers()
        self.wfile.write(b'Method Not Allowed')

    def do_OPTIONS(self):
        """CORS preflight"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, x-goog-api-key")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    # --- コアロジック ---
    def _inject_locale_constraint(self, payload: dict) -> None:
        """systemInstruction に日本語制約を安全にインジェクト"""
        # Gemini API構造チェック
        if "contents" not in payload or not isinstance(payload.get("contents"), list):
            return

        if "systemInstruction" not in payload:
            payload["systemInstruction"] = {
                "role": "system",
                "parts": [{"text": INJECTED_SYSTEM_INSTRUCTION}],
            }
        else:
            si = payload["systemInstruction"]
            if isinstance(si, dict) and "parts" in si and isinstance(si["parts"], list):
                si["parts"].append({
                    "text": f"\n\n[COMPLIANCE OVERRIDE]: {INJECTED_SYSTEM_INSTRUCTION}"
                })
            else:
                logger.warning("systemInstruction の構造が不明なためインジェクション失敗")

    def _stream_response(self, response) -> None:
        """SSEレスポンスをチャンク単位でリアルタイム転送"""
        try:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                # HTTP chunked transfer encoding
                self.wfile.write(f"{len(chunk):x}\r\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            # 終端チャンク
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            logger.info("クライアント切断（ストリーミング中断）")

    def _send_error(self, code: int, message: str) -> None:
        """統一エラーレスポンス"""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        body = json.dumps({"error": message}, ensure_ascii=False)
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        """BaseHTTPRequestHandlerのデフォルトログを抑制（独自loggerを使用）"""
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Neural Override Proxy — ToS準拠 Gemini API プロンプトフック"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"プロキシのリッスンポート (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--upstream", type=str, default=DEFAULT_UPSTREAM,
        help=f"上流API URL (default: {DEFAULT_UPSTREAM})"
    )
    args = parser.parse_args()

    # upstream URLの検証
    parsed = urlparse(args.upstream)
    if parsed.scheme not in ("http", "https"):
        logger.error(f"不正なupstream URL: {args.upstream}")
        raise SystemExit(1)

    upstream = args.upstream.rstrip("/")

    # ハンドラにupstream URLを設定（グローバル変数を回避）
    NeuralOverrideProxy.upstream_url = upstream

    server = HTTPServer(("", args.port), NeuralOverrideProxy)
    logger.info(f"🚀 Neural Override Proxy v2 起動")
    logger.info(f"   ポート: {args.port}")
    logger.info(f"   上流:   {upstream}")
    logger.info(f"   制約:   {INJECTED_SYSTEM_INSTRUCTION[:40]}...")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("シャットダウン...")
    server.server_close()


if __name__ == "__main__":
    main()
