#!/usr/bin/env bash
# Install or update JARVIS straight from GitHub, no zip needed:
#   bash <(curl -fsSL https://raw.githubusercontent.com/1kyvooo-lang/jarvis/main/scripts/get.sh)
set -euo pipefail
REPO="${JARVIS_UPDATE_REPO:-1kyvooo-lang/jarvis}"
echo "Downloading the latest JARVIS…"
SHA="$(curl -fsSL "https://api.github.com/repos/$REPO/commits/main" | grep -m1 '"sha"' | cut -d'"' -f4)"
[ -n "$SHA" ] || { echo "Couldn't reach GitHub. Check your internet and try again."; exit 1; }
TMP="$(mktemp -d)"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$SHA" | tar -xz -C "$TMP"
cd "$TMP"/*/
echo "$SHA" > .release
bash scripts/install_mac.sh < /dev/tty
