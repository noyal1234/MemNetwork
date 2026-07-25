-- Dual-store compressed views + sticky session engine cohort + compression event log

CREATE TABLE IF NOT EXISTS compression_views (
  neuron_id       TEXT NOT NULL,
  body_hash       TEXT NOT NULL,
  engine_version  TEXT NOT NULL,
  intensity       TEXT NOT NULL,
  compressed_text TEXT NOT NULL,
  tokens_in       INTEGER NOT NULL,
  tokens_out      INTEGER NOT NULL,
  created_at      TEXT NOT NULL,
  PRIMARY KEY (neuron_id, body_hash, engine_version, intensity)
);

CREATE INDEX IF NOT EXISTS idx_compression_views_neuron
  ON compression_views(neuron_id);

CREATE TABLE IF NOT EXISTS session_compression_cohort (
  session_id      TEXT PRIMARY KEY,
  engine_version  TEXT NOT NULL,
  canary          INTEGER NOT NULL DEFAULT 0,
  assigned_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compression_events (
  id                TEXT PRIMARY KEY,
  session_id        TEXT,
  surface           TEXT NOT NULL,
  composition_mode  TEXT NOT NULL,
  engine_id         TEXT NOT NULL,
  tokens_in         INTEGER NOT NULL,
  tokens_out        INTEGER NOT NULL,
  skipped_reason    TEXT,
  latency_ms        REAL,
  created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_compression_events_session
  ON compression_events(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_compression_events_surface
  ON compression_events(surface, created_at);
