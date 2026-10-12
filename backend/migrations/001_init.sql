-- Portable SQL (SQLite now, PostgreSQL later: swap INTEGER PRIMARY KEY AUTOINCREMENT -> BIGSERIAL,
-- TEXT JSON columns -> JSONB, and the FTS table -> a tsvector index).
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT 'New conversation',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,            -- user | assistant | event
  content TEXT NOT NULL,         -- JSON: list of Claude content blocks (or event payload)
  text TEXT NOT NULL DEFAULT '', -- plain text for display/search
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,            -- preference | fact | project | goal | instruction
  content TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'user',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'todo', -- todo|proposed|queued|awaiting_approval|running|completed|failed|cancelled|done
  due_at TEXT,
  steps TEXT,                    -- JSON list of {tool,args} for automations; NULL = plain to-do
  result TEXT,
  source TEXT NOT NULL DEFAULT 'user',
  approved INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT,
  task_id INTEGER,
  tool TEXT NOT NULL,
  args TEXT NOT NULL,
  summary TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', -- pending|approved|denied|executed|failed
  result TEXT,
  created_at TEXT NOT NULL,
  decided_at TEXT
);

CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  action TEXT NOT NULL,
  tool TEXT,
  status TEXT NOT NULL,          -- ok | error | pending | denied | info
  approval TEXT,                 -- auto | required | approved | denied | user-initiated
  result TEXT,
  error TEXT,
  source TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(id DESC);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
