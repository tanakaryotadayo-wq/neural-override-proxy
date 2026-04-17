#!/usr/bin/env python3
"""
kc — Knowledge CLI
Claude Code寄りアルゴリズムで動く統合AIコーディングCLI

Backends:
  claude   → claude CLI (Claude Code)
  copilot  → gh copilot suggest/explain
  local    → vLLM MLX endpoint (Qwen3 KI蒸留 等)

Usage:
  kc [prompt]
  kc code [prompt]
  kc fix path/to/file.py
  kc explain path/to/file.py
  kc models
  kc models add <name> <url>
  kc --backend copilot [prompt]
"""

import argparse
import json
import os
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ── Config paths ──────────────────────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".kc"
MODELS_FILE = CONFIG_DIR / "models.json"
CONFIG_FILE = CONFIG_DIR / "config.json"

# ── Terminal colors ────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


def c(color: str, text: str) -> str:
    """Apply ANSI color if stdout is a tty."""
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{RESET}"


def banner():
    print(c(CYAN, BOLD + "⚡ kc" + RESET) + c(DIM, " — Knowledge CLI"))


def print_model_tag(name: str):
    print(c(DIM, f"  [{name}]"))


# ── Config / Model Registry ────────────────────────────────────────────────────
def ensure_config():
    CONFIG_DIR.mkdir(exist_ok=True)
    if not MODELS_FILE.exists():
        default_models = {
            "claude": {
                "type": "claude",
                "description": "Claude Code (default)",
                "default": True,
            },
            "copilot": {
                "type": "copilot",
                "description": "GitHub Copilot CLI",
            },
        }
        MODELS_FILE.write_text(json.dumps(default_models, indent=2, ensure_ascii=False))
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps({"default_backend": "claude"}, indent=2))


def load_models() -> dict:
    ensure_config()
    return json.loads(MODELS_FILE.read_text())


def load_config() -> dict:
    ensure_config()
    return json.loads(CONFIG_FILE.read_text())


def save_models(models: dict):
    ensure_config()
    MODELS_FILE.write_text(json.dumps(models, indent=2, ensure_ascii=False))


def get_default_backend() -> str:
    return load_config().get("default_backend", "claude")


