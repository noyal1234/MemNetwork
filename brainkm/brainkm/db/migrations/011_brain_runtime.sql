-- Cross-process runtime KV (hooks CLI ↔ long-lived MCP). Used for last_hook_session
-- inference when agents omit session_id.
CREATE TABLE IF NOT EXISTS brain_runtime (
  key TEXT PRIMARY KEY NOT NULL,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
