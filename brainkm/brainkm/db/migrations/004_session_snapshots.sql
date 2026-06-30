-- Frozen injection snapshots per Cursor session (SessionStart pack)

CREATE TABLE session_snapshots (
  session_id   TEXT PRIMARY KEY,
  pack_text    TEXT NOT NULL,
  neuron_ids   TEXT NOT NULL,
  token_count  INTEGER NOT NULL,
  frozen       INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL
);

CREATE INDEX idx_session_snapshots_created ON session_snapshots(created_at);
