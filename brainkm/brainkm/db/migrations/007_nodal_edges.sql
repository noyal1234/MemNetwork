-- Nodal adopt: edge lookup indexes + optional meta_json for temporal supersede metadata

ALTER TABLE edges ADD COLUMN meta_json TEXT;

CREATE INDEX IF NOT EXISTS idx_edges_rel_to
  ON edges(relationship, to_id);

CREATE INDEX IF NOT EXISTS idx_edges_rel_from
  ON edges(relationship, from_id);

CREATE INDEX IF NOT EXISTS idx_nodes_subtype_valid
  ON nodes(kind, subtype, valid_until);
