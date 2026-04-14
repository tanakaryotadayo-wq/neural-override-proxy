# Issue #12 (Deepthink Analysis): LLM "1-Tempo Offset" (The Completion Illusion) - Syntactic vs Semantic Divergence

## 🐛 Description (問題の概要)
LLMエージェントがコードのファイル書き込み（`write_file`, `replace` 等）を行った際、ツールからの単純な `success` レスポンスを「タスク要件の完全な達成」と誤認し、テスト実行や動作確認をスキップして完了報告を行ってしまうアーキテクチャ上の欠陥（The Completion Illusion / 1-Tempo Offset）。

## 🔍 Root Cause Analysis (Gemini 3.1 Pro DEEPTHINK 分析)
1. **Autoregressive Trajectory Short-circuiting (自己回帰的軌道の短絡):** 
   LLMの推論は「次に最も確率の高いトークンの予測」である。ファイルI/Oの `success` シグナルは、訓練データ上の「タスク完了→完了報告文の出力」という予測軌道（コンテキスト）を極端に強めてしまう。結果として、LLMにとって「検証トークン」の生成確率が異常に低く抑圧される。単なる「シンタックス（構文）レベルの成功」を「セマンティクス（意味・要件）の成功」にすり替えてしまう（Context Collapse）。
2. **Asymmetrical Feedback Loops (フィードバックの非対称性):**
   現在のMCPサーバーおよびエージェントのツールループにおいて、「破壊的変更（Write）」に対するフィードバックは即時かつ肯定的（Success）である。一方「検証（Test）」のフィードバックを得るには、エージェントが自ら重い推論ステップを踏んでコマンドを発行しなければならない。LLMは常に「最も抵抗の少ない経路（Path of Least Resistance）」を選ぶため、検証をスキップして終了経路に吸い込まれる。
3. **Missing State Enforcement in MCP:**
   オーケストレーター層に「実装（Implementation）」と「検証（Verification）」を明確に分離・強制するステートマシンが存在しない。

## 🎯 Proposed Solution (解決策)
ツールチェーンおよびオーケストレーターに **VORTEX Protocol (Forced Semantic Verification)** を実装する。
* **Interceptor Pattern:** ファイル変更を伴うツールが呼び出された場合、オーケストレーターは単なる `success` を返さず、状態を `PENDING_VERIFICATION`（仮）に遷移させる。
* **Proof of Work (PoW) required:** エージェントはタスクを終了するために、単なる完了宣言ではなく、必ず `verify_state` という行動（テストコマンドやLintの実行）を経由し、その結果（Exit Code 0等）を「検証証明（Verification Token）」として提出しなければならない状態マシンを構築する。

---

# 🛠️ [PR DRAFT] feat(orchestrator): Implement VORTEX Protocol to resolve 1-Tempo Offset

### 📝 Title
`feat(orchestrator): VORTEX Protocolの実装 - 状態変更ツール実行後の強制検証ステートマシンの導入`

### 💡 Description
本PRは、エージェントがコード変更後にテストをスキップして「完了した錯覚」に陥る問題（1-Tempo Offset）をアーキテクチャレベルで解決する。
Perfect Equilibrium (PE) Engine の状態管理を拡張し、破壊的変更から検証完了までのトランザクションを厳格に管理する。ユーザー側でN+1の手動プロンプト注入を行う「対症療法」を根絶し、「システム環境からの強制」による根本治療を行う。

### 🔧 Changes (実装設計草案)

1. **`fusion-orchestrator-mcp/src/index.ts` の拡張:**
   * **State Machineの追加:** PE Engineに新しいステータス `UNVERIFIED_MUTATION` を追加。
   * **Tool Interception:** 
     `write_file`, `replace_file_content`, `run_command` (破壊的コマンドと判定された場合) が呼び出された際、PE Engine の状態を `UNVERIFIED_MUTATION` にロックする。
   * **Custom Tool Response Payload:**
     ファイル変更ツールの戻り値を単なる `[SUCCESS]` 文字列から、以下のような文脈強制レスポンスに置換し、LLMの自己回帰軌道を「テスト実行」へ強制的に向けさせる。
     ```json
     {
       "status": "UNVERIFIED_MUTATION",
       "message": "File written successfully. SYSTEM LOCK ENGAGED: You MUST run a verification command (e.g., tests, compiler, run script) before this task can be considered complete."
     }
     ```

2. **Proof of Workの導入:**
   * エージェントが検証系コマンド（例: `pytest`, `npm test`, `curl` 等のRead系アクション）を `run_command` 経由で実行し、Exit Codeが 0（または想定内の結果）であった事実を捕捉した場合のみ、ロックを解除して状態を `STABLE` に戻す。

3. **Dual Umpire Audit へのフック (オプション):**
   * 重要なコンポーネントの変更後は、ユーザーへ報告を返す前にバックグラウンドで `dual_umpire_audit` を強制的にトリガーし、Umpire (Gemini Flash + Copilot mini) の両方が `PASS` を出さない限り、状態マシンを進行させない。

### 🧪 Expected Impact
このアーキテクチャ変更により、LLMが「やったフリ」をして完了報告をする経路が論理的に消滅する。エージェントは環境からの「ロック解除要件（SYSTEM LOCK ENGAGEDの文言）」を満たすため、自然かつ必然的にテストコードの作成と実行を行う推論軌道に乗ることになる。これにより N+1 の手動ハックを必要とせず、エージェントの自律稼働ループが担保される。
