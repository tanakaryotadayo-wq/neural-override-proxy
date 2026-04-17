#!/bin/bash
# ============================================================
# Ryota-Core LoRA Training Script
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
MODEL_NAME="mlx-community/Qwen2.5-Coder-14B-Instruct-4bit"  # Stable base
CORPUS_DIR="$HOME/lora-training"
CORPUS_FILE="$CORPUS_DIR/corpus_text.jsonl" 
ADAPTER_DIR="$CORPUS_DIR/adapters/ryota-core-v1"
MERGED_DIR="$CORPUS_DIR/merged/ryota-core-v1"

# Training hyperparams
BATCH_SIZE=2
LORA_LAYERS=16
LORA_RANK=16
LEARNING_RATE=1e-5
ITERS=1000
VAL_BATCHES=25
SAVE_EVERY=200

echo "╔══════════════════════════════════════════╗"
echo "║  Ryota-Core LoRA Training                ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Model: $MODEL_NAME"
echo "║  Corpus: $CORPUS_FILE"
echo "║  Adapter: $ADAPTER_DIR"
echo "║  Iters: $ITERS  Batch: $BATCH_SIZE"
echo "║  LoRA Layers: $LORA_LAYERS  Rank: $LORA_RANK"
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
echo "▶ Step 2: Starting LoRA training..."
echo "  (This will take ~2-3 hours on M3 Ultra)"
echo ""

mkdir -p "$ADAPTER_DIR"

python3 -m mlx_lm.lora \
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

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅ Training Complete!                    ║"
echo "║  Adapter: $ADAPTER_DIR                   ║"
echo "╚══════════════════════════════════════════╝"

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
    echo "  To serve: mlx_lm.server --model $MERGED_DIR --port 8102"
fi

echo ""
echo "Done. To serve with adapter (no merge):"
echo "  python3 -m mlx_lm.server --model $MODEL_NAME --adapter-path $ADAPTER_DIR --port 8102"
