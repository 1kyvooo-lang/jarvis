#!/usr/bin/env bash
# Remove JARVIS from this Mac. Hermes Agent itself is left installed (it's yours to keep).
set -uo pipefail
TARGET="$HOME/Library/Application Support/JARVIS"
read -r -p "Remove JARVIS (app, login item, settings, chat history and memory)? [y/N] " a
[ "$a" = "y" ] || [ "$a" = "Y" ] || { echo "Nothing removed."; exit 0; }
curl -fsS -X POST http://127.0.0.1:8000/api/shutdown >/dev/null 2>&1 && sleep 3
launchctl bootout "gui/$(id -u)/com.jarvis.app" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/com.jarvis.agent" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/com.jarvis.menu" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.jarvis.app.plist" "$HOME/Library/LaunchAgents/com.jarvis.agent.plist" "$HOME/Library/LaunchAgents/com.jarvis.menu.plist"
rm -rf /Applications/JARVIS.app "$HOME/Applications/JARVIS.app"
HCONF="${HERMES_HOME:-$HOME/.hermes}/config.yaml"
if [ -f "$HCONF" ] && [ -x "$TARGET/.venv/bin/python" ]; then
  "$TARGET/.venv/bin/python" - "$HCONF" <<'PY'
import sys
from ruamel.yaml import YAML
p = sys.argv[1]; y = YAML(); d = y.load(open(p)) or {}
(d.get("mcp_servers") or {}).pop("jarvis", None)
(d.get("platform_toolsets") or {}).pop("api_server", None)
y.dump(d, open(p, "w")); print("Removed JARVIS entries from", p)
PY
fi
for svc in jarvis-assistant; do
  for k in elevenlabs_api_key; do security delete-generic-password -s "$svc" -a "$k" >/dev/null 2>&1 || true; done
done
rm -rf "$TARGET"
echo "JARVIS removed. (Hermes Agent is still installed; remove it with its own uninstaller if you want.)"
