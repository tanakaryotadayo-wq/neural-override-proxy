#!/usr/bin/env python3
"""
Build Fine-Tuning corpus from KI + codebase for local AI training.
Output: JSONL file compatible with MLX LoRA training.

Usage:
  python3 build_ft_corpus.py --output corpus.jsonl
  python3 build_ft_corpus.py --output corpus.jsonl --format chat  # instruction-tuning
  python3 build_ft_corpus.py --output corpus.jsonl --format text  # continued pretraining
"""

import argparse
import glob
import json
import os
import sys

# Sources to collect
KI_BASE = os.path.expanduser("~/.gemini/antigravity/knowledge")
CODE_SOURCES = [
    os.path.expanduser("~/Newgate"),
    os.path.expanduser("~/neural-override-proxy"),
]
BRAIN_BASE = os.path.expanduser("~/.gemini/antigravity/brain")

# File extensions to include
CODE_EXTENSIONS = {".py", ".ts", ".js", ".json", ".md", ".sh", ".yaml", ".yml"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build"}
MAX_FILE_SIZE = 100_000  # 100KB max per file


def collect_ki_items() -> list[dict]:
    """Collect all KI artifacts as training documents."""
    items = []
    if not os.path.isdir(KI_BASE):
        print(f"  ⚠️  KI base not found: {KI_BASE}", file=sys.stderr)
        return items

    for ki_dir in sorted(glob.glob(f"{KI_BASE}/*/")):
        ki_name = os.path.basename(ki_dir.rstrip("/"))
        meta_path = os.path.join(ki_dir, "metadata.json")

        # Read metadata
        summary = ""
        if os.path.isfile(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                summary = meta.get("summary", "")
            except Exception:
                pass

        # Read all artifact files
        artifacts_dir = os.path.join(ki_dir, "artifacts")
        if not os.path.isdir(artifacts_dir):
            continue

        for root, dirs, files in os.walk(artifacts_dir):
            for fname in sorted(files):
                fpath = os.path.join(root, fname)
                if os.path.getsize(fpath) > MAX_FILE_SIZE:
                    continue
                try:
                    with open(fpath, "r", errors="replace") as f:
                        content = f.read().strip()
                except Exception:
                    continue

                if not content:
                    continue

                rel_path = os.path.relpath(fpath, KI_BASE)
                items.append({
                    "source": "ki",
                    "ki_name": ki_name,
                    "path": rel_path,
                    "summary": summary[:200] if summary else "",
                    "content": content,
                })

    return items


def collect_code_files() -> list[dict]:
    """Collect code files from project directories."""
    items = []

    for code_dir in CODE_SOURCES:
        if not os.path.isdir(code_dir):
            print(f"  ⚠️  Code dir not found: {code_dir}", file=sys.stderr)
            continue

        repo_name = os.path.basename(code_dir)
        for root, dirs, files in os.walk(code_dir):
            # Skip unwanted directories
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in CODE_EXTENSIONS:
                    continue

                fpath = os.path.join(root, fname)
                if os.path.getsize(fpath) > MAX_FILE_SIZE:
                    continue

                try:
                    with open(fpath, "r", errors="replace") as f:
                        content = f.read().strip()
                except Exception:
                    continue

                if not content or len(content) < 50:
                    continue

                rel_path = os.path.relpath(fpath, code_dir)
                items.append({
                    "source": "code",
                    "repo": repo_name,
                    "path": rel_path,
                    "content": content,
                })

    return items


def collect_conversations() -> list[dict]:
    """Collect conversation logs from brain/."""
    items = []
    if not os.path.isdir(BRAIN_BASE):
        return items

    for conv_dir in sorted(glob.glob(f"{BRAIN_BASE}/*/")):
        conv_id = os.path.basename(conv_dir.rstrip("/"))
        overview = os.path.join(conv_dir, ".system_generated", "logs", "overview.txt")

        if os.path.isfile(overview) and os.path.getsize(overview) > 100:
            try:
                with open(overview, "r", errors="replace") as f:
                    content = f.read().strip()
            except Exception:
                continue

            if content:
                items.append({
                    "source": "conversation",
                    "conversation_id": conv_id,
                    "content": content[:50000],  # Cap at 50K chars
                })

    return items


def format_text(items: list[dict]) -> list[str]:
    """Format for continued pretraining (raw text)."""
    docs = []
    for item in items:
        if item["source"] == "ki":
            header = f"# Knowledge Item: {item['ki_name']}\n## {item['path']}\n"
            if item.get("summary"):
                header += f"Summary: {item['summary']}\n\n"
            docs.append(header + item["content"])

        elif item["source"] == "code":
            header = f"# Code: {item['repo']}/{item['path']}\n"
            docs.append(header + f"```\n{item['content']}\n```")

        elif item["source"] == "conversation":
            header = f"# Conversation: {item['conversation_id']}\n"
            docs.append(header + item["content"])

    return docs


def format_chat(items: list[dict]) -> list[dict]:
    """Format for instruction tuning (chat format)."""
    pairs = []
    for item in items:
        if item["source"] == "ki":
            pairs.append({
                "messages": [
                    {"role": "user", "content": f"{item['ki_name']}について教えて。特に{item['path']}の内容を詳しく。"},
                    {"role": "assistant", "content": item["content"]},
                ]
            })

        elif item["source"] == "code":
            pairs.append({
                "messages": [
                    {"role": "user", "content": f"{item['repo']}の{item['path']}のコードを見せて。"},
                    {"role": "assistant", "content": f"```\n{item['content']}\n```"},
                ]
            })

    return pairs


def main():
    parser = argparse.ArgumentParser(description="Build FT corpus from KI + code")
    parser.add_argument("--output", "-o", default="corpus.jsonl", help="Output JSONL file")
    parser.add_argument("--format", choices=["text", "chat"], default="text",
                        help="text=continued pretraining, chat=instruction tuning")
    parser.add_argument("--stats", action="store_true", help="Print stats only, don't write")
    args = parser.parse_args()

    print("📦 Collecting KI items...")
    ki_items = collect_ki_items()
    print(f"   {len(ki_items)} KI artifacts")

    print("📦 Collecting code files...")
    code_items = collect_code_files()
    print(f"   {len(code_items)} code files")

    print("📦 Collecting conversations...")
    conv_items = collect_conversations()
    print(f"   {len(conv_items)} conversations")

    all_items = ki_items + code_items + conv_items
    total_chars = sum(len(item["content"]) for item in all_items)
    est_tokens = total_chars // 4  # rough estimate

    print(f"\n📊 Total: {len(all_items)} documents, ~{total_chars:,} chars, ~{est_tokens:,} tokens")

    if args.stats:
        print("\n📈 Breakdown:")
        print(f"   KI:            {len(ki_items):5d} docs, {sum(len(i['content']) for i in ki_items):>10,} chars")
        print(f"   Code:          {len(code_items):5d} docs, {sum(len(i['content']) for i in code_items):>10,} chars")
        print(f"   Conversations: {len(conv_items):5d} docs, {sum(len(i['content']) for i in conv_items):>10,} chars")
        return

    print(f"\n💾 Writing {args.format} format to {args.output}...")

    with open(args.output, "w") as f:
        if args.format == "text":
            docs = format_text(all_items)
            for doc in docs:
                f.write(json.dumps({"text": doc}, ensure_ascii=False) + "\n")
        else:
            pairs = format_chat(all_items)
            for pair in pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    output_size = os.path.getsize(args.output)
    print(f"✅ Done: {args.output} ({output_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
