#!/usr/bin/env bash
# Build JARVIS.app — a double-clickable app that starts JARVIS (if needed) and opens its window.
#   ./scripts/build_app.sh [destination folder]   (default: /Applications, else ~/Applications)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
[ "$(uname)" = "Darwin" ] || { echo "JARVIS.app can only be built on macOS."; exit 1; }

DEST="${1:-}"
if [ -z "$DEST" ]; then
  if [ -w /Applications ]; then DEST=/Applications; else DEST="$HOME/Applications"; fi
fi
mkdir -p "$DEST"
APP="$DEST/JARVIS.app"
PORT="${JARVIS_BACKEND_PORT:-8000}"

if [ -e "$APP" ]; then
  # Only replace an app we built ourselves.
  if ! grep -q "com.jarvis.app" "$APP/Contents/Info.plist" 2>/dev/null; then
    echo "$APP exists and isn't JARVIS's — leaving it alone."; exit 1
  fi
  rm -rf "$APP"
fi

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp macos/JARVIS.icns "$APP/Contents/Resources/JARVIS.icns"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>JARVIS</string>
  <key>CFBundleDisplayName</key><string>JARVIS</string>
  <key>CFBundleIdentifier</key><string>com.jarvis.app</string>
  <key>CFBundleVersion</key><string>2.0</string>
  <key>CFBundleShortVersionString</key><string>2.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>JARVIS</string>
  <key>CFBundleIconFile</key><string>JARVIS</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>JARVIS listens when you press the microphone button.</string>
</dict>
</plist>
EOF

cat > "$APP/Contents/MacOS/JARVIS" <<EOF
#!/bin/bash
# Starts JARVIS if it isn't running, then opens its window.
ROOT="$ROOT"
URL="http://127.0.0.1:$PORT"
LABEL="com.jarvis.app"
mkdir -p "\$ROOT/data/logs"

if ! curl -fsS "\$URL/api/status" >/dev/null 2>&1; then
  if launchctl print "gui/\$(id -u)/\$LABEL" >/dev/null 2>&1; then
    launchctl kickstart "gui/\$(id -u)/\$LABEL"
  else
    cd "\$ROOT" && nohup "\$ROOT/.venv/bin/python" -m backend.main >> "\$ROOT/data/logs/app.out" 2>&1 &
  fi
  for i in \$(seq 1 80); do curl -fsS "\$URL/api/status" >/dev/null 2>&1 && break; sleep 0.25; done
fi

# Its own window: Chrome in app mode with a separate profile (keeps the mic permission),
# otherwise the default browser.
for B in "/Applications/Google Chrome.app" "\$HOME/Applications/Google Chrome.app" "/Applications/Microsoft Edge.app" "/Applications/Brave Browser.app"; do
  if [ -d "\$B" ]; then
    open -na "\$B" --args --app="\$URL" --user-data-dir="\$ROOT/data/app-window" --window-size=1380,900 \\
      --no-first-run --no-default-browser-check \\
      --autoplay-policy=no-user-gesture-required --disable-background-timer-throttling \\
      --disable-renderer-backgrounding --disable-backgrounding-occluded-windows
    exit 0
  fi
done
open "\$URL"
EOF
chmod +x "$APP/Contents/MacOS/JARVIS"
touch "$APP"
echo "Built $APP"
