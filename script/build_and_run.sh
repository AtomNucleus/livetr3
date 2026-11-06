#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The executable and bundle id keep the old LiveTR3 name so settings, sessions and
# the process name used by the check scripts carry over. Users see DISPLAY_NAME.
APP_NAME="LiveTR3"
DISPLAY_NAME="Herald"
PACKAGE_DIR="$ROOT/macos/LiveTR3Mac"
BUNDLE="$ROOT/dist/$DISPLAY_NAME.app"
APP_ICON="$PACKAGE_DIR/Resources/AppIcon.icns"

verify=false
if [[ "${1:-}" == "--verify" ]]; then
  verify=true
fi

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

cd "$PACKAGE_DIR"
swift build -c release

EXECUTABLE="$(swift build -c release --show-bin-path)/$APP_NAME"

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cp "$EXECUTABLE" "$BUNDLE/Contents/MacOS/$APP_NAME"
cp "$APP_ICON" "$BUNDLE/Contents/Resources/AppIcon.icns"
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
  <string>$DISPLAY_NAME</string>
  <key>CFBundleDisplayName</key>
  <string>$DISPLAY_NAME</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>14.0</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>Herald captures microphone audio for local transcription and translation.</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

"$ROOT/script/package_engine.sh" "$BUNDLE"

/usr/bin/open -n "$BUNDLE"

if [[ "$verify" == true ]]; then
  sleep 2
  pgrep -x "$APP_NAME" >/dev/null
  echo "$DISPLAY_NAME is running from $BUNDLE"
fi
