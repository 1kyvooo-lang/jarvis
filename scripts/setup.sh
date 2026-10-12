#!/usr/bin/env bash
# Developer setup (run JARVIS from this folder). Most people should double-click
# "Install JARVIS.command" instead, which also installs Hermes and builds JARVIS.app.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf "\033[36m›\033[0m %s\n" "$*"; }
die() { printf "\033[31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || die "Python 3.10+ is required. Install it with: brew install python@3.12"
command -v node >/dev/null || die "Node.js 18+ is required. Install it with: brew install node"
say "Using $($PY --version) and Node $(node --version)"

if [ ! -d .venv ]; then say "Creating virtualenv"; "$PY" -m venv .venv; fi
say "Installing Python packages"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

say "Installing Playwright MCP (browser control)"
(cd mcp-runtime && npm install --silent --no-audit --no-fund)

if command -v hermes >/dev/null || [ -x "$HOME/.local/bin/hermes" ]; then
  say "Making sure Hermes has its API server and MCP support"
  bash scripts/hermes_extras.sh "$(command -v hermes || echo "$HOME/.local/bin/hermes")" || echo "  (couldn't update Hermes — see README)"
else
  echo "  Hermes Agent not found. Install it: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash"
fi

say "Installing and building the dashboard"
(cd frontend && npm install --silent && npm run build --silent)

if [ ! -f .env ]; then
  say "Creating .env with a random agent token"
  TOKEN=$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')
  sed "s/^JARVIS_AGENT_TOKEN=.*/JARVIS_AGENT_TOKEN=$TOKEN/" .env.example > .env
  chmod 600 .env
else
  say ".env already exists — left untouched"
fi

if [ ! -f config/permissions.json ]; then
  cp config/permissions.example.json config/permissions.json
  say "Created config/permissions.json (edit it or use Settings → Permissions)"
else
  say "config/permissions.json already exists — left untouched"
fi

mkdir -p data/logs
if command -v hermes >/dev/null || [ -x "$HOME/.local/bin/hermes" ]; then
  .venv/bin/python -c "import sys; sys.path.insert(0, '.'); from backend import hermes; print('  Hermes config:', hermes.ensure_config()['changed'] or 'already set')"
fi
say "Running tests"
.venv/bin/python -m pytest -q tests || die "Tests failed — see output above"

printf "\n\033[32m✓ Setup complete.\033[0m Start everything with: ./scripts/dev.sh\n"
