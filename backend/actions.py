"""The single gate every tool call passes through: kill switch, allowlist,
approval workflow, execution and activity logging."""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from . import agent_client, db, memory

# ---------------------------------------------------------------- backend-local tools

LOCAL_TOOLS: list[dict] = [
    {"name": "save_memory",
     "description": "Save something the user explicitly asked you to remember (a preference, fact, project, goal or standing instruction). Never save passwords, keys or other secrets.",
     "input_schema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": list(memory.KINDS)},
         "content": {"type": "string", "maxLength": 2000}}, "required": ["kind", "content"]}},
    {"name": "search_memory",
     "description": "Search the user's saved memories by keywords.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 200}}, "required": ["query"]}},
    {"name": "create_task",
     "description": "Create a to-do item in the user's task list (no automatic execution).",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string", "maxLength": 200}, "description": {"type": "string", "maxLength": 2000},
         "due_at": {"type": "string", "description": "ISO 8601 datetime, optional"}}, "required": ["title"]}},
    {"name": "list_tasks",
     "description": "List the user's tasks and automations, optionally filtered by status.",
     "input_schema": {"type": "object", "properties": {"status": {"type": "string"}}}},
    {"name": "update_task_status",
     "description": "Mark a to-do task as done, todo or cancelled.",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["todo", "done", "cancelled"]}},
         "required": ["task_id", "status"]}},
    {"name": "propose_automation",
     "description": "Propose an automation: an ordered list of Mac agent tool steps, optionally scheduled. It is NOT run until the user approves it in the Tasks screen.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string", "maxLength": 200},
         "description": {"type": "string", "maxLength": 2000},
         "steps": {"type": "array", "minItems": 1, "maxItems": 10, "items": {"type": "object", "properties": {
             "tool": {"type": "string"}, "args": {"type": "object"}}, "required": ["tool", "args"]}},
         "run_at": {"type": "string", "description": "ISO 8601 datetime; omit to run right after approval"}},
         "required": ["title", "steps"]}},
]
LOCAL_TOOLS += [
    {"name": "call_me",
     "description": "Phone the user on their own phone (via Twilio) and start a voice conversation. Use when they ask you "
                    "to call them, or to report back by phone when a task finishes. Only their own number can be called.",
     "input_schema": {"type": "object", "properties": {
         "message": {"type": "string", "maxLength": 500, "description": "What to say when they pick up."}}}},
    {"name": "send_sms",
     "description": "Send a text message (SMS) to the user's own phone via Twilio. Only their own number can be texted.",
     "input_schema": {"type": "object", "properties": {"message": {"type": "string", "maxLength": 1600}},
                      "required": ["message"]}},
]
PHONE_TOOLS = {"call_me", "send_sms"}
LOCAL_NAMES = {t["name"] for t in LOCAL_TOOLS}


def _task(tid: int) -> dict | None:
    t = db.one("SELECT * FROM tasks WHERE id=?", (tid,))
    if t and t.get("steps"):
        t["steps"] = json.loads(t["steps"])
    return t


