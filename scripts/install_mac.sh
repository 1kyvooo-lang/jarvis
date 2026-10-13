#!/usr/bin/env bash
# JARVIS installer for macOS. Safe to run again (it repairs and updates).
#
#  1. Copies JARVIS to ~/Library/Application Support/JARVIS (so you can delete the download)
#  2. Installs what's missing: Homebrew, Python 3.12, Node, uv
#  3. Installs Hermes Agent (official installer) and the two Hermes features JARVIS needs
#  4. Lets you choose Hermes's AI model (Nous Portal, OpenRouter, …)
#  5. Installs JARVIS, the dashboard and Playwright MCP
#  6. Builds JARVIS.app and (optionally) starts JARVIS at login
#
# Nothing is overwritten silently: your Hermes config is backed up before JARVIS adds its entries.
set -uo pipefail

BOLD=$'\033[1m'; CYAN=$'\033[36m'; GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; OFF=$'\033[0m'
step() { printf "\n${CYAN}${BOLD}▸ %s${OFF}\n" "$*"; }
ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
note() { printf "  ${DIM}%s${OFF}\n" "$*"; }
die()  { printf "\n${RED}✗ %s${OFF}\n\nThe log above shows what happened. You can re-run the installer any time.\n" "$*"; read -r -p "Press Enter to close…" _; exit 1; }
ask()  { local a; read -r -p "  $1 [Y/n] " a; [ -z "$a" ] || [ "$a" = "y" ] || [ "$a" = "Y" ]; }

[ "$(uname)" = "Darwin" ] || die "This installer is for macOS."
SRC="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$HOME/Library/Application Support/JARVIS"

clear
printf "${BOLD}JARVIS installer${OFF}\n${DIM}Hermes Agent brain · ElevenLabs voice · Playwright browser · Mac control with your approval${OFF}\n"

# ------------------------------------------------------------------ 1. location
step "Putting JARVIS in its home folder"
if [ "$SRC" != "$TARGET" ]; then
  mkdir -p "$TARGET"
  # Copy code; keep the target's data/, .env, permissions and installed dependencies.
  rsync -a --delete \
    --exclude ".venv" --exclude "data" --exclude ".env" --exclude "config/permissions.json" \
    --exclude "frontend/node_modules" --exclude "frontend/dist" --exclude "mcp-runtime/node_modules" \
    "$SRC/" "$TARGET/" || die "Couldn't copy JARVIS to $TARGET"
  ok "Copied to $TARGET"
else
  ok "Already in $TARGET"
fi
cd "$TARGET"
xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null || true

# ------------------------------------------------------------------ 2. tools
step "Checking developer tools"
BREW="$(command -v brew || true)"
[ -z "$BREW" ] && [ -x /opt/homebrew/bin/brew ] && BREW=/opt/homebrew/bin/brew
[ -z "$BREW" ] && [ -x /usr/local/bin/brew ] && BREW=/usr/local/bin/brew
if [ -z "$BREW" ]; then
  note "Homebrew (the standard Mac package manager) is needed for Python and Node."
  ask "Install Homebrew now? It will ask for your Mac password." || die "Homebrew is required. Install it from https://brew.sh and run this again."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || die "Homebrew install failed"
  BREW="$(ls /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | head -1)"
fi
eval "$("$BREW" shellenv)"
ok "Homebrew"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then brew install python@3.12 || die "Couldn't install Python"; PY="$(brew --prefix)/bin/python3.12"; fi
ok "Python ($("$PY" --version 2>&1))"
command -v node >/dev/null || brew install node || die "Couldn't install Node.js"
ok "Node ($(node --version))"
command -v uv >/dev/null || [ -x "$HOME/.local/bin/uv" ] || brew install uv || die "Couldn't install uv"
ok "uv"
command -v cloudflared >/dev/null || brew install cloudflared || note "cloudflared didn't install; the phone line (Twilio) won't work until it does."
command -v cloudflared >/dev/null && ok "cloudflared (secure tunnel for the phone line)"

# ------------------------------------------------------------------ 3. Hermes
step "Hermes Agent (the brain)"
export PATH="$HOME/.local/bin:$PATH"
HERMES="$(command -v hermes || true)"
if [ -z "$HERMES" ]; then
  note "Hermes Agent by Nous Research is open source and runs on your Mac."
  ask "Install Hermes Agent with its official installer?" || die "JARVIS needs Hermes Agent."
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash || die "Hermes install failed"
  export PATH="$HOME/.local/bin:$PATH"
  HERMES="$(command -v hermes || echo "$HOME/.local/bin/hermes")"
  [ -x "$HERMES" ] || die "Hermes installed but the 'hermes' command wasn't found"
