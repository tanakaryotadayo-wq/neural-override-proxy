#!/bin/bash
# ============================================================================
# Newgate Repo Audit Sweep — Gemini 3.1 Pro × PCC multi-preset
# ============================================================================
# Usage: ./scripts/repo-audit-sweep.sh [--dry-run]
#
# Own repos:  feeds full tree to Gemini
# Fork repos: computes diff vs upstream/main, feeds ONLY user changes
# Reports saved to audit-reports/<repo>/<preset>_<timestamp>.md
# ============================================================================

set -euo pipefail
export PATH="/opt/homebrew/Cellar/node/25.3.0/bin:/opt/homebrew/bin:$PATH"

DRY_RUN="${1:-}"
REPORT_DIR="$(cd "$(dirname "$0")/.." && pwd)/audit-reports"
CLONE_DIR="/tmp/newgate-audit-clones"
DELAY_SECONDS=15
MODEL="gemini-3.1-pro-preview"

# ── Target repos ──
# Format: "owner/repo  type  upstream_owner  description"
# type=own → full tree analysis
# type=fork → diff vs upstream only
REPOS=(
  "tanakaryotadayo-wq/neural-override-proxy    own    -                  A2A Bridge + VORTEX拡張 + DeepSeek critic"
  "tanakaryotadayo-wq/pcc-critic               own    -                  PCC Constraint Injection × Multi-AI Critic"
  "tanakaryotadayo-wq/Antigravity              own    -                  Fusion Gate v4 — Claude Code Hooks"
  "tanakaryotadayo-wq/vscode-copilot-chat      fork   microsoft          Copilot Chat extension (microsoft fork)"
  "tanakaryotadayo-wq/gemini-cli               fork   google-gemini      Gemini CLI (google fork)"
  "tanakaryotadayo-wq/vscode-dotnet-runtime    fork   dotnet             .NET runtime extension (fork)"
  "tanakaryotadayo-wq/n8n-docs                 fork   n8n-io             n8n documentation (fork)"
  "tanakaryotadayo-wq/nvm                      fork   nvm-sh             Node Version Manager (fork)"
)

# ── PCC Presets ──
PRESETS=("監" "刃" "探" "極")

