-- T1 semantic embeddings + feedback / decay support columns

CREATE TABLE IF NOT EXISTS node_embeddings (
  node_id    TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
  model      TEXT NOT NULL,
  dim        INTEGER NOT NULL,
  embedding  BLOB NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_node_embeddings_model ON node_embeddings(model);

-- Usage feedback: injected vs actually referenced (Phase C)
CREATE TABLE IF NOT EXISTS neuron_feedback (
  node_id         TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
  injected_count  INTEGER NOT NULL DEFAULT 0,
  used_count      INTEGER NOT NULL DEFAULT 0,
  ignored_count   INTEGER NOT NULL DEFAULT 0,
  last_injected   TEXT,
  last_used       TEXT,
  updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_use_count ON nodes(use_count);
CREATE INDEX IF NOT EXISTS idx_nodes_updated_at ON nodes(updated_at);
