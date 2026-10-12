#!/usr/bin/env bash
# Manage the Mac agent as a background process: start | stop | restart | status | logs
set -euo pipefail
cd "$(dirname "$0")/.."
PIDFILE=data/agent.pid
mkdir -p data/logs

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-status}" in
  start)
    if running; then echo "Agent already running (pid $(cat $PIDFILE))"; exit 0; fi
    if launchctl list 2>/dev/null | grep -q com.jarvis.agent; then
      echo "Agent is managed by the LaunchAgent (launchctl). Use ./scripts/launchagent.sh to control it."; exit 0
    fi
    nohup .venv/bin/python -m agent.server >> data/logs/agent.out 2>&1 &
    for _ in $(seq 1 30); do
      if curl -fsS "http://127.0.0.1:${JARVIS_AGENT_PORT:-8765}/health" >/dev/null 2>&1; then echo "Agent started (pid $(cat $PIDFILE 2>/dev/null || echo ?))"; exit 0; fi
      sleep 0.3
    done
    echo "Agent did not come up — see data/logs/agent.out"; exit 1 ;;
  stop)
    if ! running; then echo "Agent not running"; rm -f "$PIDFILE"; exit 0; fi
    PID=$(cat "$PIDFILE"); kill -TERM "$PID"
    for _ in $(seq 1 30); do kill -0 "$PID" 2>/dev/null || { echo "Agent stopped"; exit 0; }; sleep 0.2; done
    echo "Agent didn't exit in 6s; forcing"; kill -KILL "$PID" 2>/dev/null || true; rm -f "$PIDFILE" ;;
  restart) "$0" stop; "$0" start ;;
  status)
    if running; then echo "Agent running (pid $(cat $PIDFILE))"; else echo "Agent not running"; fi ;;
  logs) tail -n 50 -f data/logs/agent.log ;;
  *) echo "usage: $0 start|stop|restart|status|logs"; exit 2 ;;
esac