def create_task(title: str, description: str = "", due_at: str | None = None, steps: list | None = None,
                status: str = "todo", source: str = "user") -> dict:
    t = db.now()
    cur = db.ex("INSERT INTO tasks(title, description, status, due_at, steps, source, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (title, description, status, due_at, json.dumps(steps) if steps else None, source, t, t))
    return _task(cur.lastrowid)


async def _run_local(name: str, args: dict) -> Any:
    if name == "save_memory":
        m = memory.create(args["kind"], args["content"], source="assistant")
        db.log_activity(f"Saved memory: {m['content'][:80]}", "ok", tool=name, approval="auto")
        return {"saved": True, "id": m["id"]}
    if name == "search_memory":
        return {"results": [{"id": r["id"], "kind": r["kind"], "content": r["content"]}
                            for r in memory.search(args["query"], limit=15)]}
    if name == "create_task":
        t = create_task(args["title"], args.get("description", ""), args.get("due_at"), source="assistant")
        db.log_activity(f"Created task: {t['title']}", "ok", tool=name, approval="auto")
        return {"created": True, "task_id": t["id"]}
    if name == "list_tasks":
        sql, p = "SELECT id, title, status, due_at FROM tasks", []
        if args.get("status"):
            sql += " WHERE status=?"; p.append(args["status"])
        return {"tasks": db.q(sql + " ORDER BY id DESC LIMIT 50", p)}
    if name == "update_task_status":
        cur = db.ex("UPDATE tasks SET status=?, updated_at=? WHERE id=? AND steps IS NULL",
                    (args["status"], db.now(), args["task_id"]))
        return {"updated": cur.rowcount == 1}
    if name == "propose_automation":
        catalog = await agent_client.tools()
        known = {t["name"] for t in (catalog or {}).get("tools", [])}
        bad = [s["tool"] for s in args["steps"] if s["tool"] not in known]
        if bad:
            raise ValueError(f"Unknown agent tools: {bad}")
        t = create_task(args["title"], args.get("description", ""), args.get("run_at"), args["steps"],
                        status="proposed", source="assistant")
        db.log_activity(f"Proposed automation: {t['title']}", "pending", tool=name, approval="required")
        return {"proposed": True, "task_id": t["id"], "note": "Waiting for the user to approve it in the Tasks screen."}
    if name == "call_me":
        from . import phone
        return await phone.call_owner(args.get("message", ""))
    if name == "send_sms":
        from . import phone
        return await phone.sms_owner(args["message"])
    raise ValueError(f"unknown local tool {name}")


# ---------------------------------------------------------------- tool catalog for Claude

async def claude_tools() -> tuple[list[dict], dict]:
    """Return (tool definitions for Claude, metadata by name)."""
    from . import phone
    phone_on = phone.configured()
    defs = [dict(t) for t in LOCAL_TOOLS if phone_on or t["name"] not in PHONE_TOOLS]
    meta: dict[str, dict] = {t["name"]: {"local": True, "requires_approval": False} for t in LOCAL_TOOLS}
    catalog = await agent_client.tools()
    if catalog and not db.get_settings().get("emergency_stop"):
        for t in catalog["tools"]:
            if not t["enabled"]:
                continue
            desc = t["description"]
            if t["requires_approval"]:
                desc += " (Requires the user's approval in the dashboard before it runs.)"
            defs.append({"name": t["name"], "description": desc, "input_schema": t["input_schema"]})
            meta[t["name"]] = {"local": False, **t}
    return defs, meta


def describe_call(tool: str, args: dict) -> str:
    a = ", ".join(f"{k}={json.dumps(v)[:120]}" for k, v in args.items())
    return f"{tool}({a})"


# ---------------------------------------------------------------- the gate

async def wait_for_decision(approval_id: int, timeout: float) -> dict:
    """Block until the user approves/denies in the dashboard (or the timeout expires)."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        row = db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if row and row["status"] not in ("pending", "approved"):
            return row
        if row and row["status"] == "approved" and row["kind"] == "external":
            return row
        await asyncio.sleep(0.4)
    db.ex("UPDATE approvals SET status='expired', decided_at=? WHERE id=? AND status='pending'", (db.now(), approval_id))
    db.log_activity(f"Approval #{approval_id} expired", "denied", approval="expired")
    return db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))


def create_approval(tool: str, args: dict, *, kind: str, conversation_id: str | None, reason: str = "",
                    source: str = "assistant") -> int:
    summary = describe_call(tool, args)
    cur = db.ex("INSERT INTO approvals(conversation_id, tool, args, summary, status, created_at, kind, reason) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (conversation_id, tool, json.dumps(args), summary, "pending", db.now(), kind, reason))
    db.log_activity(f"Approval requested: {summary}" + (f" — {reason}" if reason else ""), "pending", tool=tool,
                    approval="required", source=source)
    return cur.lastrowid


async def run_tool(tool: str, args: dict, *, conversation_id: str | None = None,
                   user_initiated: bool = False, source: str = "assistant", wait: float = 0) -> dict:
    """Returns {status: ok|error|pending_approval, output?, error?, approval_id?}.

    With wait > 0, a tool that needs approval blocks until the user decides (used by
    Hermes via MCP, so the agent simply gets the result once you click Approve)."""
    if db.get_settings().get("emergency_stop"):
        db.log_activity(f"Blocked {tool} (emergency stop)", "error", tool=tool, error="emergency stop", source=source)
        return {"status": "error", "error": "Emergency stop is active — no actions will run until it is released."}

    if tool in LOCAL_NAMES:
        try:
            return {"status": "ok", "output": await _run_local(tool, args)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    catalog = await agent_client.tools(force=True)
    if catalog is None:
        db.log_activity(f"{tool} failed — agent offline", "error", tool=tool, error="agent offline", source=source)
        return {"status": "error", "error": "The Mac agent is offline. Start it with ./scripts/agent.sh start"}
    info = next((t for t in catalog["tools"] if t["name"] == tool), None)
    if not info:
        return {"status": "error", "error": f"Unknown tool {tool}"}
    if not info["enabled"]:
        return {"status": "error", "error": f"Tool {tool} is disabled in permissions"}

    summary = describe_call(tool, args)
    if info["requires_approval"] and not user_initiated:
        aid = create_approval(tool, args, kind="blocking" if wait else "agent", conversation_id=conversation_id,
                              reason="needs your approval", source=source)
        if not wait:
            return {"status": "pending_approval", "approval_id": aid}
        row = await wait_for_decision(aid, wait)
        if row["status"] == "executed":
            return {"status": "ok", "output": json.loads(row["result"] or "null"), "approval_id": aid}
        if row["status"] == "failed":
            return {"status": "error", "error": (json.loads(row["result"] or "{}") or {}).get("error", "failed"), "approval_id": aid}
        if row["status"] == "denied":
            return {"status": "error", "error": "The user denied this action. Don't retry it unless they ask.", "approval_id": aid}
        return {"status": "error", "error": f"Nobody approved this within {int(wait)}s, so it did not run. "
                "Tell the user it's waiting for approval and ask them to approve, then try again.", "approval_id": aid}

    res = await agent_client.execute(uuid.uuid4().hex, tool, args, approved=user_initiated)
    approval = "user-initiated" if user_initiated else "auto"
    if res.get("ok"):
        db.log_activity(summary, "ok", tool=tool, approval=approval, result=res.get("output"), source=source)
        return {"status": "ok", "output": res.get("output")}
    db.log_activity(summary, "error", tool=tool, approval=approval, error=res.get("error"), source=source)
    return {"status": "error", "error": res.get("error")}


def add_event(conversation_id: str, payload: dict, text: str) -> None:
    db.ex("INSERT INTO messages(conversation_id, role, content, text, created_at) VALUES (?,?,?,?,?)",
          (conversation_id, "event", json.dumps(payload), text, db.now()))


async def decide_approval(approval_id: int, approve: bool) -> dict:
    new = "approved" if approve else "denied"
    cur = db.ex("UPDATE approvals SET status=?, decided_at=? WHERE id=? AND status='pending'",
                (new, db.now(), approval_id))
    if cur.rowcount != 1:  # already decided — prevents double execution
        raise ValueError("Approval is not pending (already decided?)")
    ap = db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
    args = json.loads(ap["args"])

    if ap["task_id"]:  # approving an automation re-queues it
        if approve:
            db.ex("UPDATE tasks SET approved=1, status='queued', updated_at=? WHERE id=?", (db.now(), ap["task_id"]))
        else:
            db.ex("UPDATE tasks SET status='cancelled', updated_at=? WHERE id=?", (db.now(), ap["task_id"]))
        db.ex("UPDATE approvals SET status=? WHERE id=?", ("executed" if approve else "denied", approval_id))
        db.log_activity(f"Automation {'approved' if approve else 'denied'}: {ap['summary']}", "info",
                        tool="automation", approval=new, source="user")
        return db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))

    if ap["kind"] == "external":  # the MCP proxy runs it; we only record the decision
        db.log_activity(f"{'Approved' if approve else 'Denied'}: {ap['summary']}", "info" if approve else "denied",
                        tool=ap["tool"], approval=new, source="user")
        return db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))

    notify_chat = ap["conversation_id"] and ap["kind"] == "agent"  # blocking calls return to Hermes directly
    if not approve:
        db.log_activity(f"Denied: {ap['summary']}", "denied", tool=ap["tool"], approval="denied", source="user")
        if notify_chat:
            add_event(ap["conversation_id"], {"type": "approval", "id": approval_id, "status": "denied",
                                              "tool": ap["tool"]}, f"User denied: {ap['summary']}")
        return db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))

    if db.get_settings().get("emergency_stop"):
        res = {"ok": False, "error": "Emergency stop is active"}
    else:
        res = await agent_client.execute(f"approval-{approval_id}", ap["tool"], args, approved=True)
    status = "executed" if res.get("ok") else "failed"
    out = res.get("output") if res.get("ok") else {"error": res.get("error")}
    db.ex("UPDATE approvals SET status=?, result=? WHERE id=?", (status, json.dumps(out, default=str)[:20000], approval_id))
    db.log_activity(ap["summary"], "ok" if res.get("ok") else "error", tool=ap["tool"], approval="approved",
                    result=res.get("output"), error=res.get("error"), source="user")
    if notify_chat:
        text = f"Approved action {ap['summary']} → " + ("succeeded" if res.get("ok") else f"failed: {res.get('error')}")
        add_event(ap["conversation_id"], {"type": "approval", "id": approval_id, "status": status, "tool": ap["tool"],
                                          "output": out}, text)
    return db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