# ── Prompt: own repos ──
prompt_own_監() {
  cat <<'PROMPT'
[PCC:#監] このリポジトリを監査しろ。

タスク: Newgate（統合AI拡張機能）への統合候補ファイルを選別する。

以下を出力:
1. リポの目的と現状（1-2文）
2. 各ファイルの判定表:
   | ファイル | 行数 | 品質(A/B/C/D) | Newgateに統合すべきか(Y/N) | 理由 |
3. 統合対象の推奨優先順位（上位5つ）
4. 注意すべき問題（dirty state, 重複, 壊れたimport等）

証拠ベースで判断しろ。推測や好意的解釈は禁止。
PROMPT
}

prompt_own_刃() {
  cat <<'PROMPT'
[PCC:#刃] このリポのコード品質をレビューしろ。

出力:
1. テストカバレッジの実態（テストファイルの数 / 総ファイル数）
2. importの整合性（壊れたimport、存在しないモジュール参照）
3. 型安全性（TypeScript: any使用数、Python: type hints有無）
4. エラーハンドリング（try/catchの適切さ）
5. セキュリティ問題（ハードコードされた秘密鍵、APIキー露出）
6. 総合評価: S/A/B/C/D/F ランク + 1行コメント

構造化出力必須。各項目にファイル名と行番号を付けろ。
PROMPT
}

prompt_own_探() {
  cat <<'PROMPT'
[PCC:#探] このリポの全機能を列挙し、他のリポとの重複を探せ。

対象リポ群:
- neural-override-proxy (A2A Bridge, VORTEX critic, DeepSeek critic)
- pcc-critic (PCC制約注入パイプライン)
- Antigravity (Fusion Gate v4, Claude Code Hooks)
- vscode-copilot-chat (Copilot Chat fork, DeepSeek critic hooks)
- gemini-cli (Gemini CLI fork, PCC delegation, Newgate sidebar)

出力:
1. このリポにしかないユニークな機能
2. 他リポと重複している機能
3. obsolete（過去の失敗版）なファイル
4. Newgateに入れるべき「最良版」はどれか

批判的に分析。「どっちでもいい」は禁止。
PROMPT
}

prompt_own_極() {
  cat <<'PROMPT'
[PCC:#極] 全ファイルを3行以内で要約。テーブル形式厳守:
| ファイルパス | 行数 | 言語 | 要約 | 依存先 |
バイナリ、ロック、node_modules、.git除外。再帰的に全件。
PROMPT
}

# ── Prompt: fork repos (diff-based) ──
prompt_fork_監() {
  cat <<'PROMPT'
[PCC:#監] この差分はforkリポのupstreamとの差分である。ユーザーが追加・変更した部分のみを示している。

タスク: この差分の中から、Newgate（統合AI拡張機能）に移植する価値のあるコードを選別しろ。

出力:
1. 変更の概要（何を追加/変更したか、1-2文）
2. 追加ファイルの判定表:
   | ファイル | 追加行数 | 品質(A/B/C/D) | Newgateに統合すべきか(Y/N) | 理由 |
3. 変更ファイル（既存ファイルの改変）の判定:
   | ファイル | 変更行数 | fork依存か独立か | 移植可能か(Y/N) | 理由 |
4. このforkでしか実現できない機能はあるか

証拠ベースで判断しろ。
PROMPT
}

prompt_fork_刃() {
  cat <<'PROMPT'
[PCC:#刃] この差分のコード品質をレビューしろ。

出力:
1. 新規追加コードの品質評価（テスト有無、型安全性、エラー処理）
2. 既存コードの改変品質（破壊的変更の有無、副作用）
3. upstreamに依存する改変 vs 独立して動くコード の分類
4. 総合評価: S/A/B/C/D/F ランク

各項目にファイル名と行番号を付けろ。
PROMPT
}

prompt_fork_探() {
  cat <<'PROMPT'
[PCC:#探] この差分から、ユーザー独自のコードを抽出しろ。

出力:
1. upstream由来のコード vs ユーザーオリジナルコード の分離
2. ユーザーオリジナルで独立動作可能なモジュール一覧
3. upstreamのAPIに強く依存していてforkでしか動かないコード
4. 他のリポ（neural-override-proxy, pcc-critic等）に同等品があるか

「独立して動くもの」と「forkに縛られるもの」を明確に分けろ。
PROMPT
}

prompt_fork_極() {
  cat <<'PROMPT'
[PCC:#極] 差分の全変更ファイルを3行以内で要約。テーブル形式厳守:
| ファイルパス | 変更種別(A/M/D) | 行数(+/-) | 要約 | upstream依存度(高/中/低/なし) |
PROMPT
}

# ── Clone/pull helper ──
setup_repo() {
  local repo="$1" repo_type="$2" upstream_owner="$3" clone_path="$4"

  if [ -d "$clone_path/.git" ]; then
    git -C "$clone_path" fetch --all --quiet 2>/dev/null || true
  else
    if [ "$repo_type" = "fork" ]; then
      # Forks need full history for upstream diff
      git clone --quiet --no-tags "https://github.com/$repo.git" "$clone_path" 2>/dev/null || return 1
    else
      git clone --quiet --depth 1 "https://github.com/$repo.git" "$clone_path" 2>/dev/null || return 1
    fi
  fi

  # For forks: add upstream remote and fetch
  if [ "$repo_type" = "fork" ] && [ "$upstream_owner" != "-" ]; then
    local repo_name
    repo_name=$(basename "$repo")
    local upstream_url="https://github.com/${upstream_owner}/${repo_name}.git"

    if ! git -C "$clone_path" remote | grep -q upstream; then
      git -C "$clone_path" remote add upstream "$upstream_url" 2>/dev/null || true
    fi
    git -C "$clone_path" fetch upstream --quiet 2>/dev/null || true
  fi
}

# ── Generate context for Gemini ──
get_context() {
  local repo_type="$1" clone_path="$2"

  if [ "$repo_type" = "own" ]; then
    # Full tree listing + key file contents
    echo "=== DIRECTORY TREE ==="
    find "$clone_path" -type f \
      ! -path "*/.git/*" ! -path "*/node_modules/*" ! -path "*/__pycache__/*" \
      ! -path "*/dist/*" ! -path "*/.next/*" ! -name "*.lock" ! -name "package-lock.json" \
      | sed "s|$clone_path/||" | sort
    echo ""
    echo "=== FILE CONTENTS (key files only, first 200 lines each) ==="
    find "$clone_path" -type f \( -name "*.py" -o -name "*.ts" -o -name "*.js" -o -name "*.json" -o -name "*.md" -o -name "*.sh" -o -name "*.yaml" -o -name "*.yml" \) \
      ! -path "*/.git/*" ! -path "*/node_modules/*" ! -path "*/__pycache__/*" \
      ! -path "*/dist/*" ! -name "*.lock" ! -name "package-lock.json" \
      -size -50k | while read -r f; do
        local rel="${f#$clone_path/}"
        local lines
        lines=$(wc -l < "$f" 2>/dev/null || echo 0)
        echo "--- $rel ($lines lines) ---"
        head -200 "$f"
        echo ""
      done
  else
    # Fork: diff vs upstream
    echo "=== FORK DIFF vs UPSTREAM ==="
    local upstream_branch
    upstream_branch=$(git -C "$clone_path" rev-parse --verify upstream/main 2>/dev/null && echo "upstream/main" || echo "upstream/master")
    git -C "$clone_path" diff "$upstream_branch"..HEAD --stat 2>/dev/null || echo "(diff stat failed)"
    echo ""
    echo "=== FULL DIFF ==="
    git -C "$clone_path" diff "$upstream_branch"..HEAD 2>/dev/null | head -5000 || echo "(diff failed — upstream may not exist)"
  fi
}

# ── Main loop ──
mkdir -p "$CLONE_DIR"
total_calls=0
skipped=0

echo "╔══════════════════════════════════════════════════╗"
echo "║  Newgate Repo Audit Sweep                       ║"
echo "║  Model: $MODEL                    ║"
echo "║  Repos: ${#REPOS[@]}  Presets: ${#PRESETS[@]}  Total: $((${#REPOS[@]} * ${#PRESETS[@]})) calls    ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

for repo_line in "${REPOS[@]}"; do
  repo=$(echo "$repo_line" | awk '{print $1}')
  repo_type=$(echo "$repo_line" | awk '{print $2}')
  upstream_owner=$(echo "$repo_line" | awk '{print $3}')
  repo_name=$(basename "$repo")

  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📦 $repo_name ($repo_type)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  clone_path="$CLONE_DIR/$repo_name"
  if ! setup_repo "$repo" "$repo_type" "$upstream_owner" "$clone_path"; then
    echo "  ✗ setup failed, skipping"
    skipped=$((skipped + 1))
    continue
  fi

  # Get context once per repo
  context_file="/tmp/newgate-audit-context-${repo_name}.txt"
  echo "  📋 generating context..."
  get_context "$repo_type" "$clone_path" > "$context_file" 2>/dev/null

  context_size=$(wc -c < "$context_file" | tr -d ' ')
  echo "  📏 context size: $((context_size / 1024))KB"

  # Skip if context is empty
  if [ "$context_size" -lt 100 ]; then
    echo "  ✗ context too small, skipping"
    skipped=$((skipped + 1))
    continue
  fi

  report_path="$REPORT_DIR/$repo_name"
  mkdir -p "$report_path"

  for preset in "${PRESETS[@]}"; do
    ts=$(date +%Y%m%d_%H%M%S)
    output_file="$report_path/${preset}_${ts}.md"

    # Select prompt based on repo type
    prompt_fn="prompt_${repo_type}_${preset}"
    prompt_text=$($prompt_fn)

    # Combine prompt + context
    full_prompt="$prompt_text

--- REPOSITORY: $repo_name ($repo_type) ---

$(cat "$context_file")"

    echo "  ▶ PCC #${preset} → $(basename "$output_file")"

    if [ "$DRY_RUN" = "--dry-run" ]; then
      echo "  [DRY RUN] would send ${#full_prompt} chars to $MODEL"
      echo "# DRY RUN: $repo_name #${preset} (${#full_prompt} chars)" > "$output_file"
    else
      # Write prompt to temp file (avoids shell escaping issues with -p)
      prompt_tmp="/tmp/newgate-audit-prompt-$$.txt"
      echo "$full_prompt" > "$prompt_tmp"
      (
        cd "$clone_path"
        gemini -m "$MODEL" --approval-mode plan -p "$(cat "$prompt_tmp")" 2>&1
      ) > "$output_file" || echo "  ⚠ gemini error"
      rm -f "$prompt_tmp"
      echo "  ✅ done ($(wc -l < "$output_file" | tr -d ' ') lines)"
      echo "  ⏳ sleeping ${DELAY_SECONDS}s..."
      sleep "$DELAY_SECONDS"
    fi

    total_calls=$((total_calls + 1))
  done

  # Clean up context file
  rm -f "$context_file"
done

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅ Complete                                    ║"
echo "║  Calls: $total_calls  Skipped: $skipped                          ║"
echo "║  Reports: $REPORT_DIR  ║"
echo "╚══════════════════════════════════════════════════╝"
