"""brainkm viz — local HTTP server for the 3D neuron graph visualization."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from brainkm.logging_config import get_logger

logger = get_logger("viz")

_STATIC_DIR = Path(__file__).resolve().parent / "viz_static"

# ---------------------------------------------------------------------------
# Demo seed data
# ---------------------------------------------------------------------------

_DEMO_NODES: list[dict[str, Any]] = [
    # --- memory neurons ---
    {
        "id": "mem-001", "kind": "memory", "subtype": "decision",
        "title": "Why we chose SQLite over PostgreSQL",
        "content": "PostgreSQL adds ops overhead for a single-developer local brain. SQLite with WAL mode is ACID-safe, zero-config, and ships with Python. We get FTS5 and vec extensions for free. Revisit if we ever need multi-user concurrent writes.",
        "tags": "architecture,database,decision", "use_count": 14, "confidence": 0.97,
        "user_pinned": 1, "valid_from": "2025-01-10T10:00:00", "valid_until": None,
        "ingested_at": "2025-01-10T10:00:00", "session_id": "sess-alpha",
        "created_at": "2025-01-10T10:00:00", "updated_at": "2025-01-10T10:00:00",
    },
    {
        "id": "mem-002", "kind": "memory", "subtype": "pivot",
        "title": "Dropped LLM self-paging — using rule-based distill",
        "content": "MemGPT-style LLM-managed paging costs one LLM call per page-in. We reject this for the zero-LLM-default principle. Rule-based extraction at SessionEnd/PreCompact is sufficient for V1.",
        "tags": "architecture,llm,compaction,pivot", "use_count": 9, "confidence": 0.95,
        "user_pinned": 0, "valid_from": "2025-01-15T14:30:00", "valid_until": None,
        "ingested_at": "2025-01-15T14:30:00", "session_id": "sess-alpha",
        "created_at": "2025-01-15T14:30:00", "updated_at": "2025-01-15T14:30:00",
    },
    {
        "id": "mem-003", "kind": "memory", "subtype": "rule",
        "title": "1500-token hard cap on injection packs",
        "content": "Token budget for SessionStart injection is 1500 tokens max. This preserves Cursor prefix cache and keeps agent context minimal. The budget splits: 800 neurons + 500 code + 200 procedures.",
        "tags": "tokens,budget,injection,rule", "use_count": 21, "confidence": 1.0,
        "user_pinned": 1, "valid_from": "2025-01-12T09:00:00", "valid_until": None,
        "ingested_at": "2025-01-12T09:00:00", "session_id": "sess-beta",
        "created_at": "2025-01-12T09:00:00", "updated_at": "2025-03-01T12:00:00",
    },
    {
        "id": "mem-004", "kind": "memory", "subtype": "error",
        "title": "FTS5 trigger race on bulk insert",
        "content": "Inserting >500 nodes in one transaction caused FTS5 sync lag. Fix: batch inserts with explicit COMMIT every 100 rows, then rebuild FTS5 with INSERT INTO nodes_fts(nodes_fts) VALUES ('rebuild').",
        "tags": "bug,fts5,performance,sqlite", "use_count": 5, "confidence": 0.92,
        "user_pinned": 0, "valid_from": "2025-02-20T16:00:00", "valid_until": None,
        "ingested_at": "2025-02-20T16:00:00", "session_id": "sess-gamma",
        "created_at": "2025-02-20T16:00:00", "updated_at": "2025-02-20T16:00:00",
    },
    {
        "id": "mem-005", "kind": "memory", "subtype": "decision",
        "title": "MCP stdio over HTTP for Cursor integration",
        "content": "Cursor MCP client connects over stdio, not HTTP. We use the MCP Python SDK stdio transport. This avoids port conflicts and matches the Cursor extension model.",
        "tags": "mcp,cursor,transport,decision", "use_count": 7, "confidence": 0.98,
        "user_pinned": 0, "valid_from": "2025-01-08T11:00:00", "valid_until": None,
        "ingested_at": "2025-01-08T11:00:00", "session_id": "sess-alpha",
        "created_at": "2025-01-08T11:00:00", "updated_at": "2025-01-08T11:00:00",
    },
    {
        "id": "mem-006", "kind": "memory", "subtype": "fact",
        "title": "PreCompact handover survives Cursor chat compaction",
        "content": "Three-layer defence: (1) SessionEnd continuous capture, (2) PreCompact handover writes neurons before Cursor compacts, (3) SessionStart injection restores frozen snapshot. DMR benchmark shows 93.4% recall vs 35.3% for lossy summarize.",
        "tags": "compaction,handover,recall,architecture", "use_count": 18, "confidence": 0.99,
        "user_pinned": 1, "valid_from": "2025-02-01T08:00:00", "valid_until": None,
        "ingested_at": "2025-02-01T08:00:00", "session_id": "sess-beta",
        "created_at": "2025-02-01T08:00:00", "updated_at": "2025-02-01T08:00:00",
    },
    # --- code neurons ---
    {
        "id": "code-001", "kind": "code", "subtype": "module",
        "title": "brainkm/services/memory.py",
        "content": "Core memory service: remember(), recall(), forget(). Implements FTS5 BM25 search + 2-hop graph activation. Enforces token budget via BudgetService.",
        "tags": "service,memory,fts5", "use_count": 31, "confidence": 1.0,
        "user_pinned": 0, "valid_from": "2025-01-05T00:00:00", "valid_until": None,
        "ingested_at": "2025-01-05T00:00:00", "session_id": None,
        "created_at": "2025-01-05T00:00:00", "updated_at": "2025-03-10T09:00:00",
    },
    {
        "id": "code-002", "kind": "code", "subtype": "module",
        "title": "brainkm/db/connection.py",
        "content": "SQLite connection factory. Applies PRAGMA foreign_keys, WAL mode, busy_timeout=10s. Row factory set to sqlite3.Row for dict-like access.",
        "tags": "db,sqlite,connection,pragma", "use_count": 44, "confidence": 1.0,
        "user_pinned": 0, "valid_from": "2025-01-05T00:00:00", "valid_until": None,
        "ingested_at": "2025-01-05T00:00:00", "session_id": None,
        "created_at": "2025-01-05T00:00:00", "updated_at": "2025-01-05T00:00:00",
    },
    {
        "id": "code-003", "kind": "code", "subtype": "module",
        "title": "brainkm/tools/remember.py",
        "content": "MCP tool handler for `remember`. Validates RememberRequest Pydantic model, calls MemoryService.store(), auto-links path mentions to code nodes.",
        "tags": "mcp,tool,remember", "use_count": 26, "confidence": 1.0,
        "user_pinned": 0, "valid_from": "2025-01-10T00:00:00", "valid_until": None,
        "ingested_at": "2025-01-10T00:00:00", "session_id": None,
        "created_at": "2025-01-10T00:00:00", "updated_at": "2025-02-15T14:00:00",
    },
    {
        "id": "code-004", "kind": "code", "subtype": "module",
        "title": "brainkm/services/search.py",
        "content": "FTS5 BM25 retrieval + 2-hop graph activation. Returns ranked ResultSet with BM25 scores, deduplicates by node id, enforces min_recall_score abstention threshold.",
        "tags": "search,fts5,bm25,graph", "use_count": 38, "confidence": 1.0,
        "user_pinned": 0, "valid_from": "2025-01-18T00:00:00", "valid_until": None,
        "ingested_at": "2025-01-18T00:00:00", "session_id": None,
        "created_at": "2025-01-18T00:00:00", "updated_at": "2025-03-05T11:00:00",
    },
    {
        "id": "code-005", "kind": "code", "subtype": "module",
        "title": "brainkm/adapters/graphify.py",
        "content": "Graphify AST graph importer. Reads graph.json, upserts code nodes and import/call edges into brain.db. Filters to code-only nodes by default.",
        "tags": "adapter,graphify,ast,import", "use_count": 12, "confidence": 1.0,
        "user_pinned": 0, "valid_from": "2025-02-10T00:00:00", "valid_until": None,
        "ingested_at": "2025-02-10T00:00:00", "session_id": None,
        "created_at": "2025-02-10T00:00:00", "updated_at": "2025-02-10T00:00:00",
    },
    # --- procedure neurons ---
    {
        "id": "proc-001", "kind": "procedure", "subtype": "tool_chain",
        "title": "Repair FTS5 index after schema change",
        "content": "1. Run `brainkm repair --project-dir .` 2. Verify with `brainkm bench run abstention`. FTS5 triggers auto-rebuild; if counts mismatch, manually run INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild').",
        "tags": "procedure,repair,fts5,maintenance", "use_count": 3, "confidence": 0.88,
        "user_pinned": 0, "valid_from": "2025-03-01T00:00:00", "valid_until": None,
        "ingested_at": "2025-03-01T00:00:00", "session_id": "sess-delta",
        "created_at": "2025-03-01T00:00:00", "updated_at": "2025-03-01T00:00:00",
    },
    {
        "id": "proc-002", "kind": "procedure", "subtype": "tool_chain",
        "title": "Add a new MCP tool (V1 pattern)",
        "content": "1. Create tools/<name>.py with handler function. 2. Add Pydantic I/O models to models/schemas.py. 3. Register in server.py. 4. Add service method in services/. 5. Write pytest test in tests/tools/. Follow layer rule: tool → service → adapter → db.",
        "tags": "procedure,mcp,tool,development", "use_count": 6, "confidence": 0.93,
        "user_pinned": 0, "valid_from": "2025-02-05T00:00:00", "valid_until": None,
        "ingested_at": "2025-02-05T00:00:00", "session_id": "sess-beta",
        "created_at": "2025-02-05T00:00:00", "updated_at": "2025-02-05T00:00:00",
    },
    # --- session neurons ---
    {
        "id": "sess-n-001", "kind": "session", "subtype": "context",
        "title": "Session alpha — initial scaffold",
        "content": "Set up V0 scaffold. Created AGENTS.md, BrainConfig Pydantic model, pyproject.toml, initial migration 001_initial.sql. SQLite WAL mode enabled. Decision: use Typer for CLI over Click.",
        "tags": "session,scaffold,v0", "use_count": 2, "confidence": 0.85,
        "user_pinned": 0, "valid_from": "2025-01-05T00:00:00", "valid_until": None,
        "ingested_at": "2025-01-05T00:00:00", "session_id": "sess-alpha",
        "created_at": "2025-01-05T00:00:00", "updated_at": "2025-01-05T00:00:00",
    },
    {
        "id": "sess-n-002", "kind": "session", "subtype": "context",
        "title": "Session gamma — abstention calibration",
        "content": "Implemented adaptive abstention: BM25 threshold calibrated from bench fixtures. Abstain mode returns empty list when top score < min_recall_score. Calibration stored in brain.db config table.",
        "tags": "session,abstention,calibration,bench", "use_count": 4, "confidence": 0.9,
        "user_pinned": 0, "valid_from": "2025-02-18T00:00:00", "valid_until": None,
        "ingested_at": "2025-02-18T00:00:00", "session_id": "sess-gamma",
        "created_at": "2025-02-18T00:00:00", "updated_at": "2025-02-18T00:00:00",
    },
    # --- archived neuron ---
    {
        "id": "mem-arch-001", "kind": "memory", "subtype": "decision",
        "title": "[ARCHIVED] Used HTTP transport for MCP (superseded)",
        "content": "Originally considered HTTP transport for MCP server. Superseded by stdio transport decision (mem-005). HTTP port conflicts with other Cursor extensions.",
        "tags": "mcp,transport,archived", "use_count": 1, "confidence": 0.5,
        "user_pinned": 0, "valid_from": "2025-01-06T00:00:00", "valid_until": "2025-01-08T11:00:00",
        "ingested_at": "2025-01-06T00:00:00", "session_id": "sess-alpha",
        "created_at": "2025-01-06T00:00:00", "updated_at": "2025-01-08T11:00:00",
    },
]

_DEMO_EDGES: list[dict[str, Any]] = [
    # architecture decisions ↔ code they influenced
    {"from_id": "mem-001", "to_id": "code-002", "relationship": "influences", "weight": 0.9},
    {"from_id": "mem-002", "to_id": "mem-006", "relationship": "supports", "weight": 0.8},
    {"from_id": "mem-003", "to_id": "code-001", "relationship": "constrains", "weight": 0.95},
    {"from_id": "mem-003", "to_id": "code-003", "relationship": "constrains", "weight": 0.9},
    {"from_id": "mem-004", "to_id": "code-002", "relationship": "related_to", "weight": 0.7},
    {"from_id": "mem-004", "to_id": "proc-001", "relationship": "spawned", "weight": 0.85},
    {"from_id": "mem-005", "to_id": "code-003", "relationship": "influences", "weight": 0.88},
    {"from_id": "mem-006", "to_id": "mem-003", "relationship": "related_to", "weight": 0.75},
    # code nodes — import/call edges
    {"from_id": "code-003", "to_id": "code-001", "relationship": "calls", "weight": 1.0},
    {"from_id": "code-001", "to_id": "code-004", "relationship": "calls", "weight": 1.0},
    {"from_id": "code-001", "to_id": "code-002", "relationship": "imports", "weight": 1.0},
    {"from_id": "code-004", "to_id": "code-002", "relationship": "imports", "weight": 1.0},
    {"from_id": "code-005", "to_id": "code-002", "relationship": "imports", "weight": 0.9},
    # procedures ↔ knowledge
    {"from_id": "proc-001", "to_id": "code-002", "relationship": "targets", "weight": 0.8},
    {"from_id": "proc-002", "to_id": "code-003", "relationship": "targets", "weight": 0.85},
    {"from_id": "proc-002", "to_id": "code-001", "relationship": "targets", "weight": 0.8},
    # sessions ↔ neurons they produced
    {"from_id": "sess-n-001", "to_id": "mem-001", "relationship": "produced", "weight": 0.7},
    {"from_id": "sess-n-001", "to_id": "mem-005", "relationship": "produced", "weight": 0.7},
    {"from_id": "sess-n-002", "to_id": "mem-004", "relationship": "produced", "weight": 0.75},
    # supersedes chain
    {"from_id": "mem-005", "to_id": "mem-arch-001", "relationship": "supersedes", "weight": 1.0},
]


def _seed_demo(conn: sqlite3.Connection) -> None:
    """Insert synthetic demo neurons and edges into an in-memory DB."""
    for n in _DEMO_NODES:
        conn.execute(
            """INSERT OR IGNORE INTO nodes
               (id, kind, subtype, title, content, tags, use_count, confidence,
                user_pinned, valid_from, valid_until, ingested_at, session_id,
                created_at, updated_at)
               VALUES (:id,:kind,:subtype,:title,:content,:tags,:use_count,:confidence,
                       :user_pinned,:valid_from,:valid_until,:ingested_at,:session_id,
                       :created_at,:updated_at)""",
            n,
        )
    for e in _DEMO_EDGES:
        edge_id = str(uuid.uuid4())
        conn.execute(
            """INSERT OR IGNORE INTO edges
               (id, from_id, to_id, relationship, weight, created_at, updated_at)
               VALUES (?,?,?,?,?,datetime('now'),datetime('now'))""",
            (edge_id, e["from_id"], e["to_id"], e["relationship"], e["weight"]),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Graph query
# ---------------------------------------------------------------------------

def _query_graph(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return all active nodes and their edges as a JSON-serialisable dict."""
    cur = conn.execute(
        """SELECT id, kind, subtype, title, content, tags, use_count, confidence,
                  user_pinned, valid_from, valid_until, ingested_at, session_id,
                  created_at, updated_at
           FROM nodes
           ORDER BY use_count DESC"""
    )
    nodes = [dict(row) for row in cur.fetchall()]

    # Build set of node ids for edge filtering
    node_ids = {n["id"] for n in nodes}

    cur = conn.execute(
        "SELECT from_id, to_id, relationship, weight FROM edges"
    )
    edges = [
        dict(row) for row in cur.fetchall()
        if row["from_id"] in node_ids and row["to_id"] in node_ids
    ]

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _VizHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler: serves /api/graph JSON and / static HTML."""

    graph_data: dict[str, Any] = {}

    def log_message(self, fmt: str, *args: object) -> None:  # type: ignore[override]
        logger.debug(fmt, *args)

    def _send_json(self, data: dict | list, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/graph":
            self._send_json(self.__class__.graph_data)
        elif self.path in ("/", "/index.html"):
            html_path = _STATIC_DIR / "index.html"
            if html_path.exists():
                self._send_html(html_path)
            else:
                self._send_json({"error": "index.html not found"}, 404)
        else:
            self._send_json({"error": "not found"}, 404)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_viz_server(
    project_dir: Path | None = None,
    port: int = 5757,
    open_browser: bool = True,
    demo: bool = False,
) -> None:
    """Start the brainkm viz HTTP server and optionally open the browser."""
    import sqlite3 as _sqlite3

    from brainkm.db.connection import configure_connection
    from brainkm.db.paths import brain_db_path

    if demo:
        # Use an in-memory database seeded with synthetic demo data.
        # migrate() always opens its own file connection, so we apply SQL directly.
        from brainkm.db.paths import migrations_dir

        conn = _sqlite3.connect(":memory:", check_same_thread=False)
        configure_connection(conn)
        for sql_path in sorted(migrations_dir().glob("*.sql")):
            conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.commit()
        _seed_demo(conn)
        logger.info("viz demo mode: seeded %d nodes, %d edges", len(_DEMO_NODES), len(_DEMO_EDGES))
    else:
        db_path = brain_db_path(project_dir)
        if not db_path.exists():
            import typer
            typer.echo(
                f"No brain.db found at {db_path}.\n"
                "Run 'brainkm install' first, or use --demo to see a demo visualization.",
                err=True,
            )
            raise typer.Exit(code=1)
        conn = _sqlite3.connect(str(db_path), check_same_thread=False)
        configure_connection(conn)

    graph = _query_graph(conn)
    conn.close()

    _VizHandler.graph_data = graph

    node_count = len(graph["nodes"])
    edge_count = len(graph["edges"])

    server = HTTPServer(("127.0.0.1", port), _VizHandler)
    url = f"http://127.0.0.1:{port}"

    import typer
    mode_label = " [DEMO]" if demo else ""
    typer.echo(
        f"🧠 MemNetwork Viz{mode_label} — {node_count} neurons, {edge_count} edges\n"
        f"   Serving at {url}\n"
        f"   Press Ctrl+C to stop."
    )

    if open_browser:
        def _open_after_delay() -> None:
            time.sleep(0.4)
            webbrowser.open(url)

        threading.Thread(target=_open_after_delay, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nViz server stopped.")
    finally:
        server.server_close()
