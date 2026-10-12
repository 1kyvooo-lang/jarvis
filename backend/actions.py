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
LOCAL_TOOLS += [
    {"name": "text_message",
     "description": "Send an SMS to someone other than the user (via the user's Twilio number). Always waits for the user's approval; "
                    "say who it's to and what it says. For texting the user themself, use send_sms.",
     "input_schema": {"type": "object", "properties": {
         "to": {"type": "string", "description": "Phone number in international format, e.g. +39 333 1234567"},
         "message": {"type": "string", "maxLength": 1600}}, "required": ["to", "message"]}},
]
GOOGLE_TOOLS_DEFS = [
    {"name": "email_search",
     "description": "Search the user's Gmail. Uses Gmail search syntax, e.g. 'in:inbox is:unread', 'from:anna newer_than:7d', "
                    "'subject:invoice'. Returns sender, subject, date and a snippet for each message.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "maxLength": 300}, "max_results": {"type": "integer", "minimum": 1, "maximum": 25}}}},
    {"name": "email_read",
     "description": "Read one email in full (from email_search results).",
     "input_schema": {"type": "object", "properties": {"message_id": {"type": "string"}}, "required": ["message_id"]}},
    {"name": "email_organize",
     "description": "Sort email: add or remove Gmail labels (created if missing), archive (remove from inbox), mark read/unread. "
                    "Use for tidying the inbox, e.g. label newsletters and archive them. Cannot delete mail.",
     "input_schema": {"type": "object", "properties": {
         "message_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 100},
         "add_labels": {"type": "array", "items": {"type": "string"}},
         "remove_labels": {"type": "array", "items": {"type": "string"}},
         "archive": {"type": "boolean"}, "mark_read": {"type": "boolean"}}, "required": ["message_ids"]}},
    {"name": "email_send",
     "description": "Send an email from the user's Gmail, or reply to one (pass reply_to_message_id to keep the thread). "
                    "Always waits for the user's approval before sending.",
     "input_schema": {"type": "object", "properties": {
         "to": {"type": "string"}, "subject": {"type": "string", "maxLength": 300},
         "body": {"type": "string", "maxLength": 20000}, "cc": {"type": "string"},
         "reply_to_message_id": {"type": "string"}}, "required": ["to", "body"]}},
    {"name": "calendar_events",
     "description": "List events on the user's Google Calendar between two times (ISO 8601). Defaults to the next 24 hours.",
     "input_schema": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}}},
    {"name": "calendar_free_slots",
     "description": "Find free appointment slots within the user's working hours, skipping anything already booked.",
     "input_schema": {"type": "object", "properties": {
         "from_date": {"type": "string", "description": "YYYY-MM-DD, default today"},
         "days": {"type": "integer", "minimum": 1, "maximum": 21},
         "duration_minutes": {"type": "integer", "minimum": 10, "maximum": 240}}}},
    {"name": "calendar_book",
     "description": "Create an event / appointment on the user's Google Calendar. If attendee_email is given, Google emails "
                    "them an invitation, so that needs the user's approval first.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string", "maxLength": 200}, "start": {"type": "string", "description": "ISO 8601"},
         "end": {"type": "string"}, "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 600},
         "description": {"type": "string", "maxLength": 4000}, "location": {"type": "string"},
         "attendee_email": {"type": "string"}}, "required": ["title", "start"]}},
]
LOCAL_TOOLS += GOOGLE_TOOLS_DEFS
GOOGLE_TOOLS = {t["name"] for t in GOOGLE_TOOLS_DEFS}
PHONE_TOOLS = {"call_me", "send_sms", "text_message"}


