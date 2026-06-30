"""SQLite connection, migrations, schema (V1)."""

from brainkm.db.checkpoint import confirm_writes, wal_checkpoint
from brainkm.db.connection import configure_connection, connect, connection
from brainkm.db.integrity import check_fts_integrity
from brainkm.db.migrate import current_schema_version, migrate
from brainkm.db.paths import brain_db_path, brain_dir, migrations_dir

__all__ = [
    "brain_db_path",
    "brain_dir",
    "check_fts_integrity",
    "configure_connection",
    "confirm_writes",
    "connect",
    "connection",
    "current_schema_version",
    "migrate",
    "migrations_dir",
    "wal_checkpoint",
]
