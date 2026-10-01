#!/bin/zsh
set -euo pipefail
repo_dir=${0:A:h:h}
silence_ms=${1:-400}
case "$silence_ms" in
  150|300|400) ;;
  *) print -u2 'Usage: launch_silence_comparison.sh [150|300|400]'; exit 2 ;;
esac
bundle_dir="$repo_dir/dist/LiveTR3-silence-comparison.app"
[[ -x "$bundle_dir/Contents/MacOS/LiveTR3" ]] || { print -u2 'Build the silence-comparison bundle first.'; exit 1; }
env PYTHONPATH="$repo_dir/script" "$repo_dir/app/backend/.venv/bin/python" -c \
  'from chunk_limit_replay import competing_workers; workers=competing_workers(); assert not workers, "Stop other model inference before launching the test app: " + str(workers)'
run_dir="$repo_dir/dist/logs/silence-user-test-${silence_ms}-$$"
mkdir -p "$run_dir"
exec env LIVETR3_DIAGNOSTIC_MIN_SILENCE_MS="$silence_ms" \
  LIVETR3_ENGINE_SOCKET="/tmp/livetr3-silence-${silence_ms}-$$.sock" \
  LIVETR3_ARCHIVE_ROOT="$run_dir/sessions" LIVETR3_RUNTIME_LOG="$run_dir/runtime.log" \
  "$bundle_dir/Contents/MacOS/LiveTR3"
