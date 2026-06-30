#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="LiveTR3"
PACKAGE_DIR="$ROOT/macos/LiveTR3Mac"
BUNDLE="$ROOT/dist/$APP_NAME.app"

verify=false
if [[ "${1:-}" == "--verify" ]]; then
  verify=true
fi

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

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

stop_repo_process_on_port 8765

cd "$PACKAGE_DIR"
swift build -c debug

EXECUTABLE="$(swift build -c debug --show-bin-path)/$APP_NAME"

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS"
cp "$EXECUTABLE" "$BUNDLE/Contents/MacOS/$APP_NAME"
cat > "$BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>com.livetr3.mac</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>14.0</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>LiveTR3 captures microphone audio for local transcription and translation.</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

/usr/bin/open -n "$BUNDLE"

if [[ "$verify" == true ]]; then
  sleep 2
  pgrep -x "$APP_NAME" >/dev/null
  echo "$APP_NAME is running from $BUNDLE"
fi
