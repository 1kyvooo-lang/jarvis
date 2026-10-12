#!/usr/bin/env bash
# Stop everything started by ./scripts/dev.sh (from another terminal), plus a standalone agent.
set -uo pipefail
cd "$(dirname "$0")/.."
if [ -f data/dev.pid ] && kill -0 "$(cat data/dev.pid)" 2>/dev/null; then
  kill -TERM "$(cat data/dev.pid)"
  for _ in $(seq 1 30); do kill -0 "$(cat data/dev.pid 2>/dev/null)" 2>/dev/null || break; sleep 0.2; done
  echo "JARVIS stopped."
else
  echo "dev.sh is not running."
fi
./scripts/agent.sh stop >/dev/null 2>&1 || true
