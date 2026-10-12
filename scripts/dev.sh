#!/usr/bin/env bash
# Developer mode: run JARVIS from this folder. The backend also starts and supervises
# Hermes and the Mac agent. Ctrl+C (or ./scripts/stop.sh) stops everything.
#   ./scripts/dev.sh          → hot-reloading dashboard on http://127.0.0.1:5173
#   ./scripts/dev.sh --built  → built dashboard served by the backend on http://127.0.0.1:8000
set -uo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || { echo "Run ./scripts/setup.sh first"; exit 1; }
mkdir -p data/logs
export PATH="$HOME/.local/bin:$PATH"

PIDS=()
cleanup() {
  trap - EXIT INT TERM
  echo; echo "Shutting down…"
  for p in "${PIDS[@]}"; do kill -TERM "$p" 2>/dev/null || true; done
  wait 2>/dev/null
  rm -f data/dev.pid
  echo "Stopped."
}
echo $$ > data/dev.pid
trap cleanup EXIT
trap "exit 130" INT
trap "exit 143" TERM

.venv/bin/python -m backend.main & PIDS+=($!)
echo "• Backend starting on 127.0.0.1:8000 (it starts Hermes and the Mac agent)"

if [ "${1:-}" = "--built" ]; then
  [ -d frontend/dist ] || (cd frontend && npm run build)
  URL=http://127.0.0.1:8000
else
  (cd frontend && exec ./node_modules/.bin/vite --clearScreen false) & PIDS+=($!)
  URL=http://127.0.0.1:5173
fi

for _ in $(seq 1 40); do curl -fsS http://127.0.0.1:8000/api/status >/dev/null 2>&1 && break; sleep 0.3; done
echo; echo "  JARVIS is up → $URL"; echo "  Press Ctrl+C to stop."; echo
command -v open >/dev/null && open "$URL" 2>/dev/null || true
wait
