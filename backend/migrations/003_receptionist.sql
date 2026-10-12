CREATE TABLE IF NOT EXISTS processed_emails (
  message_id TEXT PRIMARY KEY,
  label TEXT,
  summary TEXT,
  processed_at TEXT NOT NULL
);
ALTER TABLE approvals ADD COLUMN notified INTEGER DEFAULT 0;
