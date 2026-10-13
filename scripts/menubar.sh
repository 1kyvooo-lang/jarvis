#!/usr/bin/env bash
# Builds the JARVIS menu bar icon and starts it at login. Also puts JARVIS in the Dock (once).
# Safe to run again. Needs Apple's command line tools (swiftc), which Homebrew already installed.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
[ "$(uname)" = "Darwin" ] || exit 0
PORT="${JARVIS_BACKEND_PORT:-8000}"
APP="$( [ -d /Applications/JARVIS.app ] && echo /Applications/JARVIS.app || echo "$HOME/Applications/JARVIS.app")"
MENU="$ROOT/data/JARVIS Menu.app"   # data/ survives updates
LABEL=com.jarvis.menu
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

# ---- Dock (only the first time, so removing it from the Dock sticks)
if [ ! -f data/.dock-added ] && [ -d "$APP" ]; then
  if ! defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "JARVIS.app"; then
    defaults write com.apple.dock persistent-apps -array-add "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>" \
      && killall Dock 2>/dev/null
  fi
  mkdir -p data && touch data/.dock-added
fi

# ---- menu bar icon
SWIFTC="$(xcrun -f swiftc 2>/dev/null || command -v swiftc || true)"
if [ -z "$SWIFTC" ]; then
  echo "swiftc not found; skipping the menu bar icon (install Apple's command line tools: xcode-select --install)"
  exit 0
fi
mkdir -p "$MENU/Contents/MacOS"
"$SWIFTC" -O -o "$MENU/Contents/MacOS/JARVISMenu" macos/menubar/main.swift 2>data/logs/menubar-build.log \
  || { echo "menu bar icon didn't build (see data/logs/menubar-build.log)"; exit 0; }
cat > "$MENU/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>JARVIS Menu</string>
  <key>CFBundleIdentifier</key><string>com.jarvis.menu</string>
  <key>CFBundleExecutable</key><string>JARVISMenu</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PL
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$MENU/Contents/MacOS/JARVISMenu</string><string>http://127.0.0.1:$PORT</string><string>$APP</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "Menu bar icon ready"
