#!/usr/bin/env python3
"""
kc — Knowledge CLI
gh copilot CLI の器をそのまま使い、バックエンドをローカルAIに差し替えられる。

Usage (gh copilot と同じ):
  kc suggest [-t shell|git|gh] <prompt>
  kc explain <command>
  kc               # interactive REPL

Backend routing:
  ~/.kc/models.json にモデルを登録して切り替える
  kc --model qwen3 suggest 'list files recursively'
"""

import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ─── Paths ────────────────────────────────────────────────────────────────────
KC_DIR = Path.home() / ".kc"
MODELS_FILE = KC_DIR / "models.json"
CONFIG_FILE = KC_DIR / "config.json"
HISTORY_FILE = KC_DIR / "history.json"
RULES_FILE = KC_DIR / "rules.md"  # ← AIへの永続ルール

DEFAULT_RULES = """\
# kc AI Rules
# ここに書いたルールは全バックエンド・全コマンドに自動注入される。
# Markdown形式で書いてOK。

## 基本ルール
- 回答は簡潔に。冗長な前置きは省く。
- コードブロックは必ず言語タグを付ける。
- 日本語で質問されたら日本語で答える。
- 不確かなことは「わからない」と言う。嘘をつかない。

## 環境情報
- OS: macOS (Apple Silicon)
- Shell: zsh
- Primary language: Python / TypeScript

## 禁止事項
- 実行確認なしにファイルを削除・上書きするコマンドを提案しない。
- sudo を使うコマンドは必ず警告を付ける。
"""

# ─── ANSI ─────────────────────────────────────────────────────────────────────
R = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
GRAY = "\033[90m"
BG_DARK = "\033[48;5;236m"


def t(color: str, text: str) -> str:
    return f"{color}{text}{R}" if sys.stdout.isatty() else text


# ─── Config ───────────────────────────────────────────────────────────────────
def _init():
    KC_DIR.mkdir(exist_ok=True)
    if not MODELS_FILE.exists():
        MODELS_FILE.write_text(json.dumps({
            "copilot": {
                "type": "copilot",
                "display": "GitHub Copilot",
            },
            "claude": {
                "type": "claude",
                "display": "Claude (Anthropic)",
            },
        }, indent=2, ensure_ascii=False))
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps({
            "default_model": "copilot",
        }, indent=2))
    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text("[]")
    # rules.md が無ければデフォルトを生成
    if not RULES_FILE.exists():
        RULES_FILE.write_text(DEFAULT_RULES)


def _load_rules() -> str:
    """~/.kc/rules.md を読んで全バックエンドの system prompt に注入する。"""
    _init()
    try:
        text = RULES_FILE.read_text().strip()
        # コメント行(#)と空行は除いてコンパクトにする
        lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
        return "\n".join(lines)
    except Exception:
        return ""


def _models() -> dict:
    _init()
    return json.loads(MODELS_FILE.read_text())


def _cfg() -> dict:
    _init()
    return json.loads(CONFIG_FILE.read_text())


def _default_model() -> str:
    return _cfg().get("default_model", "copilot")


def _save_models(m: dict):
    _init()
    MODELS_FILE.write_text(json.dumps(m, indent=2, ensure_ascii=False))


def _save_cfg(c: dict):
    _init()
    CONFIG_FILE.write_text(json.dumps(c, indent=2))


def _append_history(entry: dict):
    try:
        h = json.loads(HISTORY_FILE.read_text())
        h.append(entry)
        HISTORY_FILE.write_text(json.dumps(h[-200:], indent=2, ensure_ascii=False))
    except Exception:
        pass


# ─── Terminal UI helpers (gh copilot スタイル) ────────────────────────────────

def _header(model_display: str):
    """gh copilot そっくりのヘッダー"""
    print()
    print(t(CYAN, BOLD + "Welcome to GitHub Copilot in the CLI!" + R))
    print(t(GRAY, f"  powered by: {model_display}"))
    print()


