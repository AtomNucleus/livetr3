#!/usr/bin/env bash
# Fails when a branch touches the engine, tuning or protocol files that CLAUDE.md
# puts off limits for UI work. Checks committed and uncommitted changes against main.
# Set LIVETR3_ENGINE_CHANGE_OK=1 only when the user asked for an engine change by name.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE="$(git merge-base HEAD "${LIVETR3_BASE:-main}")"
CHANGED="$( { git diff --name-only "$BASE"; git ls-files --others --exclude-standard; } | sort -u)"

hits=()
while IFS= read -r path; do
  case "$path" in
    app/backend/*) hits+=("$path (engine)") ;;
    */BundledEngineConfiguration.swift) hits+=("$path (engine environment)") ;;
    */LocalEngineConnection.swift) hits+=("$path (socket protocol)") ;;
  esac
done <<< "$CHANGED"

# LiveTR3Protocol.swift also holds UI-facing types, so only flag lines that touch
# ClientConfig tuning fields or the message shapes' coding keys.
PROTO="macos/LiveTR3Mac/Sources/LiveTR3Mac/LiveTR3Protocol.swift"
if grep -qx "$PROTO" <<< "$CHANGED"; then
  if git diff "$BASE" -- "$PROTO" | grep -E '^[+-][^+-]' \
      | grep -qE 'partial_interval|max_utterance|silero|speech_pad|min_silence|early_commit|stability_window|CodingKeys|case [a-z_]+ = "'; then
    hits+=("$PROTO (tuning fields or message shapes)")
  fi
fi

if (( ${#hits[@]} )); then
  echo "UI guard: these changes are off limits for UI work (see CLAUDE.md):"
  printf '  - %s\n' "${hits[@]}"
  if [[ "${LIVETR3_ENGINE_CHANGE_OK:-0}" == "1" ]]; then
    echo "LIVETR3_ENGINE_CHANGE_OK=1 is set; continuing. Run the replay scoreboard too."
    exit 0
  fi
  echo "Stop and ask the user, or set LIVETR3_ENGINE_CHANGE_OK=1 if they asked for it."
  exit 1
fi
echo "UI guard: no engine, tuning or protocol files changed."
