#!/usr/bin/env bash
# Restart JARVIS's background part cleanly (used by updates and self-repair).
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${JARVIS_BACKEND_PORT:-8000}"
mkdir -p data/logs
if [ "$(uname)" = "Darwin" ] && launchctl print "gui/$(id -u)/com.jarvis.app" >/dev/null 2>&1; then
  exec launchctl kickstart -k "gui/$(id -u)/com.jarvis.app"
fi
curl -fsS -X POST "http://127.0.0.1:$PORT/api/shutdown" >/dev/null 2>&1
for i in $(seq 1 40); do   # wait until the old JARVIS has really let go of its port
  curl -fsS -m 1 "http://127.0.0.1:$PORT/api/status" >/dev/null 2>&1 || break
  sleep 0.5
done
sleep 1
(cd "$ROOT" && exec nohup "$ROOT/.venv/bin/python" -m backend.main >> "$ROOT/data/logs/app.out" 2>&1 < /dev/null) &
