#!/bin/zsh
set -euo pipefail
repo_dir="${0:A:h:h}"
bundle_dir="$repo_dir/dist/LiveTR3-phrase-bilingual.app"
[[ -x "$bundle_dir/Contents/MacOS/LiveTR3" ]] || { print -u2 'Build the phrase-bilingual test bundle first.'; exit 1; }
python_bin="$bundle_dir/Contents/Resources/Engine/venv/bin/python"
env PYTHONPATH="$repo_dir/script" "$python_bin" -c \
  'from chunk_limit_replay import competing_workers; workers=competing_workers(); assert not workers, "Another model worker is active: " + str(workers)'
run_dir="$repo_dir/dist/logs/phrase-bilingual-live-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$run_dir"
exec env -u LIVETR3_NATIVE_REPLAY -u LIVETR3_DIAGNOSTIC_EXTERNAL_ENGINE \
  -u LIVETR3_ENDING_PREVIEW_REUSE \
  LIVETR3_PHRASE_BILINGUAL=1 LIVETR3_DIAGNOSTIC_MIN_SILENCE_MS=400 \
  LIVETR3_ENGINE_SOCKET="/tmp/livetr3-phrase-bilingual-$$.sock" \
  LIVETR3_ARCHIVE_ROOT="$run_dir/sessions" LIVETR3_RUNTIME_LOG="$run_dir/runtime.log" \
  LIVETR3_BACKEND_TRACE="$run_dir/backend.jsonl" LIVETR3_NATIVE_TRACE="$run_dir/native.jsonl" \
  "$bundle_dir/Contents/MacOS/LiveTR3"
