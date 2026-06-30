-- Materialize valid_until from forgotten events (soft-archive via audit_log)

CREATE TRIGGER audit_materialize_valid_until_forgotten
AFTER INSERT ON audit_log
WHEN NEW.event_type = 'forgotten' AND NEW.node_id IS NOT NULL
BEGIN
  UPDATE nodes
  SET valid_until = json_extract(NEW.payload, '$.valid_until'),
      updated_at  = NEW.ts
  WHERE id = NEW.node_id;
END;
