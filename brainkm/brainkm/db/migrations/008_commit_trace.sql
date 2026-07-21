-- Commit-trace: durable sha→session joins reuse nodes(kind='commit').
-- Diffs stay in git; this index makes live git-log joins cheap.

CREATE INDEX IF NOT EXISTS idx_nodes_commit_git_hash
  ON nodes(git_hash)
  WHERE kind = 'commit' AND git_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_nodes_session_kind
  ON nodes(session_id, kind)
  WHERE session_id IS NOT NULL AND valid_until IS NULL;