def _show_suggestion(suggestion: str, target: str = "shell"):
    """gh copilot suggest のコマンド表示ボックス"""
    lines = suggestion.strip().splitlines()
    width = max(len(l) for l in lines) + 4
    sep = "─" * width
    print()
    print(t(GRAY, f"  {sep}"))
    for line in lines:
        print(t(GRAY, "  │ ") + t(CYAN, BOLD + line + R))
    print(t(GRAY, f"  {sep}"))
    print()


def _show_explanation(explanation: str):
    """gh copilot explain のテキスト表示"""
    print()
    for line in explanation.strip().splitlines():
        print(f"  {line}")
    print()


def _menu(options: list, prompt: str = "? What would you like to do?") -> Optional[str]:
    """
    gh copilot の対話メニューを再現。
    矢印キー不要: 番号入力で選択。
    """
    print(t(BOLD, f"  {prompt}"))
    for i, (label, _) in enumerate(options, 1):
        print(f"  {t(GRAY, str(i) + '.')} {label}")
    print()
    try:
        raw = input(t(BOLD, "  > ")).strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx][1]
        # label prefix match
        for label, val in options:
            if label.lower().startswith(raw.lower()):
                return val
    except (KeyboardInterrupt, EOFError):
        pass
    return None


def _copy_to_clipboard(text: str):
    """macOS pbcopy でコピー。"""
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        print(t(GREEN, "  ✓ Copied to clipboard!"))
    except Exception:
        print(t(RED, "  ✗ pbcopy not available"))


def _rate(suggestion: str, target: str):
    """簡易フィードバック収録 (履歴に保存)。"""
    print(t(BOLD, "  ? Rate this response:"))
    print(f"  {t(GRAY, '1.')} 👍  Good")
    print(f"  {t(GRAY, '2.')} 👎  Bad")
    try:
        r = input(t(BOLD, "  > ")).strip()
        rating = "good" if r == "1" else "bad" if r == "2" else "skip"
        _append_history({"type": "rating", "rating": rating, "text": suggestion[:200]})
        print(t(GRAY, f"  Thanks for the feedback! ({rating})"))
    except (KeyboardInterrupt, EOFError):
        pass


# ─── Backends ─────────────────────────────────────────────────────────────────

