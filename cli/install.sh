#!/bin/bash
# ============================================================
# kc install script
# Usage: bash install.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KC_SRC="$SCRIPT_DIR/kc.py"
INSTALL_DIR="/usr/local/bin"
LINK="$INSTALL_DIR/kc"

echo "⚡ Installing kc — Knowledge CLI..."

# 実行権限
chmod +x "$KC_SRC"

# /usr/local/bin に symlink
if [ -L "$LINK" ] || [ -f "$LINK" ]; then
    rm -f "$LINK"
fi

ln -sf "$KC_SRC" "$LINK"
echo "  ✅ Linked: $LINK → $KC_SRC"

# 初期設定ディレクトリ
mkdir -p "$HOME/.kc"
echo "  ✅ Config dir: ~/.kc/"

echo ""
echo "Done! Try:"
echo "  kc 'PCC とは何か？'"
echo "  kc models"
echo "  kc repl"
echo ""
echo "Register Qwen3 KI蒸留 (after training):"
echo "  kc models add qwen3 http://localhost:8102/v1/chat/completions --model-name qwen3-ki-choryuu"
