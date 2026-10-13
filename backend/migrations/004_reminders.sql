CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  due_at TEXT NOT NULL,
  via TEXT NOT NULL DEFAULT 'text',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  sent_at TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders(status, due_at);