def _call_copilot_suggest(query: str, target: str) -> Optional[str]:
    """gh copilot suggest をそのまま呼ぶ (gh が入っている場合)。"""
    try:
        result = subprocess.run(
            ["gh", "copilot", "suggest", "-t", target, "--", query],
            capture_output=True, text=True, timeout=30,
        )
        out = result.stdout.strip()
        # gh copilot は最後のコマンドを返す
        return out if out else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _call_copilot_explain(query: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["gh", "copilot", "explain", "--", query],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _call_claude(prompt: str, system: str = "") -> Optional[str]:
    """Claude API 直接呼び出し。"""
    api_key = os.getenv("ANTHROPIC_API_KEY") or _keychain("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    payload = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 2048,
        "system": system or "You are a helpful coding assistant. Be concise.",
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        data = json.dumps(payload).encode()
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
            return json.loads(resp.read())["content"][0]["text"]
    except Exception:
        return None


def _call_local(prompt: str, model_cfg: dict, system: str = "") -> Optional[str]:
    """OpenAI互換ローカルエンドポイント (vLLM MLX 等)。"""
    url = model_cfg.get("url", "http://localhost:8102/v1/chat/completions")
    model_name = model_cfg.get("model_name", "local")
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system or "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 2048,
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERROR: {e}]"


def _keychain(key: str) -> Optional[str]:
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", key, "-w"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip() or None
    except subprocess.CalledProcessError:
        return None


# ─── Core query dispatcher ────────────────────────────────────────────────────

def _query(prompt: str, model_key: str, system: str = "") -> Optional[str]:
    """
    モデルキーを元にバックエンドを選択して問い合わせ。
    ~/.kc/rules.md のルールを全バックエンドに自動注入する。
    """
    models = _models()
    cfg = models.get(model_key)
    if not cfg:
        print(t(RED, f"  Unknown model: {model_key}. Run: kc models"))
        return None

    # ── rules.md を system prompt の先頭に注入 ──
    rules = _load_rules()
    if rules:
        injected_system = f"{rules}\n\n---\n{system}" if system else rules
    else:
        injected_system = system

    mtype = cfg.get("type", "local")
    print(t(GRAY, f"  Asking {cfg.get('display', model_key)}..."), end="\r", flush=True)

    if mtype == "copilot":
        # gh copilot 経由で試みる (動かなければ claude フォールバック)
        result = _call_copilot_suggest(prompt, "shell")
        if result is None:
            result = _call_claude(prompt, injected_system)
    elif mtype == "claude":
        result = _call_claude(prompt, injected_system)
    elif mtype == "local":
        result = _call_local(prompt, cfg, injected_system)
    else:
        result = None

    # 表示のクリア
    print(" " * 60, end="\r")
    return result


# ─── Sub-commands ─────────────────────────────────────────────────────────────

def cmd_suggest(args):
    """
    gh copilot suggest と同じフロー:
    1. 問い合わせ → コマンド表示
    2. メニュー: Copy / Explain / Revise / Rate / Exit
    """
    _init()
    query = " ".join(args.query)
    target = getattr(args, "target", "shell")
    model_key = getattr(args, "model", None) or _default_model()
    models = _models()
    display = models.get(model_key, {}).get("display", model_key)

    _header(display)

    # suggest 用システムプロンプト
    system = (
        f"You are a CLI assistant. The user is on macOS zsh. "
        f"Target: {target} command. "
        "Respond with ONLY the command, no explanations, no markdown fences. "
        "Single line unless pipe is required."
    )
    prompt = f"Suggest a {target} command to: {query}"

    suggestion = _query(prompt, model_key, system)
    if not suggestion:
        print(t(RED, "  Failed to get suggestion."))
        return 1

    # コマンドだけ抽出 (```...``` を除去)
    suggestion = suggestion.strip().strip("`").strip()
    if suggestion.startswith("sh\n") or suggestion.startswith("bash\n"):
        suggestion = "\n".join(suggestion.splitlines()[1:])

    _show_suggestion(suggestion, target)
    _append_history({"type": "suggest", "query": query, "result": suggestion, "model": model_key})

    # ── インタラクティブメニュー (gh copilot そのまま) ──
    while True:
        action = _menu([
            ("Copy command to clipboard", "copy"),
            ("Explain command",           "explain"),
            ("Revise command",            "revise"),
            ("Rate response",             "rate"),
            ("Exit",                      "exit"),
        ])

        if action == "copy":
            _copy_to_clipboard(suggestion)
            break

        elif action == "explain":
            exp_system = (
                "Explain the following shell command clearly. "
                "Show what each part does. Keep it under 10 lines."
            )
            exp = _query(
                f"Explain this command:\n{suggestion}",
                model_key, exp_system,
            )
            if exp:
                _show_explanation(exp)

        elif action == "revise":
            try:
                revision = input(t(BOLD, "  Revision request: ")).strip()
            except (KeyboardInterrupt, EOFError):
                break
            rev_prompt = (
                f"Original request: {query}\n"
                f"Current command: {suggestion}\n"
                f"Revision: {revision}\n"
                "Give me the revised command only, no markdown."
            )
            new_suggestion = _query(rev_prompt, model_key, system)
            if new_suggestion:
                suggestion = new_suggestion.strip().strip("`").strip()
                _show_suggestion(suggestion, target)

        elif action == "rate":
            _rate(suggestion, target)
            break

        else:
            print(t(GRAY, "  Bye!"))
            break

    return 0


def cmd_status(args):
    """
    現在起動中のローカルAIサーバーを全部スキャンして一覧表示。
    /v1/models を実際に叩いてなにが動いてるか確認する。
    """
    _init()

    # デフォルトスキャン対象ポート
    scan_ports = [8101, 8102, 8103, 8104, 8765, 9700, 9800]

    print()
    print(t(BOLD, "  🖥️  Running AI Servers"))
    print(t(GRAY, f"  Scanned: {time.strftime('%H:%M:%S')}  —  MacBook Air (this machine)"))
    print()
    print(t(GRAY, "  " + "─" * 60))

    found_any = False
    for port in scan_ports:
        url = f"http://localhost:{port}/v1/models"
        t0 = time.time()
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                ms = int((time.time() - t0) * 1000)
                data = json.loads(resp.read())
                model_ids = [m["id"] for m in data.get("data", [])]
                for mid in model_ids:
                    found_any = True
                    # 短縮表示（長すぎる場合は屑尾を勝る）
                    label = mid if len(mid) <= 45 else mid[:42] + "..."
                    print(
                        f"  {t(GREEN, '●')}  "
                        f":{t(BOLD, str(port))}  "
                        f"{t(CYAN, label)}  "
                        f"{t(GRAY, str(ms) + 'ms')}"
                    )
        except (urllib.error.URLError, OSError):
            # ポートが広いので死んでるものはスキップ（クリーンな出力のため）
            pass
        except Exception as e:
            print(f"  {t(YELLOW, '?')}  :{port}  {t(GRAY, str(e)[:40])}")

    if not found_any:
        print(f"  {t(GRAY, '(no local servers found on ports ' + str(scan_ports) + ')')}")

    print(t(GRAY, "  " + "─" * 60))

    # ─── vLLM プロセス情報 — PID ・メモリ・ポート ───────────────────
    print()
    print(t(BOLD, "  🔎  Process Detail (vLLM / mlx_lm)"))
    print()
    try:
        ps_out = subprocess.check_output(
            ["ps", "ax", "-o", "pid,rss,command"],
            text=True,
        )
        for line in ps_out.splitlines():
            if "vllm" in line.lower() and "grep" not in line:
                parts = line.split(None, 2)
                if len(parts) < 3:
                    continue
                pid, rss_kb = parts[0], parts[1]
                cmd = parts[2]

                # ポートを抽出
                port_str = ""
                if "--port" in cmd:
                    idx = cmd.split().index("--port")
                    port_str = cmd.split()[idx + 1] if idx + 1 < len(cmd.split()) else ""

                # メモリを GB に
                try:
                    mem_gb = f"{int(rss_kb) / 1_048_576:.1f} GB"
                except ValueError:
                    mem_gb = rss_kb

                # サーブドモデル名を抽出
                served = ""
                if "--served-model-name" in cmd:
                    idx = cmd.split().index("--served-model-name")
                    served = cmd.split()[idx + 1] if idx + 1 < len(cmd.split()) else ""

                label = served or cmd.split()[1] if len(cmd.split()) > 1 else cmd[:50]
                label_short = label if len(label) <= 40 else label[:37] + "..."

                pid_str = t(GRAY, f"PID {pid}")
                port_label = t(BOLD, f":{port_str}") if port_str else t(GRAY, "?port")
                mem_label = t(YELLOW, mem_gb)

                print(f"    {port_label}  {t(CYAN, label_short)}")
                print(f"      {pid_str}  {mem_label}")
                print()
    except Exception as e:
        print(t(RED, f"  Failed to read processes: {e}"))

    return 0


def cmd_explain(args):
    """
    gh copilot explain と同じ: コマンドを説明する。
    """
    _init()
    command = " ".join(args.command)
    model_key = getattr(args, "model", None) or _default_model()
    models = _models()
    display = models.get(model_key, {}).get("display", model_key)

    _header(display)
    print(t(BOLD, f"  Explaining: ") + t(CYAN, command))

    system = (
        "Explain the shell command clearly. Cover: what it does, each flag/argument, "
        "and any gotchas. Keep it under 15 lines."
    )
    exp = _query(f"Explain: {command}", model_key, system)
    if exp:
        _show_explanation(exp)
        _append_history({"type": "explain", "command": command, "result": exp, "model": model_key})
    else:
        print(t(RED, "  Failed to get explanation."))
        return 1
    return 0


def cmd_rules(args):
    """~/.kc/rules.md の表示 / 編集 / リセット。"""
    _init()
    sub = getattr(args, "rules_sub", None)

    if sub == "edit":
        editor = os.getenv("EDITOR", "nano")
        subprocess.run([editor, str(RULES_FILE)])

    elif sub == "reset":
        RULES_FILE.write_text(DEFAULT_RULES)
        print(t(GREEN, f"  ✓ Rules reset to default: {RULES_FILE}"))

    elif sub == "path":
        print(str(RULES_FILE))

    else:
        # デフォルト: 現在のルールを表示
        rules = RULES_FILE.read_text()
        print()
        print(t(BOLD, f"  Rules file: {RULES_FILE}"))
        print(t(GRAY, "  (edit with: kc rules edit)"))
        print()
        for line in rules.splitlines():
            if line.startswith("#"):
                print(t(CYAN, f"  {line}"))
            elif line.strip():
                print(f"  {line}")
            else:
                print()
        print()

    return 0


def cmd_models(args):
    """モデル一覧 / 追加 / 削除 / デフォルト設定。"""
    _init()
    models = _models()
    default = _default_model()
    sub = getattr(args, "models_sub", None)

    if sub == "add":
        models[args.name] = {
            "type": "local",
            "display": getattr(args, "display", args.name),
            "url": args.url,
            "model_name": getattr(args, "model_name", args.name),
        }
        _save_models(models)
        print(t(GREEN, f"  ✓ Added: {args.name} → {args.url}"))

    elif sub == "remove":
        if args.name in models:
            del models[args.name]
            _save_models(models)
            print(t(GREEN, f"  ✓ Removed: {args.name}"))
        else:
            print(t(RED, f"  ✗ Not found: {args.name}"))

    elif sub == "default":
        c = _cfg()
        c["default_model"] = args.name
        _save_cfg(c)
        print(t(GREEN, f"  ✓ Default set to: {args.name}"))

    else:
        # 一覧表示
        print()
        print(t(BOLD, "  Registered models:"))
        print()
        for name, cfg in models.items():
            star = t(GREEN, " ★") if name == default else ""
            display = cfg.get("display", name)
            mtype = cfg.get("type", "?")
            url = cfg.get("url", "")
            print(f"  {t(CYAN, name)}{star}  {t(GRAY, display)}  [{mtype}]")
            if url:
                print(f"      {t(GRAY, url)}")
        print()

    return 0


def cmd_repl(args):
    """
    gh copilot interactive REPL 風: チャット形式で連続質問。
    """
    _init()
    model_key = getattr(args, "model", None) or _default_model()
    models = _models()
    display = models.get(model_key, {}).get("display", model_key)

    _header(display)
    print(t(GRAY, "  Type your question. Ctrl+C or 'exit' to quit."))
    print(t(GRAY, "  Slash commands: /model /clear /help"))
    print()

    history = []

    while True:
        try:
            user = input(t(BOLD, "> ")).strip()
        except (KeyboardInterrupt, EOFError):
            print(t(GRAY, "\n  Session ended."))
            break

        if not user:
            continue

        # Slash commands
        if user == "/help":
            print(t(GRAY, "  /model <name>  — switch model"))
            print(t(GRAY, "  /clear         — clear history"))
            print(t(GRAY, "  /models        — list models"))
            print(t(GRAY, "  exit / quit    — exit"))
            continue
        if user.startswith("/model "):
            model_key = user.split(" ", 1)[1].strip()
            display = _models().get(model_key, {}).get("display", model_key)
            print(t(GREEN, f"  ✓ Switched to: {model_key} ({display})"))
            continue
        if user == "/clear":
            history = []
            print(t(GRAY, "  History cleared."))
            continue
        if user == "/models":
            for name, cfg in _models().items():
                star = " ★" if name == _default_model() else ""
                print(f"  {t(CYAN, name)}{star}  {cfg.get('display', name)}")
            continue
        if user.lower() in ("exit", "quit", "bye"):
            print(t(GRAY, "  Bye!"))
            break

        # コンテキスト付きプロンプト
        history.append(f"User: {user}")
        ctx = "\n".join(history[-6:])
        result = _query(ctx, model_key)
        if result:
            print()
            _show_explanation(result)
            history.append(f"Assistant: {result[:200]}")

    return 0


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    _init()

    parser = argparse.ArgumentParser(
        prog="kc",
        description="kc — Knowledge CLI (gh copilot compatible, local AI ready)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Commands (gh copilot compatible):
              kc suggest [-t shell|git|gh] <prompt>
              kc explain <command>

            Extra:
              kc repl                     interactive chat
              kc models                   list models
              kc models add <n> <url>     register local AI
              kc models default <n>       set default

            Examples:
              kc suggest 'find all py files modified today'
              kc suggest -t git 'undo last commit but keep changes'
              kc explain 'find . -name "*.py" | xargs grep -l TODO'
              kc --model qwen3 suggest 'KI蒸留とは'
              kc models add qwen3 http://localhost:8102/v1/chat/completions
        """),
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Model to use (overrides default)",
    )
    parser.add_argument("--version", "-v", action="version", version="kc 1.0.0")

    sub = parser.add_subparsers(dest="cmd")

    # status
    p_stat = sub.add_parser("status", aliases=["st"], help="Show running AI servers")
    p_stat.set_defaults(func=cmd_status)

    # suggest
    p_sug = sub.add_parser("suggest", aliases=["s"], help="Suggest a command")
    p_sug.add_argument("-t", dest="target", default="shell",
                       choices=["shell", "git", "gh"], help="Target (default: shell)")
    p_sug.add_argument("query", nargs="+", help="What you want to do")
    p_sug.set_defaults(func=cmd_suggest)

    # explain
    p_exp = sub.add_parser("explain", aliases=["e"], help="Explain a command")
    p_exp.add_argument("command", nargs="+", help="Command to explain")
    p_exp.set_defaults(func=cmd_explain)

    # repl
    p_repl = sub.add_parser("repl", aliases=["r"], help="Interactive chat")
    p_repl.set_defaults(func=cmd_repl)

    # rules
    p_rules = sub.add_parser("rules", help="Manage AI rules (~/.kc/rules.md)")
    rsub = p_rules.add_subparsers(dest="rules_sub")
    p_rules.set_defaults(func=cmd_rules)
    rsub.add_parser("edit",  help="Open rules.md in $EDITOR").set_defaults(func=cmd_rules)
    rsub.add_parser("reset", help="Reset to default rules").set_defaults(func=cmd_rules)
    rsub.add_parser("path",  help="Print rules.md path").set_defaults(func=cmd_rules)

    # models
    p_mod = sub.add_parser("models", help="Manage model registry")
    msub = p_mod.add_subparsers(dest="models_sub")
    p_mod.set_defaults(func=cmd_models)

    p_add = msub.add_parser("add", help="Add a local model")
    p_add.add_argument("name", help="Alias")
    p_add.add_argument("url", help="OpenAI-compatible endpoint")
    p_add.add_argument("--model-name", dest="model_name", default=None)
    p_add.add_argument("--display", default=None, help="Display name")
    p_add.set_defaults(func=cmd_models)

    p_rm = msub.add_parser("remove", help="Remove a model")
    p_rm.add_argument("name")
    p_rm.set_defaults(func=cmd_models)

    p_def = msub.add_parser("default", help="Set default model")
    p_def.add_argument("name")
    p_def.set_defaults(func=cmd_models)

    # parse
    args, extra = parser.parse_known_args()

    # no subcommand → REPL
    if args.cmd is None:
        if extra:
            # kc 'some question' → suggest
            args.query = extra
            args.target = "shell"
            args.func = cmd_suggest
        else:
            args.func = cmd_repl

    if hasattr(args, "func"):
        sys.exit(args.func(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
