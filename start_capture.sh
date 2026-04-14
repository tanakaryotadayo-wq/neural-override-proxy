#!/bin/bash
# start_capture.sh — Gemini API 通信傍受を開始
# Usage: ./start_capture.sh [--web]
#
# --web: mitmweb (WebUI付き) で起動、ポート8081でアクセス可能
# デフォルト: mitmdump (CUI、ログのみ)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ADDON="${SCRIPT_DIR}/mitm_gemini_capture.py"
PROXY_PORT="${PROXY_PORT:-18080}"
WEB_PORT="${WEB_PORT:-8081}"
CONF_DIR="${HOME}/.mitmproxy"

# Electron (Antigravity) 用に NODE_EXTRA_CA_CERTS を設定
export NODE_EXTRA_CA_CERTS="${CONF_DIR}/mitmproxy-ca-cert.pem"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔥 Neural Override Proxy — Gemini Capture Mode"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Proxy port: ${PROXY_PORT}"
echo "  Addon:      ${ADDON}"
echo "  Captures:   ${SCRIPT_DIR}/captures/"
echo "  CA cert:    ${CONF_DIR}/mitmproxy-ca-cert.pem"
echo ""
echo "  Antigravity settings.json に以下を追加:"
echo "    \"http.proxy\": \"http://127.0.0.1:${PROXY_PORT}\""
echo "    \"http.proxyStrictSSL\": false"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

mkdir -p "${SCRIPT_DIR}/captures"

if [[ "${1:-}" == "--web" ]]; then
    echo "🌐 Starting mitmweb (WebUI: http://127.0.0.1:${WEB_PORT})"
    exec mitmweb \
        --listen-port "${PROXY_PORT}" \
        --web-port "${WEB_PORT}" \
        --web-open-browser \
        --set confdir="${CONF_DIR}" \
        -s "${ADDON}" \
        --set console_focus_follow=true
else
    echo "📟 Starting mitmdump (CUI mode)"
    exec mitmdump \
        --listen-port "${PROXY_PORT}" \
        --set confdir="${CONF_DIR}" \
        -s "${ADDON}" \
        --set console_focus_follow=true
fi
