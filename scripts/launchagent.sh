#!/usr/bin/env bash
# Start JARVIS at login (backend, which also runs Hermes and the Mac agent): install | uninstall | status
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL=com.jarvis.app
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
[ "$(uname)" = "Darwin" ] || { echo "LaunchAgents are macOS only."; exit 1; }
DOMAIN="gui/$(id -u)"

case "${1:-status}" in
  install)
    if [ -f "$PLIST" ] && ! grep -q "$ROOT" "$PLIST"; then
      read -r -p "$PLIST exists for another JARVIS folder. Replace it? [y/N] " ans
      [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "Left unchanged."; exit 0; }
    fi
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootout "$DOMAIN/com.jarvis.agent" 2>/dev/null || true   # older agent-only job
    rm -f "$HOME/Library/LaunchAgents/com.jarvis.agent.plist"
    mkdir -p "$HOME/Library/LaunchAgents" data/logs
    NODE_DIR="$(dirname "$(command -v node 2>/dev/null || echo /opt/homebrew/bin/node)")"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$ROOT/.venv/bin/python</string><string>-m</string><string>backend.main</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$HOME/.local/bin:$NODE_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$ROOT/data/logs/app.out</string>
  <key>StandardErrorPath</key><string>$ROOT/data/logs/app.out</string>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
EOF
    # If JARVIS is already running outside launchd, stop it so launchd owns it.
    curl -fsS -X POST http://127.0.0.1:${JARVIS_BACKEND_PORT:-8000}/api/shutdown >/dev/null 2>&1 && sleep 3 || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "JARVIS now starts at login (and restarts if it crashes)." ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"; echo "JARVIS will no longer start at login." ;;
  status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state|pid" || echo "Not set to start at login." ;;
  *) echo "usage: $0 install|uninstall|status"; exit 2 ;;
esac
