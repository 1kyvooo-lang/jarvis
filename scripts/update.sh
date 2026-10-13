#!/usr/bin/env bash
# Called by JARVIS's "Update now" button:  update.sh <new source dir> <install dir> <commit sha>
# Copies the new code in (keeping data, keys, settings and permissions), refreshes packages and the dashboard,
# then restarts JARVIS. Everything is logged to data/logs/update.log.
set -uo pipefail
SRC="$1"; TARGET="$2"; SHA="$3"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
fail() { echo "FAILED: $*"; restart; exit 1; }
PORT="${JARVIS_BACKEND_PORT:-8000}"
restart() {
  echo "Restarting JARVIS…"
  bash "$TARGET/scripts/restart.sh"
}

echo "Updating JARVIS to ${SHA:0:7} — $(date)"
sleep 1   # let the dashboard get its reply first
rsync -a --delete \
  --exclude ".venv" --exclude "data" --exclude ".env" --exclude "config/permissions.json" \
  --exclude "frontend/node_modules" --exclude "frontend/dist" --exclude "mcp-runtime/node_modules" \
  "$SRC/" "$TARGET/" || fail "couldn't copy the new code"
cd "$TARGET"
echo "Python packages…"
.venv/bin/pip install --quiet -r requirements.txt || fail "Python packages didn't install"
echo "Dashboard…"
(cd frontend && npm install --silent --no-audit --no-fund && npm run build --silent) || fail "dashboard build failed"
[ "$(uname)" = "Darwin" ] && { bash scripts/build_app.sh >/dev/null || echo "warning: couldn't rebuild JARVIS.app"; }
[ "$(uname)" = "Darwin" ] && { bash scripts/menubar.sh || echo "warning: menu bar icon skipped"; }
echo "Playwright MCP…"
(cd mcp-runtime && npm install --silent --no-audit --no-fund) || echo "warning: Playwright MCP install had problems"
.venv/bin/python -c "import sys; sys.path.insert(0, '.'); from backend import hermes; hermes.ensure_config(); hermes.ensure_env()" \
  || echo "warning: couldn't refresh Hermes config"
echo "$SHA" > data/version
echo "Done."
restart
