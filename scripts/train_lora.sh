#!/bin/bash
# ============================================================
# Qwen3 Coder Next KI蒸留 (Knowledge-Injected LoRA)
# Qwen3 Coder Next Abliterated × Ryota-Core KI Corpus
# Run on Mac Studio (M3 Ultra 512GB)
#
# Usage:
#   1. scp corpus to Mac Studio:
#      scp ft-corpus/corpus_text.jsonl ryyota@mac-studio:~/lora-training/
#   2. SSH into Mac Studio and run:
#      bash scripts/train_lora.sh
# ============================================================

set -euo pipefail

# ── Config ──
MODEL_NAME="mlx-community/Qwen3-Coder-Next-4bit"  # 80B MoE abliterated
CORPUS_DIR="$HOME/lora-training"
CORPUS_FILE="$CORPUS_DIR/corpus_text.jsonl" 
ADAPTER_DIR="$CORPUS_DIR/adapters/qwen3-ki-choryuu-v1"
MERGED_DIR="$CORPUS_DIR/merged/qwen3-ki-choryuu-v1"

# iCloud backup
ICLOUD_BACKUP="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Qwen3-KI蒸留"

# Training hyperparams
BATCH_SIZE=2
LORA_LAYERS=16
LORA_RANK=16
LEARNING_RATE=1e-5
ITERS=1000
VAL_BATCHES=25
SAVE_EVERY=200

# Safety timeout (seconds) — kills training if stuck
# 80B MoE on M3 Ultra: ~4-8 hours typical, 10h max
TIMEOUT_HOURS=10
TIMEOUT_SECONDS=$((TIMEOUT_HOURS * 3600))

echo "╔══════════════════════════════════════════╗"
echo "║  🧠 Qwen3 Coder Next KI蒸留               ║"
echo "║  Knowledge-Injected LoRA Fine-Tuning     ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Model: $MODEL_NAME"
echo "║  Corpus: $CORPUS_FILE"
echo "║  Adapter: $ADAPTER_DIR"
echo "║  Iters: $ITERS  Batch: $BATCH_SIZE"
echo "║  LoRA Layers: $LORA_LAYERS  Rank: $LORA_RANK"
echo "║  iCloud: $ICLOUD_BACKUP"
echo "╚══════════════════════════════════════════╝"

# ── Pre-flight ──
echo ""
echo "▶ Step 0: Pre-flight checks..."

# Check MLX
python3 -c "import mlx; print(f'  ✅ MLX {mlx.__version__}')" || {
    echo "  ❌ MLX not found. Install: pip3 install mlx mlx-lm"
    exit 1
}

# Check mlx-lm
python3 -c "import mlx_lm; print(f'  ✅ mlx-lm {mlx_lm.__version__}')" || {
    echo "  ❌ mlx-lm not found. Install: pip3 install mlx-lm"
    exit 1
}

# Check corpus
if [ ! -f "$CORPUS_FILE" ]; then
    echo "  ❌ Corpus not found: $CORPUS_FILE"
    echo "     Run on MBA: scp ft-corpus/corpus_text.jsonl ryyota@mac-studio:~/lora-training/"
    exit 1
fi

CORPUS_SIZE=$(du -h "$CORPUS_FILE" | cut -f1)
CORPUS_LINES=$(wc -l < "$CORPUS_FILE" | tr -d ' ')
echo "  ✅ Corpus: $CORPUS_FILE ($CORPUS_SIZE, $CORPUS_LINES docs)"

# ── Step 1: Prep data ──
echo ""
echo "▶ Step 1: Preparing train/valid split..."

mkdir -p "$CORPUS_DIR/data"

python3 << 'PYEOF'
import json, random, os

corpus = os.path.expanduser("~/lora-training/corpus_text.jsonl")
data_dir = os.path.expanduser("~/lora-training/data")

# Read all docs
docs = []
with open(corpus) as f:
    for line in f:
        docs.append(line.strip())

# Shuffle and split 95/5
random.seed(42)
random.shuffle(docs)
split = int(len(docs) * 0.95)

train = docs[:split]
valid = docs[split:]

with open(f"{data_dir}/train.jsonl", "w") as f:
    f.write("\n".join(train) + "\n")

with open(f"{data_dir}/valid.jsonl", "w") as f:
    f.write("\n".join(valid) + "\n")

print(f"  ✅ Train: {len(train)} docs")
print(f"  ✅ Valid: {len(valid)} docs")
PYEOF

# ── Step 2: Train ──
echo ""
echo "▶ Step 2: Starting KIFT LoRA training..."
echo "  80B MoE → ~4-8 hours on M3 Ultra (timeout: ${TIMEOUT_HOURS}h)"
echo "  Checkpoints saved every ${SAVE_EVERY} iters (safe to kill)"
echo ""
START_TIME=$(date +%s)

mkdir -p "$ADAPTER_DIR"

