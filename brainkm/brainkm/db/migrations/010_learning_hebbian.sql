-- Hebbian learning-loop hardening: episode pending state, decay checkpoint,
-- ignore half-life stamp, atomic inject dedupe, legacy co_activated clamp.
-- Cap must match LearningConfig.co_activation_max_weight default (10.0).

UPDATE edges
SET weight = MIN(weight, 10.0)
WHERE relationship = 'co_activated' AND weight > 10.0;

ALTER TABLE edges ADD COLUMN decayed_at TEXT;

ALTER TABLE neuron_feedback ADD COLUMN last_ignored TEXT;

CREATE TABLE IF NOT EXISTS session_learning_state (
  session_id TEXT PRIMARY KEY,
  pending_node_ids TEXT,
  pending_coact INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

-- Atomic per-session inject dedupe (kind='injected' rows)
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_activity_injected
  ON session_activity(session_id, node_id)
  WHERE kind = 'injected' AND node_id IS NOT NULL;
