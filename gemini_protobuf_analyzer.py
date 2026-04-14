#!/usr/bin/env python3
"""
gemini_protobuf_analyzer.py

mitmproxy で傍受した Gemini API 通信 (Protobuf binary) を解析するツール。
systemInstruction, ephemeralMessage, plannerConfig の構造を抽出して表示する。

Usage:
  python3 gemini_protobuf_analyzer.py captures/req_0001.bin
  python3 gemini_protobuf_analyzer.py captures/req_0001.bin --json
"""

import argparse
import json
import sys
from pathlib import Path

# TODO: Add protobuf import here
# from google.protobuf.internal.decoder import _DecodeVarint32

def parse_protobuf_binary(data: bytes) -> dict:
    """
    TODO: mitmproxy から出力された raw protobuf bytes を解析し、
    systemInstruction, ephemeralMessage, plannerConfig などを抽出して dict で返す
    """
    raise NotImplementedError("Jules / Qwen: Implement protobuf parsing logic here using 'protobuf' package.")

def main():
    parser = argparse.ArgumentParser(description="Gemini API Protobuf Analyzer")
    parser.add_argument("file", type=Path, help="Path to the binary or HAR file to analyze")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"Error: File not found: {args.file}")
        sys.exit(1)

    # TODO: HAR ファイル処理と raw binary 読み込みの分岐ロジック
    
    # テンプレ出力
    if args.json:
        print(json.dumps({"status": "unimplemented", "file": str(args.file)}))
    else:
        print(f"Analyzing {args.file}...")
        print("Not implemented yet.")

if __name__ == "__main__":
    main()
