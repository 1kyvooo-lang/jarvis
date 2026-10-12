"""Runs approved automations when they are due. Each task is claimed atomically
(status queued -> running) so it can never execute twice."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging

from . import agent_client, db

log = logging.getLogger("jarvis.scheduler")


def _due(due_at: str | None) -> bool:
    if not due_at:
        return True
    try:
        d = dt.datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.astimezone()
        return d <= dt.datetime.now(dt.timezone.utc)
    except ValueError:
        return True


async def run_task(task: dict) -> None:
    steps = json.loads(task["steps"] or "[]")
    outputs = []
    ok = True
    for i, step in enumerate(steps):
        if db.get_settings().get("emergency_stop"):
            outputs.append({"step": i, "error": "emergency stop"}); ok = False; break
        res = await agent_client.execute(f"task-{task['id']}-step-{i}", step["tool"], step.get("args", {}),
                                         approved=bool(task["approved"]))
        outputs.append({"step": i, "tool": step["tool"], **{k: res.get(k) for k in ("ok", "output", "error")}})
        db.log_activity(f"Automation '{task['title']}' step {i + 1}: {step['tool']}", "ok" if res.get("ok") else "error",
                        tool=step["tool"], approval="approved", result=res.get("output"), error=res.get("error"),
                        source="automation")
        if not res.get("ok"):
            ok = False
            break
    db.ex("UPDATE tasks SET status=?, result=?, updated_at=? WHERE id=?",
          ("completed" if ok else "failed", json.dumps(outputs, default=str)[:20000], db.now(), task["id"]))


async def tick() -> int:
    if db.get_settings().get("emergency_stop"):
        return 0
    ran = 0
    for t in db.q("SELECT * FROM tasks WHERE status='queued' AND steps IS NOT NULL AND approved=1"):
        if not _due(t["due_at"]):
            continue
        claimed = db.ex("UPDATE tasks SET status='running', updated_at=? WHERE id=? AND status='queued'", (db.now(), t["id"]))
        if claimed.rowcount != 1:
            continue
        try:
            await run_task(t)
        except Exception as e:
            log.exception("task %s failed", t["id"])
            db.ex("UPDATE tasks SET status='failed', result=?, updated_at=? WHERE id=?", (str(e), db.now(), t["id"]))
        ran += 1
    return ran


async def loop(interval: float = 5.0) -> None:
    # Tasks left 'running' by a crash are marked failed rather than silently re-run.
    db.ex("UPDATE tasks SET status='failed', result='Interrupted by a restart' WHERE status='running'")
    while True:
        try:
            await tick()
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)
