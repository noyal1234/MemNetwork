-- Per-tool success/failure counters. tool_registry (nodes kind='tool') only
-- stores name+description; PostToolUseFailure records an observation but
-- nothing previously landed on the tool node itself, so there was no way to
-- ask "has this tool been failing lately". Mirrors neuron_feedback's shape.
CREATE TABLE IF NOT EXISTS tool_feedback (
  tool_name       TEXT PRIMARY KEY NOT NULL,
  success_count   INTEGER NOT NULL DEFAULT 0,
  failure_count   INTEGER NOT NULL DEFAULT 0,
  last_success    TEXT,
  last_failure    TEXT,
  updated_at      TEXT NOT NULL
);
