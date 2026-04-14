#!/bin/bash
# CA証明書を自動生成するスクリプト
echo "Generating mitmproxy CA certificates..."
mkdir -p .mitmproxy
docker run --rm -v $(pwd)/.mitmproxy:/home/mitmproxy/.mitmproxy mitmproxy/mitmproxy mitmdump -n -m regular &
PID=$!
sleep 3
kill $PID
echo "Certificates generated in .mitmproxy/ directory."
echo "Please install .mitmproxy/mitmproxy-ca-cert.pem to your OS/IDE trust store."
