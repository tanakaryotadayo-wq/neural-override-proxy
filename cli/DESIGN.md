# CLI 設計: kc (Knowledge CLI)

## コンセプト

```
kc [prompt]                  # デフォルト ask (Claude寄り)
kc code [prompt]             # コーディングモード
kc fix [file]                # エラー修正
kc explain [file/prompt]     # コード説明
kc models                    # 登録モデル一覧
kc models add <name> <url>   # ローカルAI登録
kc --backend claude          # バックエンド指定
kc --backend copilot
kc --backend qwen3           # Qwen3 KI蒸留
```

## アーキテクチャ

```
[kc CLI]
    │
    ├─ InputProcessor  (コンテキスト収集: git diff, ファイル, エラー)
    │
    ├─ Router (Claude Code 寄り)
    │     ├─ prefer: claude → claude_backend.py
    │     ├─ fallback: copilot → copilot_backend.py
    │     └─ local: vLLM MLX → local_backend.py
    │
    └─ OutputRenderer  (rich カラー出力 + コードブロック)
```

## Claude Code 寄りアルゴリズム

- Agentic: 1ターンで完結せず、ファイル読み込み→分析→提案のステップを踏む
- Context-aware: 現在のgit diff / ファイルを自動注入
- Multi-shot: 回答後に続きを聞ける (REPL モード)