# ── Context collector (Claude Code 寄り: git / file aware) ────────────────────
def collect_context(target_file: Optional[str] = None) -> str:
    """
    Claude Code アルゴリズム: ファイルと git diff を自動収集してコンテキストとして注入。
    """
    context_parts = []

    # git diff HEAD (変更中のファイル)
    try:
        diff = subprocess.check_output(
            ["git", "diff", "HEAD", "--stat"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if diff:
            context_parts.append(f"[git diff --stat]\n{diff[:1000]}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # 指定ファイルの内容
    if target_file and Path(target_file).is_file():
        content = Path(target_file).read_text(errors="replace")
        lang = Path(target_file).suffix.lstrip(".")
        # 長すぎる場合は先頭200行だけ
        lines = content.splitlines()
        if len(lines) > 200:
            content = "\n".join(lines[:200]) + f"\n... ({len(lines)-200} more lines)"
        context_parts.append(f"[file: {target_file}]\n```{lang}\n{content}\n```")

    return "\n\n".join(context_parts)


# ── Backends ─────────────────────────────────────────────────────────────────

def backend_claude(prompt: str, mode: str = "ask") -> int:
    """
    Claude Code バックエンド。
    `claude` CLI がなければ Anthropic API 直接呼び出しにフォールバック。
    """
    # claude CLI があれば使う
    try:
        subprocess.run(["which", "claude"], check=True, capture_output=True)
        cmd = ["claude", "--print", prompt] if mode != "code" else ["claude", "--print", prompt]
        return subprocess.run(cmd).returncode
    except subprocess.CalledProcessError:
        pass

    # フォールバック: ANTHROPIC_API_KEY で直接 API 呼び出し
    api_key = os.getenv("ANTHROPIC_API_KEY") or _keychain_get("ANTHROPIC_API_KEY")
    if not api_key:
        print(c(RED, "❌ claude CLI not found and ANTHROPIC_API_KEY not set."))
        print(c(DIM, "   Install: brew install anthropic/tap/claude"))
        print(c(DIM, "   Or: export ANTHROPIC_API_KEY=sk-ant-..."))
        return 1

    system = (
        "You are an expert coding assistant. "
        "Be concise. Show code blocks when relevant."
    )
    if mode == "code":
        system += " Focus on producing working code."

    return _anthropic_api_call(api_key, system, prompt)


def backend_copilot(prompt: str, mode: str = "ask") -> int:
    """
    GitHub Copilot CLI バックエンド。
    gh copilot suggest (code) / gh copilot explain (explain)
    """
    try:
        subprocess.run(["which", "gh"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print(c(RED, "❌ gh CLI not found. Install: brew install gh"))
        return 1

    if mode in ("code", "fix"):
        cmd = ["gh", "copilot", "suggest", "-t", "shell", prompt]
    elif mode == "explain":
        cmd = ["gh", "copilot", "explain", prompt]
    else:
        cmd = ["gh", "copilot", "suggest", prompt]

    return subprocess.run(cmd).returncode


def backend_local(prompt: str, model_cfg: dict, mode: str = "ask") -> int:
    """
    ローカルAI バックエンド (vLLM MLX / mlx_lm.server 互換)
    OpenAI互換エンドポイントを叩く。
    """
    url = model_cfg.get("url", "http://localhost:8102/v1/chat/completions")
    model_name = model_cfg.get("model_name", "local")

    system = "あなたは優秀なAIコーディングアシスタントです。日本語で回答してください。"
    if mode == "code":
        system += "コードブロックを使い、動くコードを出力してください。"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 2048,
        "stream": False,
    }

    print(c(CYAN, f"  Querying {model_cfg.get('description', model_name)}..."), flush=True)

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            content = result["choices"][0]["message"]["content"]
            print()
            print(content)
            return 0
    except urllib.error.URLError as e:
        print(c(RED, f"❌ Local model unreachable: {e}"))
        print(c(DIM, f"   Is the server running? vllm serve --port 8102"))
        return 1
    except Exception as e:
        print(c(RED, f"❌ Error: {e}"))
        return 1


def _anthropic_api_call(api_key: str, system: str, prompt: str) -> int:
    """Anthropic Messages API 直接呼び出し (claude CLI フォールバック)."""
    payload = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 4096,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            text = result["content"][0]["text"]
            print()
            _render_output(text)
            return 0
    except Exception as e:
        print(c(RED, f"❌ API error: {e}"))
        return 1


def _keychain_get(key: str) -> Optional[str]:
    """macOS Keychain からシークレットを取得。"""
    try:
        out = subprocess.check_output(
            ["security", "find-generic-password", "-s", key, "-w"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or None
    except subprocess.CalledProcessError:
        return None


def _render_output(text: str):
    """コードブロックをハイライト表示 (簡易)。"""
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            print(c(DIM, line))
        elif in_code:
            print(c(CYAN, line))
        else:
            print(line)


# ── Router (Claude Code 寄り) ─────────────────────────────────────────────────
def route(backend_name: str, prompt: str, mode: str = "ask") -> int:
    """
    バックエンドを選択してルーティング。
    デフォルトは claude (Claude Code 寄り)。
    """
    models = load_models()

    print_model_tag(backend_name)

    if backend_name == "claude":
        return backend_claude(prompt, mode)
    elif backend_name == "copilot":
        return backend_copilot(prompt, mode)
    elif backend_name in models:
        cfg = models[backend_name]
        if cfg.get("type") == "local":
            return backend_local(prompt, cfg, mode)
        else:
            print(c(RED, f"❌ Unknown model type: {cfg.get('type')}"))
            return 1
    else:
        print(c(RED, f"❌ Unknown backend: {backend_name}"))
        print(c(DIM, "  Run: kc models"))
        return 1


# ── Sub-commands ──────────────────────────────────────────────────────────────

def cmd_ask(args):
    """汎用質問 (Claude Code 寄り: コンテキスト自動注入)。"""
    prompt = " ".join(args.prompt)
    context = collect_context()
    if context:
        full_prompt = f"{context}\n\n---\n{prompt}"
    else:
        full_prompt = prompt
    return route(args.backend, full_prompt, mode="ask")


def cmd_code(args):
    """コーディング特化モード (Claude Code 寄り)。"""
    prompt = " ".join(args.prompt)
    context = collect_context()
    full_prompt = f"Write working code for the following task:\n\n{prompt}"
    if context:
        full_prompt = f"{context}\n\n---\n{full_prompt}"
    return route(args.backend, full_prompt, mode="code")


def cmd_fix(args):
    """ファイルのバグ修正 (Claude Code 寄り: ファイル全体読み込み)。"""
    file_path = args.file
    context = collect_context(target_file=file_path)
    if not context:
        print(c(RED, f"❌ File not found: {file_path}"))
        return 1
    prompt = f"{context}\n\n---\nIdentify and fix all bugs in this file. Show only the corrected code."
    return route(args.backend, prompt, mode="code")


def cmd_explain(args):
    """コード説明モード。"""
    # ファイルか文字列か判定
    text = " ".join(args.target) if hasattr(args, "target") else ""
    if text and Path(text).is_file():
        context = collect_context(target_file=text)
        prompt = f"{context}\n\n---\nExplain this code in detail. Focus on what it does and why."
    else:
        prompt = f"Explain the following:\n\n{text}"
    return route(args.backend, prompt, mode="ask")


def cmd_models(args):
    """モデル一覧 / 追加 / 削除。"""
    models = load_models()

    if hasattr(args, "models_cmd") and args.models_cmd == "add":
        # kc models add <name> <url> [--model-name <model>] [--description <desc>]
        new_model = {
            "type": "local",
            "url": args.url,
            "model_name": getattr(args, "model_name", args.name),
            "description": getattr(args, "description", args.name),
        }
        models[args.name] = new_model
        save_models(models)
        print(c(GREEN, f"✅ Registered: {args.name} → {args.url}"))
        return 0

    if hasattr(args, "models_cmd") and args.models_cmd == "remove":
        if args.name in models:
            del models[args.name]
            save_models(models)
            print(c(GREEN, f"✅ Removed: {args.name}"))
        else:
            print(c(RED, f"❌ Not found: {args.name}"))
        return 0

    if hasattr(args, "models_cmd") and args.models_cmd == "default":
        cfg = load_config()
        cfg["default_backend"] = args.name
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
        print(c(GREEN, f"✅ Default backend set to: {args.name}"))
        return 0

    # デフォルト: 一覧表示
    default_be = get_default_backend()
    print(c(BOLD, "\n📦 Registered Models:\n"))
    for name, cfg in models.items():
        tag = c(GREEN, " ★ default") if name == default_be else ""
        desc = cfg.get("description", name)
        mtype = cfg.get("type", "?")
        url = cfg.get("url", "")
        url_str = c(DIM, f"  {url}") if url else ""
        print(f"  {c(CYAN, name)}{tag}")
        print(f"    {desc} [{mtype}]{url_str}")
    print()
    return 0


# ── REPL (multi-turn, Claude Code 寄り) ──────────────────────────────────────
def cmd_repl(args):
    """
    インタラクティブ REPL モード。
    Claude Code 寄り: 会話コンテキストを保持しながら連続質問できる。
    """
    backend = args.backend
    models = load_models()

    print(c(CYAN, f"\n⚡ kc REPL [{backend}]") + c(DIM, "  (Ctrl+C / 'exit' to quit)\n"))

    history = []  # multi-turn コンテキスト

    while True:
        try:
            user_input = input(c(BOLD, "you> ")).strip()
        except (KeyboardInterrupt, EOFError):
            print(c(DIM, "\nbye."))
            break

        if not user_input or user_input.lower() in ("exit", "quit", "bye"):
            print(c(DIM, "bye."))
            break

        # コンテキスト付きプロンプト組み立て
        history.append(f"User: {user_input}")
        context = collect_context()
        full_prompt = ""
        if context:
            full_prompt += f"{context}\n\n---\n"
        if len(history) > 1:
            full_prompt += "Previous conversation:\n"
            full_prompt += "\n".join(history[:-1][-6:])  # 直近3ターン
            full_prompt += "\n\n---\n"
        full_prompt += user_input

        print()
        route(backend, full_prompt, mode="ask")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ensure_config()
    default_be = get_default_backend()

    parser = argparse.ArgumentParser(
        prog="kc",
        description="kc — Knowledge CLI: Claude Code × Copilot × Local AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(f"""\
            Examples:
              kc 'PCC とは何か？'
              kc code 'FastAPI で /health エンドポイントを作れ'
              kc fix src/main.py
              kc explain src/vector_proxy.py
              kc repl
              kc --backend copilot 'how to reverse a list in python'
              kc --backend qwen3 'LoRA とは何か？'
              kc models
              kc models add qwen3 http://localhost:8102/v1/chat/completions

            Default backend: {default_be}
            Config: ~/.kc/
        """),
    )
    parser.add_argument(
        "--backend", "-b",
        default=default_be,
        help=f"Backend to use (default: {default_be})",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version="kc 1.0.0 — Knowledge CLI",
    )

    subparsers = parser.add_subparsers(dest="command")

    # ask (default)
    sp_ask = subparsers.add_parser("ask", help="Ask a question")
    sp_ask.add_argument("prompt", nargs="+")
    sp_ask.set_defaults(func=cmd_ask)

    # code
    sp_code = subparsers.add_parser("code", help="Code generation mode")
    sp_code.add_argument("prompt", nargs="+")
    sp_code.set_defaults(func=cmd_code)

    # fix
    sp_fix = subparsers.add_parser("fix", help="Fix bugs in a file")
    sp_fix.add_argument("file")
    sp_fix.set_defaults(func=cmd_fix)

    # explain
    sp_explain = subparsers.add_parser("explain", help="Explain code or text")
    sp_explain.add_argument("target", nargs="+")
    sp_explain.set_defaults(func=cmd_explain)

    # repl
    sp_repl = subparsers.add_parser("repl", help="Interactive REPL (multi-turn)")
    sp_repl.set_defaults(func=cmd_repl)

    # models
    sp_models = subparsers.add_parser("models", help="Manage AI model registry")
    models_sub = sp_models.add_subparsers(dest="models_cmd")

    sp_models_add = models_sub.add_parser("add", help="Register a new model")
    sp_models_add.add_argument("name", help="Model alias (e.g. qwen3)")
    sp_models_add.add_argument("url", help="OpenAI-compatible endpoint URL")
    sp_models_add.add_argument("--model-name", default=None, dest="model_name")
    sp_models_add.add_argument("--description", default=None, dest="description")

    sp_models_rm = models_sub.add_parser("remove", help="Remove a model")
    sp_models_rm.add_argument("name")

    sp_models_default = models_sub.add_parser("default", help="Set default backend")
    sp_models_default.add_argument("name")

    sp_models.set_defaults(func=cmd_models)

    # ── Parse ──────────────────────────────────────────────────────────────────
    # kc [prompt without subcommand] → ask
    args, remaining = parser.parse_known_args()

    banner()

    if args.command is None:
        if remaining:
            args.prompt = remaining
            args.func = cmd_ask
            args.command = "ask"
        else:
            # no args → repl
            args.func = cmd_repl
            args.command = "repl"

    if hasattr(args, "func"):
        sys.exit(args.func(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