fi
ok "Hermes at $HERMES"
bash scripts/hermes_extras.sh "$HERMES" || die "Couldn't add the API-server and MCP features to Hermes"
ok "Hermes API server + MCP support"

# ------------------------------------------------------------------ 4. Hermes model
step "Hermes's AI model"
HCONF="${HERMES_HOME:-$HOME/.hermes}/config.yaml"
CURRENT_MODEL="$("$PY" - "$HCONF" <<'PY' 2>/dev/null
import re, sys
try:
    text = open(sys.argv[1]).read()
except OSError:
    sys.exit()
m = re.search(r"^model:\s*\n((?:[ \t]+.*\n?)*)", text, re.M)
block = m.group(1) if m else ""
v = re.search(r"^[ \t]+(?:default|model):[ \t]*['\"]?([^'\"\s#]+)", block, re.M)
if not v:
    v = re.search(r"^model:[ \t]*['\"]?([^'\"\s#]+)", text, re.M)
print(v.group(1) if v else "")
PY
)"
if [ -n "$CURRENT_MODEL" ]; then
  ok "Already set up ($CURRENT_MODEL)"
  if ask "Keep it? (choose n to pick a different model)"; then :; else "$HERMES" model; fi
else
  note "Pick a provider and model. Nous Portal or OpenRouter both work; Hermes will sign you in."
  "$HERMES" model || die "Model setup didn't finish. Run '$HERMES model' and then this installer again."
fi

# ------------------------------------------------------------------ 5. JARVIS
step "Installing JARVIS"
[ -d .venv ] || "$PY" -m venv .venv || die "Couldn't create Python environment"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt || die "Python packages failed to install"
ok "JARVIS backend"
(cd frontend && npm install --silent --no-audit --no-fund && npm run build --silent) >/dev/null 2>&1 || die "Dashboard build failed"
ok "Dashboard"
(cd mcp-runtime && npm install --silent --no-audit --no-fund) >/dev/null 2>&1 || die "Playwright MCP install failed"
if [ ! -d "/Applications/Google Chrome.app" ]; then
  note "Google Chrome not found — downloading a browser for JARVIS to use…"
  mcp-runtime/node_modules/.bin/playwright install chromium || note "Browser download failed; browser tools will report it."
fi
ok "Playwright MCP (browser control)"

if [ ! -f .env ]; then
  TOKEN=$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')
  sed "s/^JARVIS_AGENT_TOKEN=.*/JARVIS_AGENT_TOKEN=$TOKEN/" .env.example > .env && chmod 600 .env
fi
[ -f config/permissions.json ] || cp config/permissions.example.json config/permissions.json
mkdir -p data/logs
[ -f "$SRC/.release" ] && cp "$SRC/.release" data/version   # lets the Update button know which version this is
.venv/bin/python -c "import sys; sys.path.insert(0, '.'); from backend import hermes; r = hermes.ensure_config(); e = hermes.ensure_env(); print('  Hermes config:', ', '.join(r['changed'] + e) or 'already set', '(backup: config.yaml.before-jarvis)')" \
  || die "Couldn't update Hermes's config"
.venv/bin/python -m pytest -q tests >/dev/null 2>&1 && ok "Self-tests passed" || note "Some self-tests failed — JARVIS may still work; see 'tests' in the README."

# ------------------------------------------------------------------ 6. app
step "Creating JARVIS.app"
bash scripts/build_app.sh || die "Couldn't build JARVIS.app"
APP="$( [ -d /Applications/JARVIS.app ] && echo /Applications/JARVIS.app || echo "$HOME/Applications/JARVIS.app")"
ok "$APP"

if ask "Start JARVIS automatically when you log in? (recommended)"; then
  bash scripts/launchagent.sh install >/dev/null && ok "Starts at login"
fi

bash scripts/menubar.sh >/dev/null 2>&1 && ok "Menu bar icon and Dock" || note "Menu bar icon skipped"

step "Opening JARVIS"
open "$APP"
printf "\n${GREEN}${BOLD}JARVIS is installed.${OFF} Open it from the Dock, the menu bar icon, or Spotlight (Cmd+Space → JARVIS).\n"
printf "${DIM}First launch: add your ElevenLabs key on the setup screen, and allow the microphone when asked.${OFF}\n\n"
read -r -p "Press Enter to close this window…" _