def needs_approval(name: str, args: dict) -> bool:
    """Backend tools that send something to another person always ask first."""
    if name in ("email_send", "text_message"):
        return True
    return name == "calendar_book" and bool(args.get("attendee_email"))
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
    if name == "text_message":
        from . import phone
        return await phone.sms_to(args["to"], args["message"])
    if name in GOOGLE_TOOLS:
        from . import google
        if name == "email_search":
            return {"messages": await google.search(args.get("query") or "in:inbox", args.get("max_results", 10))}
        if name == "email_read":
            return await google.read(args["message_id"])
        if name == "email_organize":
            r = await google.organize(args["message_ids"], args.get("add_labels"), args.get("remove_labels"),
                                      bool(args.get("archive")), args.get("mark_read"))
            db.log_activity(f"Sorted {r['updated']} email(s)", "ok", tool=name, approval="auto", result=r)
            return r
        if name == "email_send":
            r = await google.send(args["to"], args.get("subject", ""), args["body"], args.get("reply_to_message_id"),
                                  args.get("cc", ""))
            db.log_activity(f"Email sent to {r['to']}: {r['subject']}", "ok", tool=name, result=r)
            return r
        if name == "calendar_events":
            return await google.events(args.get("start"), args.get("end"))
        if name == "calendar_free_slots":
            return await google.free_slots(args.get("from_date"), args.get("days", 5), args.get("duration_minutes", 30))
        if name == "calendar_book":
            r = await google.create_event(args["title"], args["start"], args.get("end"), args.get("description", ""),
                                          args.get("attendee_email"), args.get("duration_minutes", 30), args.get("location", ""))
            db.log_activity(f"Booked: {r['title']} at {r['start']}", "ok", tool=name, result=r)
            return r
    raise ValueError(f"unknown local tool {name}")


# ---------------------------------------------------------------- tool catalog for Claude

async def claude_tools() -> tuple[list[dict], dict]:
    """Return (tool definitions for Claude, metadata by name)."""
    from . import phone
    phone_on = phone.configured()
    from . import google
    google_on = google.connected()
    defs = [dict(t) for t in LOCAL_TOOLS
            if (phone_on or t["name"] not in PHONE_TOOLS) and (google_on or t["name"] not in GOOGLE_TOOLS)]
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
    if kind == "agent" and tool in ("email_send", "text_message"):
        try:   # also text the owner so they can answer YES/NO from their phone
            from . import phone
            asyncio.get_running_loop().create_task(phone.notify_approval(cur.lastrowid))
        except RuntimeError:
            pass
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
        if needs_approval(tool, args) and not user_initiated:
            aid = create_approval(tool, args, kind="blocking" if wait else "agent", conversation_id=conversation_id,
                                  reason="sends a message to someone", source=source)
            if not wait:
                return {"status": "pending_approval", "approval_id": aid,
                        "note": "Waiting for the user's approval; it will be sent once they approve."}
            return _approval_result(await wait_for_decision(aid, wait), aid, wait)
        try:
            return {"status": "ok", "output": await _run_local(tool, args)}
        except Exception as e:
            db.log_activity(f"{tool} failed", "error", tool=tool, error=str(e)[:300], source=source)
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
        return _approval_result(await wait_for_decision(aid, wait), aid, wait)

    res = await agent_client.execute(uuid.uuid4().hex, tool, args, approved=user_initiated)
    approval = "user-initiated" if user_initiated else "auto"
    if res.get("ok"):
        db.log_activity(summary, "ok", tool=tool, approval=approval, result=res.get("output"), source=source)
        return {"status": "ok", "output": res.get("output")}
    db.log_activity(summary, "error", tool=tool, approval=approval, error=res.get("error"), source=source)
    return {"status": "error", "error": res.get("error")}


def _approval_result(row: dict, aid: int, wait: float) -> dict:
    if row["status"] == "executed":
        return {"status": "ok", "output": json.loads(row["result"] or "null"), "approval_id": aid}
    if row["status"] == "failed":
        return {"status": "error", "error": (json.loads(row["result"] or "{}") or {}).get("error", "failed"), "approval_id": aid}
    if row["status"] == "denied":
        return {"status": "error", "error": "The user denied this action. Don't retry it unless they ask.", "approval_id": aid}
    return {"status": "error", "error": f"Nobody approved this within {int(wait)}s, so it did not run. "
            "Tell the user it's waiting for approval and ask them to approve, then try again.", "approval_id": aid}


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
    elif ap["tool"] in LOCAL_NAMES:
        try:
            res = {"ok": True, "output": await _run_local(ap["tool"], args)}
        except Exception as e:
            res = {"ok": False, "error": str(e)}
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