# Run with timeout — training saves checkpoints, so killing is safe
timeout ${TIMEOUT_SECONDS} python3 -m mlx_lm.lora \
    --model "$MODEL_NAME" \
    --train \
    --data "$CORPUS_DIR/data" \
    --adapter-path "$ADAPTER_DIR" \
    --batch-size $BATCH_SIZE \
    --lora-layers $LORA_LAYERS \
    --lora-rank $LORA_RANK \
    --learning-rate $LEARNING_RATE \
    --iters $ITERS \
    --val-batches $VAL_BATCHES \
    --save-every $SAVE_EVERY

TRAIN_EXIT=$?
END_TIME=$(date +%s)
ELAPSED=$(( (END_TIME - START_TIME) / 60 ))

if [ $TRAIN_EXIT -eq 124 ]; then
    echo ""
    echo "⚠️  Training timed out after ${TIMEOUT_HOURS}h (${ELAPSED}min)"
    echo "   Last checkpoint saved in: $ADAPTER_DIR"
    echo "   Resume or use the partial adapter — it's still usable."
elif [ $TRAIN_EXIT -ne 0 ]; then
    echo ""
    echo "❌ Training failed (exit: $TRAIN_EXIT) after ${ELAPSED}min"
    echo "   Check logs. Last checkpoint may still be in: $ADAPTER_DIR"
else
    echo ""
    echo "✅ Training completed in ${ELAPSED} minutes"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅ Qwen3 KI蒸留 Training Complete!       ║"
echo "║  Adapter: $ADAPTER_DIR                   ║"
echo "╚══════════════════════════════════════════╝"

# ── Step 2.5: Auto-backup to iCloud + フォルダ保護 ──
echo ""
echo "▶ Step 2.5: Backing up to iCloud..."
mkdir -p "$ICLOUD_BACKUP"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="qwen3-ki-choryuu-v1_${TIMESTAMP}"
cp -r "$ADAPTER_DIR" "$ICLOUD_BACKUP/$BACKUP_NAME"
cp "$CORPUS_FILE" "$ICLOUD_BACKUP/corpus_text.jsonl" 2>/dev/null || true
echo "  ✅ Adapter backed up: $ICLOUD_BACKUP/$BACKUP_NAME"
echo "  ✅ Corpus backed up: $ICLOUD_BACKUP/corpus_text.jsonl"
echo "  📱 iCloud will sync automatically"

# ── フォルダ保護: chflags uchg — Finder・ターミナルからの誤删除を封じる ──
echo ""
echo "▶ Step 2.6: Protecting output folders from accidental deletion..."
# ローカルの adapter フォルダをロック
chflags -R uchg "$ADAPTER_DIR" && echo "  🔒 $ADAPTER_DIR locked" || echo "  ⚠️  Could not lock $ADAPTER_DIR"
# iCloudバックアップ先もロック
chflags -R uchg "$ICLOUD_BACKUP/$BACKUP_NAME" && echo "  🔒 $ICLOUD_BACKUP/$BACKUP_NAME locked" || echo "  ⚠️  Could not lock iCloud backup"
echo ""
echo "  ⚠️  NOTE: To DELETE later, first run:"
echo "    chflags -R nouchg $ADAPTER_DIR"
echo "    chflags -R nouchg \"$ICLOUD_BACKUP/$BACKUP_NAME\""

# ── Step 3: Test ──
echo ""
echo "▶ Step 3: Quick test..."

python3 << PYEOF
from mlx_lm import load, generate

model, tokenizer = load("$MODEL_NAME", adapter_path="$ADAPTER_DIR")

prompts = [
    "PCC (Personality Coordinate Control) とは何か？",
    "fusion-gate の Vector Proxy 5層防御を説明せよ。",
    "Neural Packet のスキーマ構造を示せ。",
]

for p in prompts:
    print(f"\n{'='*60}")
    print(f"Q: {p}")
    resp = generate(model, tokenizer, prompt=p, max_tokens=200)
    print(f"A: {resp}")

print("\n✅ Test complete")
PYEOF

# ── Optional: Merge ──
echo ""
read -p "▶ Merge adapter into model? (y/N): " merge
if [ "$merge" = "y" ]; then
    echo "  Merging..."
    mkdir -p "$MERGED_DIR"
    python3 -m mlx_lm.fuse \
        --model "$MODEL_NAME" \
        --adapter-path "$ADAPTER_DIR" \
        --save-path "$MERGED_DIR"
    echo "  ✅ Merged model: $MERGED_DIR"
    echo ""
    echo "  To serve (vLLM MLX):"
    echo "    vllm serve $MERGED_DIR --device mlx --port 8102 --served-model-name ryota-core"
fi

echo ""
echo "Done. To serve Qwen3 KI蒸留 (vLLM MLX):"
echo "  # Merged (recommended):"
echo "  vllm serve $MERGED_DIR --device mlx --port 8102 --served-model-name qwen3-ki-choryuu"
echo ""
echo "  # With adapter (no merge):"
echo "  python3 -m mlx_lm.server --model $MODEL_NAME --adapter-path $ADAPTER_DIR --port 8102"
echo ""
echo "  # iCloud backup location:"
echo "  $ICLOUD_BACKUP/"
echo ""
echo "  # To unlock folders if you need to delete:"
echo "  chflags -R nouchg $ADAPTER_DIR"
echo "  chflags -R nouchg \"$ICLOUD_BACKUP\""
