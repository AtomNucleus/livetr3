#!/bin/zsh
set -euo pipefail
repo_dir=${0:A:h:h}
mode=${1:-mtp}
case "$mode" in
  mtp) enabled=1 ;;
  baseline) enabled=0 ;;
  *) print -u2 'Usage: launch_mtp_candidate.sh [mtp|baseline]'; exit 2 ;;
esac
bundle_dir="$repo_dir/dist/LiveTR3-gemma-mtp.app"
[[ -x "$bundle_dir/Contents/MacOS/LiveTR3" ]] || { print -u2 'Run build_mtp_candidate.sh first.'; exit 1; }
env PYTHONPATH="$repo_dir/script" "$bundle_dir/Contents/Resources/Engine/venv/bin/python" -c \
  'from chunk_limit_replay import competing_workers; workers=competing_workers(); assert not workers, "Other model inference exists: " + str(workers)'
run_dir="$repo_dir/dist/logs/mtp-user-test-${mode}-$$"
mkdir -p "$run_dir"
exec env LIVETR3_GEMMA_MTP="$enabled" LIVETR3_DIAGNOSTIC_MIN_SILENCE_MS=400 \
  LIVETR3_ENGINE_SOCKET="/tmp/livetr3-mtp-${mode}-$$.sock" \
  LIVETR3_BACKEND_TRACE="$run_dir/backend.jsonl" \
  LIVETR3_ARCHIVE_ROOT="$run_dir/sessions" LIVETR3_RUNTIME_LOG="$run_dir/runtime.log" \
  "$bundle_dir/Contents/MacOS/LiveTR3"
