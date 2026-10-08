#!/usr/bin/env bash
# Ordered off/on/on/off FLEURS replay of the early final decode
# (LIVETR3_EARLY_FINAL_MS), then one score table. Stop live capture first.
# Usage: script/early_final_ab.sh [eval-dir] [output-root]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVAL_DIR="$(cd "${1:-$ROOT/dist/eval/fleurs-v1}" && pwd)"
OUT="${2:-$ROOT/dist/logs/fleurs/early-final-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"

run() {
  echo "== $1 (LIVETR3_EARLY_FINAL_MS=$2)"
  (cd "$ROOT/app/backend" && LIVETR3_EARLY_FINAL_MS="$2" PYTHONPATH=. uv run python \
    "$ROOT/script/fleurs_replay.py" --eval-dir "$EVAL_DIR" --output "$OUT/$1" \
    --mode mtp --conditions 6:600:2:200)
}

run 1-off 0
run 2-on 200
run 3-on 200
run 4-off 0

cd "$ROOT/app/backend"
uv run --with sacrebleu --with whisper-normalizer python -I "$ROOT/script/fleurs_score.py" \
  --eval-dir "$EVAL_DIR" --json "$OUT/scores.json" "$OUT"/1-off "$OUT"/2-on "$OUT"/3-on "$OUT"/4-off
