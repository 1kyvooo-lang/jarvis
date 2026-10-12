#!/usr/bin/env bash
# Make sure Hermes Agent has the optional features JARVIS relies on:
#   messaging → aiohttp, for Hermes's local API server that JARVIS talks to
#   mcp       → connecting to JARVIS's MCP server (Mac tools + Playwright browser)
#   anthropic → Claude models, if you pick Anthropic as Hermes's provider
# First uses Hermes's own package manager (extras are added, nothing removed).
# If that fails, finds Hermes's Python environment and adds Hermes's pinned versions there.
set -uo pipefail

HERMES_BIN="${1:-$(command -v hermes || echo "$HOME/.local/bin/hermes")}"
[ -x "$HERMES_BIN" ] || { echo "Hermes not found at $HERMES_BIN"; exit 1; }
HHOME="${HERMES_HOME:-$HOME/.hermes}"
PINS="aiohttp==3.14.3 mcp==2.0.0 anthropic==0.87.0"
CHECK='import aiohttp, mcp, anthropic'

echo "Adding Hermes features: API server, MCP, Anthropic (this can take a minute)…"
if "$HERMES_BIN" pm install --extra messaging --extra mcp --extra anthropic; then
  echo "Done."
  exit 0
fi

echo "Hermes's package manager didn't finish; adding the packages directly instead…"

# Use Hermes's own pinned versions when its source is present.
SRC="$HHOME/hermes-agent/pyproject.toml"
if [ -f "$SRC" ]; then
  FOUND="$(/usr/bin/python3 - "$SRC" <<'PY' 2>/dev/null
import re, sys
text = open(sys.argv[1]).read()
out = []
for name in ("aiohttp", "mcp", "anthropic"):
    m = re.search(r'"(%s==[0-9][^";\s]*)' % name, text)
    if m:
        out.append(m.group(1))
print(" ".join(out))
PY
)"
  [ -n "$FOUND" ] && PINS="$FOUND"
fi

# Every Python under the Hermes home that has Hermes's core packages is one of its environments.
CANDIDATES=()
while IFS= read -r py; do
  if "$py" -c 'import ruamel.yaml, rich, fire, httpx' >/dev/null 2>&1; then CANDIDATES+=("$py"); fi
done < <(find "$HHOME" -path '*/bin/python3' \( -type f -o -type l \) 2>/dev/null)
[ ${#CANDIDATES[@]} -gt 0 ] || { echo "Couldn't find Hermes's Python environment under $HHOME."; exit 1; }

UV="$(command -v uv || true)"
for c in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do [ -z "$UV" ] && [ -x "$c" ] && UV="$c"; done

ok=1
for py in "${CANDIDATES[@]}"; do
  if "$py" -c "$CHECK" >/dev/null 2>&1; then ok=0; continue; fi
  echo "  → $py"
  if [ -n "$UV" ]; then "$UV" pip install --python "$py" $PINS || continue
  else "$py" -m pip install $PINS || continue; fi
  "$py" -c "$CHECK" && ok=0
done
[ $ok -eq 0 ] && { echo "Done."; exit 0; }
echo "Couldn't add the packages. Run:  $HERMES_BIN pm doctor   and send the output."
exit 1
