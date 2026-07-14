-- Cross-process session activity / learning signals (hooks run as subprocesses)

CREATE TABLE IF NOT EXISTS session_activity (
  id          TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL,
  kind        TEXT NOT NULL,  -- 'neuron_hit' | 'tool_use'
  node_id     TEXT,           -- set for neuron_hit
  tool_name   TEXT,           -- set for tool_use; '__recall__' for neuron hits
  source      TEXT,           -- optional provenance (session_start, recall, pre_tool, ...)
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_activity_session
  ON session_activity(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_session_activity_session_kind
  ON session_activity(session_id, kind);
