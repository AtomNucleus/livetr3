#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/app/backend"
FRONTEND_DIR="$ROOT/app/frontend"

mode="${1:-quick}"

stop_repo_process_on_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -n "$pids" ]] || return 0

  while read -r pid; do
    [[ -n "$pid" ]] || continue
    local command
    command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command" == *"$ROOT"* ]] || [[ "$command" == *"server:app --host 127.0.0.1 --port 8765"* ]]; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done <<< "$pids"
}

prepare_live_ports() {
  stop_repo_process_on_port 8765
  stop_repo_process_on_port 5173
  sleep 1
}

run_backend_import_gate() {
  cd "$BACKEND_DIR"
  PYTHONPATH=. uv run python scripts/check_imports.py
  PYTHONPATH=. uv run python -m py_compile \
    mlx_worker.py \
    session.py \
    parakeet_worker.py \
    protocol.py \
    server.py
}

run_frontend_build() {
  cd "$FRONTEND_DIR"
  yarn build
}

run_projector_smoke() {
  prepare_live_ports
  cd "$FRONTEND_DIR"
  yarn test:projector
}

run_short_soak() {
  cd "$BACKEND_DIR"
  PYTHONPATH=. uv run python scripts/soak.py \
    --duration-seconds 90 \
    --metric-interval-seconds 10 \
    --drain-seconds 15 \
    --no-polish
}

run_fault_soak() {
  cd "$BACKEND_DIR"
  PYTHONPATH=. uv run python scripts/soak.py \
    --duration-seconds 180 \
    --metric-interval-seconds 15 \
    --drain-seconds 20 \
    --inject-fault \
    --fault-at-seconds 75 \
    --no-polish
}

case "$mode" in
  quick)
    run_backend_import_gate
    run_frontend_build
    run_projector_smoke
    ;;
  soak)
    run_short_soak
    ;;
  full)
    run_backend_import_gate
    run_frontend_build
    run_projector_smoke
    run_fault_soak
    ;;
  *)
    echo "Usage: $0 [quick|soak|full]" >&2
    exit 2
    ;;
esac

echo "LiveTR3 known-good validation passed: $mode"
