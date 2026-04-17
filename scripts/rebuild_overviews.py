#!/usr/bin/env python3
"""
Rebuild overview.txt for all conversations from step data.
Fixes the broken Sovereign Memory pipeline by reconstructing
conversation logs from .system_generated/steps/ data.

Usage:
  python3 scripts/rebuild_overviews.py
  python3 scripts/rebuild_overviews.py --conversation <id>
"""

import argparse
import glob
import json
import os
import sys

BRAIN_BASE = os.path.expanduser("~/.gemini/antigravity/brain")


def rebuild_overview(conv_dir: str) -> int:
    """Rebuild overview.txt from steps/ and messages/ data."""
    conv_id = os.path.basename(conv_dir.rstrip("/"))
    steps_dir = os.path.join(conv_dir, ".system_generated", "steps")
    messages_dir = os.path.join(conv_dir, ".system_generated", "messages")
    logs_dir = os.path.join(conv_dir, ".system_generated", "logs")

    lines = []

    # 1. Collect from steps/
    if os.path.isdir(steps_dir):
        step_nums = []
        for entry in os.listdir(steps_dir):
            try:
                step_nums.append(int(entry))
            except ValueError:
                continue

        for step_num in sorted(step_nums):
            step_dir = os.path.join(steps_dir, str(step_num))
            output_file = os.path.join(step_dir, "output.txt")

            if os.path.isfile(output_file) and os.path.getsize(output_file) > 0:
                try:
                    with open(output_file, "r", errors="replace") as f:
                        content = f.read().strip()
                    if content:
                        lines.append(f"[step {step_num}] {content[:2000]}")
                except Exception:
                    pass

            # Also check for JSON metadata
            for json_file in glob.glob(os.path.join(step_dir, "*.json")):
                try:
                    with open(json_file, "r") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        if "content" in data:
                            lines.append(f"[step {step_num}] {str(data['content'])[:2000]}")
                        elif "output" in data:
                            lines.append(f"[step {step_num}] {str(data['output'])[:2000]}")
                except Exception:
                    pass

    # 2. Collect from messages/
    if os.path.isdir(messages_dir):
        messages = []
        for msg_file in glob.glob(os.path.join(messages_dir, "*.json")):
            try:
                with open(msg_file, "r") as f:
                    msg = json.load(f)
                ts = msg.get("timestamp", "")
                sender = msg.get("sender", "unknown")
                content = msg.get("content", "")
                if content and str(msg.get("hideFromUser", "")).lower() != "true":
                    messages.append((ts, f"[{sender}] {content[:2000]}"))
            except Exception:
                pass

        for _, line in sorted(messages):
            lines.append(line)

    # 3. Collect from artifacts (md files in conversation root)
    for md_file in sorted(glob.glob(os.path.join(conv_dir, "*.md"))):
        fname = os.path.basename(md_file)
        if fname.startswith("."):
            continue
        try:
            with open(md_file, "r", errors="replace") as f:
                content = f.read().strip()
            if content and len(content) > 50:
                lines.append(f"[artifact: {fname}] {content[:3000]}")
        except Exception:
            pass

    if not lines:
        return 0

    # Write overview.txt
    os.makedirs(logs_dir, exist_ok=True)
    overview_path = os.path.join(logs_dir, "overview.txt")
    with open(overview_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return len(lines)


def main():
    parser = argparse.ArgumentParser(description="Rebuild conversation overviews")
    parser.add_argument("--conversation", "-c", help="Specific conversation ID")
    args = parser.parse_args()

    if args.conversation:
        conv_dir = os.path.join(BRAIN_BASE, args.conversation)
        if not os.path.isdir(conv_dir):
            print(f"❌ Not found: {conv_dir}", file=sys.stderr)
            sys.exit(1)
        n = rebuild_overview(conv_dir)
        print(f"✅ {args.conversation}: {n} lines")
        return

    # Process all conversations
    total_rebuilt = 0
    total_lines = 0

    for conv_dir in sorted(glob.glob(f"{BRAIN_BASE}/*/")):
        conv_id = os.path.basename(conv_dir.rstrip("/"))
        if conv_id.startswith(".") or conv_id == "tempmediaStorage":
            continue

        n = rebuild_overview(conv_dir)
        if n > 0:
            print(f"  ✅ {conv_id}: {n} lines")
            total_rebuilt += 1
            total_lines += n
        else:
            print(f"  ⬚ {conv_id}: empty (skipped)")

    print(f"\n📊 Rebuilt {total_rebuilt} overviews, {total_lines} total lines")


if __name__ == "__main__":
    main()
