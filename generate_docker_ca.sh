#!/bin/bash
# generate_docker_ca.sh
set -e

echo "🔑 Generating self-signed CA for mitmproxy..."
mkdir -p .mitmproxy
# 権限を持たせるために docker コンテナで mitmdump を一度だけ実行して証明書を生成させる
docker run --rm -v "$(pwd)/.mitmproxy:/home/mitmproxy/.mitmproxy" mitmproxy/mitmproxy:8.1.1 mitmdump --version > /dev/null 2>&1 || true

# Wait until mitmproxy-ca-cert.pem is generated
if [ ! -f ".mitmproxy/mitmproxy-ca-cert.pem" ]; then
    echo "Wait, mitmdump --version might not generate certs. Running mitmdump momentarily..."
    docker run --rm -d --name temp-mitm -v "$(pwd)/.mitmproxy:/home/mitmproxy/.mitmproxy" mitmproxy/mitmproxy:8.1.1 mitmdump
    sleep 2
    docker rm -f temp-mitm > /dev/null
fi

CERT_FILE=".mitmproxy/mitmproxy-ca-cert.pem"

if [ -f "$CERT_FILE" ]; then
    echo "✅ CA generated at $CERT_FILE"
else
    echo "❌ Failed to generate CA."
    exit 1
fi
