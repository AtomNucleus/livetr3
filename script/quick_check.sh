#!/usr/bin/env bash
# Fast check for each UI edit: the off-limits guard, then Swift unit tests (which
# also compile the whole app). Backend tests run only when app/backend changed.
# Before a PR, run ./script/validate.sh and ./script/ui_perf_check.py instead.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/script/ui_guard.sh"

BASE="$(git -C "$ROOT" merge-base HEAD "${LIVETR3_BASE:-main}")"
if { git -C "$ROOT" diff --name-only "$BASE"; git -C "$ROOT" ls-files --others --exclude-standard; } \
    | grep -q '^app/backend/'; then
  echo "==> Backend tests (app/backend changed)"
  (cd "$ROOT/app/backend" && uv run --extra test pytest -q tests)
fi

echo "==> Swift unit tests"
cd "$ROOT/macos/LiveTR3Mac"
swift test
echo "==> Quick check passed"
