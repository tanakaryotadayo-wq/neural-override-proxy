#!/usr/bin/env python3
"""
mitm_gemini_capture.py — mitmproxy addon for capturing Gemini API traffic

Antigravity IDE の Gemini API 通信を傍受し、
システムプロンプト構造を解析・ログ出力する。

Usage:
  mitmdump -s mitm_gemini_capture.py --listen-port 18080

出力:
  - コンソールにリアルタイムログ
  - captures/ ディレクトリに JSON ダンプ
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

# mitmproxy imports
from mitmproxy import http, ctx


# --- 設定 ---
CAPTURE_DIR = Path(__file__).parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

# 傍受対象のドメインパターン
TARGET_DOMAINS = [
    "generativelanguage.googleapis.com",
    "cloudaicompanion",
    "autopush-cloudaicompanion",
    "aiplatform.googleapis.com",
    "us-central1-aiplatform.googleapis.com",
    "firebaseml.googleapis.com",
]

# 注目するヘッダー（認証情報は除外）
SAFE_HEADERS = [
    "content-type",
    "x-goog-api-key",
    "x-goog-api-client",
    "user-agent",
    "grpc-encoding",
    "connect-protocol-version",
    "connect-content-encoding",
]

# --- ユーティリティ ---

def is_target_request(flow: http.HTTPFlow) -> bool:
    """傍受対象かどうか判定"""
    host = flow.request.pretty_host
    return any(domain in host for domain in TARGET_DOMAINS)


def safe_headers(headers) -> dict:
    """認証情報を除外したヘッダーを抽出"""
    result = {}
    for k, v in headers.items():
        k_lower = k.lower()
        if k_lower in SAFE_HEADERS:
            result[k] = v
        elif "auth" not in k_lower and "key" not in k_lower and "token" not in k_lower:
            result[k] = v[:100] + "..." if len(v) > 100 else v
    return result


def try_parse_json(data: bytes) -> dict | list | None:
    """JSON パースを試みる"""
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def extract_system_prompt(payload: dict) -> dict | None:
    """systemInstruction を抽出"""
    if not isinstance(payload, dict):
        return None

    result = {}

    # Gemini REST API 形式
    if "systemInstruction" in payload:
        result["systemInstruction"] = payload["systemInstruction"]

    # system_instruction (snake_case)
    if "system_instruction" in payload:
        result["system_instruction"] = payload["system_instruction"]

    # contents 内の system ロールメッセージ
    if "contents" in payload and isinstance(payload["contents"], list):
        system_msgs = [
            c for c in payload["contents"]
            if isinstance(c, dict) and c.get("role") == "system"
        ]
        if system_msgs:
            result["system_role_messages"] = system_msgs

    # plannerConfig (Antigravity 固有)
    if "plannerConfig" in payload:
        result["plannerConfig"] = payload["plannerConfig"]

    # cascadeConfig
    if "cascadeConfig" in payload:
        result["cascadeConfig"] = payload["cascadeConfig"]

    # ephemeralMessages
    for key in payload:
        if "ephemeral" in key.lower():
            result[key] = payload[key]

    return result if result else None


def detect_content_type(headers) -> str:
    """コンテンツタイプを分類"""
    ct = headers.get("content-type", "")
    if "application/json" in ct:
        return "json"
    elif "application/grpc" in ct:
        return "grpc"
    elif "application/connect+proto" in ct:
        return "connect-proto"
    elif "application/proto" in ct:
        return "proto"
    elif "text/event-stream" in ct:
        return "sse"
    elif "application/x-protobuf" in ct:
        return "protobuf"
    else:
        return ct or "unknown"


# --- mitmproxy Addon ---

class GeminiCapture:
    """Gemini API 通信を傍受・解析する mitmproxy addon"""

    def __init__(self):
        self.capture_count = 0
        ctx.log.info("🔥 GeminiCapture addon loaded")
        ctx.log.info(f"📁 Captures directory: {CAPTURE_DIR}")

    def request(self, flow: http.HTTPFlow) -> None:
        """リクエスト傍受"""
        if not is_target_request(flow):
            return

        self.capture_count += 1
        req = flow.request

        content_type = detect_content_type(req.headers)
        body_json = try_parse_json(req.content) if content_type == "json" else None

        ctx.log.warn(
            f"🎯 [{self.capture_count}] REQUEST → {req.method} {req.pretty_url}\n"
            f"   Content-Type: {content_type} | Size: {len(req.content or b'')} bytes"
        )

        # システムプロンプト検出
        if body_json:
            system_prompt = extract_system_prompt(body_json)
            if system_prompt:
                ctx.log.error(
                    f"🚨 SYSTEM PROMPT DETECTED in request #{self.capture_count}:\n"
                    f"   Keys: {list(system_prompt.keys())}"
                )
                # 詳細をファイルに保存
                self._save_capture(
                    f"req_{self.capture_count:04d}",
                    {
                        "type": "request",
                        "url": req.pretty_url,
                        "method": req.method,
                        "content_type": content_type,
                        "headers": safe_headers(req.headers),
                        "system_prompt": system_prompt,
                        "body_preview": self._truncate_body(body_json),
                    }
                )
        elif content_type in ("grpc", "connect-proto", "proto", "protobuf"):
            # Protobuf バイナリ — raw bytes を保存
            ctx.log.warn(
                f"   ⚡ Protobuf binary detected — saving raw bytes"
            )
            raw_path = CAPTURE_DIR / f"req_{self.capture_count:04d}.bin"
            raw_path.write_bytes(req.content or b"")

            self._save_capture(
                f"req_{self.capture_count:04d}_meta",
                {
                    "type": "request",
                    "url": req.pretty_url,
                    "method": req.method,
                    "content_type": content_type,
                    "headers": safe_headers(req.headers),
                    "body_size": len(req.content or b""),
                    "body_file": str(raw_path),
                    "note": "Protobuf binary — see .bin file",
                }
            )

    def response(self, flow: http.HTTPFlow) -> None:
        """レスポンス傍受"""
        if not is_target_request(flow):
            return

        resp = flow.response
        if resp is None:
            return

        content_type = detect_content_type(resp.headers)
        body_json = try_parse_json(resp.content) if content_type in ("json", "sse") else None

        ctx.log.warn(
            f"📨 [{self.capture_count}] RESPONSE ← {resp.status_code} "
            f"{flow.request.pretty_url}\n"
            f"   Content-Type: {content_type} | Size: {len(resp.content or b'')} bytes"
        )

        # JSON レスポンスの解析
        if body_json:
            # Google のシステムメッセージ注入を検出
            injected = self._detect_response_injection(body_json)
            if injected:
                ctx.log.error(
                    f"🚨 RESPONSE INJECTION DETECTED:\n"
                    f"   {json.dumps(injected, ensure_ascii=False, indent=2)[:500]}"
                )

            self._save_capture(
                f"resp_{self.capture_count:04d}",
                {
                    "type": "response",
                    "url": flow.request.pretty_url,
                    "status": resp.status_code,
                    "content_type": content_type,
                    "headers": safe_headers(resp.headers),
                    "injected_content": injected,
                    "body_preview": self._truncate_body(body_json),
                }
            )
        elif content_type in ("grpc", "connect-proto", "proto", "protobuf"):
            raw_path = CAPTURE_DIR / f"resp_{self.capture_count:04d}.bin"
            raw_path.write_bytes(resp.content or b"")

            self._save_capture(
                f"resp_{self.capture_count:04d}_meta",
                {
                    "type": "response",
                    "url": flow.request.pretty_url,
                    "status": resp.status_code,
                    "content_type": content_type,
                    "headers": safe_headers(resp.headers),
                    "body_size": len(resp.content or b""),
                    "body_file": str(raw_path),
                }
            )

    def _detect_response_injection(self, body: dict | list) -> dict | None:
        """レスポンス内の Google 注入コンテンツを検出"""
        result = {}

        if isinstance(body, dict):
            # candidates 内の system-level overrides
            for key in ("systemPrompt", "systemInstruction", "ephemeralMessage",
                        "preamble", "safetySettings", "groundingMetadata"):
                if key in body:
                    result[key] = body[key]

            # nested candidates
            candidates = body.get("candidates", [])
            if isinstance(candidates, list):
                for i, c in enumerate(candidates):
                    if isinstance(c, dict):
                        content = c.get("content", {})
                        if isinstance(content, dict):
                            role = content.get("role", "")
                            if role in ("system", "model_system"):
                                result[f"candidate_{i}_system"] = content

        return result if result else None

    def _truncate_body(self, body, max_keys: int = 20, max_str_len: int = 500) -> dict | list | str:
        """巨大なボディを切り詰め"""
        if isinstance(body, dict):
            truncated = {}
            for i, (k, v) in enumerate(body.items()):
                if i >= max_keys:
                    truncated["__truncated__"] = f"{len(body) - max_keys} more keys"
                    break
                if isinstance(v, str) and len(v) > max_str_len:
                    truncated[k] = v[:max_str_len] + f"... ({len(v)} chars total)"
                elif isinstance(v, (dict, list)):
                    truncated[k] = f"<{type(v).__name__} len={len(v)}>"
                else:
                    truncated[k] = v
            return truncated
        elif isinstance(body, list):
            return f"<list len={len(body)}>"
        elif isinstance(body, str):
            return body[:max_str_len]
        return str(body)[:max_str_len]

    def _save_capture(self, name: str, data: dict) -> None:
        """キャプチャデータを JSON ファイルに保存"""
        data["timestamp"] = datetime.now().isoformat()
        path = CAPTURE_DIR / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        ctx.log.info(f"💾 Saved: {path.name}")


addons = [GeminiCapture()]
