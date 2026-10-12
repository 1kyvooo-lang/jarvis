-- 'agent' approvals are executed by the backend after approval;
-- 'external' approvals (browser actions via Playwright MCP) are executed by the MCP proxy.
ALTER TABLE approvals ADD COLUMN kind TEXT NOT NULL DEFAULT 'agent';
ALTER TABLE approvals ADD COLUMN reason TEXT;
