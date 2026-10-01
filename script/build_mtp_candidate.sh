#!/bin/zsh
# Build a separate signed test bundle; never launch or stop a running app.
set -euo pipefail
repo_dir=${0:A:h:h}
python_bin=${LIVETR3_MTP_PYTHON:-$repo_dir/app/backend/.venv/bin/python}
[[ -x "$python_bin" ]] || { print -u2 'Set LIVETR3_MTP_PYTHON to the existing backend Python.'; exit 1; }
bundle_dir="$repo_dir/dist/LiveTR3-gemma-mtp.app"
cd "$repo_dir/macos/LiveTR3Mac"
swift build -c release
binary_dir=$(swift build -c release --show-bin-path)
mkdir -p "$bundle_dir/Contents/MacOS" "$bundle_dir/Contents/Resources"
cp "$binary_dir/LiveTR3" "$bundle_dir/Contents/MacOS/LiveTR3"
cp Resources/AppIcon.icns "$bundle_dir/Contents/Resources/AppIcon.icns"
cat > "$bundle_dir/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>LiveTR3</string>
<key>CFBundleIdentifier</key><string>com.livetr3.gemma-mtp</string>
<key>CFBundleName</key><string>LiveTR3 Gemma MTP</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSMicrophoneUsageDescription</key><string>Capture speech for local transcription and translation.</string>
<key>NSPrincipalClass</key><string>NSApplication</string>
</dict></plist>
PLIST
"$repo_dir/script/package_engine.sh" "$bundle_dir"
mkdir -p "$bundle_dir/Contents/Resources/Engine/venv/bin"
# A local test shim uses the existing environment without installing/upgrading it.
# zsh's quoted expansion protects paths that contain shell metacharacters.
print -r -- '#!/bin/zsh' > "$bundle_dir/Contents/Resources/Engine/venv/bin/python"
print -r -- "exec ${(q)python_bin} \"\$@\"" >> "$bundle_dir/Contents/Resources/Engine/venv/bin/python"
chmod +x "$bundle_dir/Contents/Resources/Engine/venv/bin/python"
codesign --force --deep --sign - "$bundle_dir"
codesign --verify --deep --strict "$bundle_dir"
print -r -- "$bundle_dir"
