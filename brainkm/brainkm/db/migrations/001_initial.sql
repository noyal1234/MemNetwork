-- MemNetwork V1 initial schema

CREATE TABLE IF NOT EXISTS schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE nodes (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,
  subtype      TEXT,
  title        TEXT NOT NULL,
  content      TEXT,
  path         TEXT,
  tags         TEXT,
  source       TEXT,
  git_hash     TEXT,
  git_branch   TEXT,
  confidence   REAL DEFAULT 1.0,
  use_count    INTEGER DEFAULT 0,
  token_count  INTEGER,
  user_pinned  INTEGER DEFAULT 0,
  valid_from   TEXT,
  valid_until  TEXT,
  ingested_at  TEXT NOT NULL,
  session_id   TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE VIRTUAL TABLE nodes_fts USING fts5(
  title, content, tags,
  content=nodes, content_rowid=rowid,
  tokenize='porter unicode61'
);

CREATE TABLE edges (
  id            TEXT PRIMARY KEY,
  from_id       TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  to_id         TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  relationship  TEXT NOT NULL,
  weight        REAL DEFAULT 1.0,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_edges_active
  ON edges(from_id, to_id, relationship);

CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type  TEXT NOT NULL,
  node_id     TEXT,
  edge_id     TEXT,
  payload     TEXT,
  ts          TEXT NOT NULL,
  CHECK (
    (node_id IS NOT NULL AND edge_id IS NULL) OR
    (node_id IS NULL AND edge_id IS NOT NULL) OR
    (event_type = 'distilled_from' AND node_id IS NOT NULL)
  )
);

CREATE TABLE graph_import_runs (
  id            TEXT PRIMARY KEY,
  started_at    TEXT NOT NULL,
  completed_at  TEXT,
  status        TEXT NOT NULL,
  node_count    INTEGER,
  edge_count    INTEGER
);

CREATE TABLE session_chunks (
  id          TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL,
  role        TEXT,
  content     TEXT NOT NULL,
  ts          TEXT NOT NULL
);

CREATE VIRTUAL TABLE session_fts USING fts5(
  content, content=session_chunks, content_rowid=rowid
);

CREATE TABLE chunk_sources (
  chunk_id    TEXT NOT NULL REFERENCES session_chunks(id) ON DELETE CASCADE,
  neuron_id   TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  distill_ts  TEXT NOT NULL,
  PRIMARY KEY (chunk_id, neuron_id)
);

CREATE TABLE ingested_sessions (
  session_id    TEXT PRIMARY KEY,
  fingerprint   TEXT NOT NULL UNIQUE,
  distill_mode  TEXT NOT NULL,
  neuron_count  INTEGER,
  ingested_at   TEXT NOT NULL
);

CREATE INDEX idx_session_chunks_session ON session_chunks(session_id, ts);
CREATE INDEX idx_audit_node_ts ON audit_log(node_id, ts);
CREATE INDEX idx_nodes_kind_valid ON nodes(kind, valid_until);
CREATE INDEX idx_nodes_kind_pinned ON nodes(kind, user_pinned);
CREATE INDEX idx_chunk_sources_neuron ON chunk_sources(neuron_id);

CREATE TRIGGER nodes_fts_insert AFTER INSERT ON nodes BEGIN
  INSERT INTO nodes_fts(rowid, title, content, tags)
  VALUES (new.rowid, new.title, new.content, new.tags);
END;

CREATE TRIGGER nodes_fts_update AFTER UPDATE ON nodes BEGIN
  INSERT INTO nodes_fts(nodes_fts, rowid, title, content, tags)
  VALUES ('delete', old.rowid, old.title, old.content, old.tags);
  INSERT INTO nodes_fts(rowid, title, content, tags)
  VALUES (new.rowid, new.title, new.content, new.tags);
END;

CREATE TRIGGER nodes_fts_delete AFTER DELETE ON nodes BEGIN
  INSERT INTO nodes_fts(nodes_fts, rowid, title, content, tags)
  VALUES ('delete', old.rowid, old.title, old.content, old.tags);
END;

CREATE TRIGGER session_fts_insert AFTER INSERT ON session_chunks BEGIN
  INSERT INTO session_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER session_fts_delete AFTER DELETE ON session_chunks BEGIN
  INSERT INTO session_fts(session_fts, rowid, content)
  VALUES ('delete', old.rowid, old.content);
END;
