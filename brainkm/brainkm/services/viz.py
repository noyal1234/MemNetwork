"""brainkm viz — local HTTP server for the 3D neuron graph visualization."""

from __future__ import annotations

import json
import mimetypes
import sqlite3
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

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
        "path": None, "source": "demo",
    },
    {
        "id": "mem-002", "kind": "memory", "subtype": "pivot",
        "title": "Dropped LLM self-paging — using rule-based distill",
        "content": "MemGPT-style LLM-managed paging costs one LLM call per page-in. We reject this for the zero-LLM-default principle. Rule-based extraction at SessionEnd/PreCompact is sufficient for V1.",
        "tags": "architecture,llm,compaction,pivot", "use_count": 9, "confidence": 0.95,
        "user_pinned": 0, "valid_from": "2025-01-15T14:30:00", "valid_until": None,
        "ingested_at": "2025-01-15T14:30:00", "session_id": "sess-alpha",
        "created_at": "2025-01-15T14:30:00", "updated_at": "2025-01-15T14:30:00",
        "path": None, "source": "demo",
    },
    {
        "id": "mem-003", "kind": "memory", "subtype": "rule",
        "title": "1500-token hard cap on injection packs",
        "content": (
            "Token budget for MCP context_pack is 1500 tokens max (configurable). "
            "Slots reallocate by query type; PreToolUse and SessionStart use smaller sub-budgets."
        ),
        "tags": "tokens,budget,injection,rule", "use_count": 21, "confidence": 1.0,
        "user_pinned": 1, "valid_from": "2025-01-12T09:00:00", "valid_until": None,
        "ingested_at": "2025-01-12T09:00:00", "session_id": "sess-beta",
        "created_at": "2025-01-12T09:00:00", "updated_at": "2025-03-01T12:00:00",
        "path": None, "source": "demo",
    },
    {
        "id": "mem-004", "kind": "memory", "subtype": "error",
        "title": "FTS5 trigger race on bulk insert",
        "content": "Inserting >500 nodes in one transaction caused FTS5 sync lag. Fix: batch inserts with explicit COMMIT every 100 rows, then rebuild FTS5 with INSERT INTO nodes_fts(nodes_fts) VALUES ('rebuild').",
        "tags": "bug,fts5,performance,sqlite", "use_count": 5, "confidence": 0.92,
        "user_pinned": 0, "valid_from": "2025-02-20T16:00:00", "valid_until": None,
        "ingested_at": "2025-02-20T16:00:00", "session_id": "sess-gamma",
        "created_at": "2025-02-20T16:00:00", "updated_at": "2025-02-20T16:00:00",
        "path": None, "source": "demo",
    },
    {
        "id": "mem-005", "kind": "memory", "subtype": "decision",
        "title": "MCP stdio over HTTP for Cursor integration",
        "content": "Cursor MCP client connects over stdio, not HTTP. We use the MCP Python SDK stdio transport. This avoids port conflicts and matches the Cursor extension model.",
        "tags": "mcp,cursor,transport,decision", "use_count": 7, "confidence": 0.98,
        "user_pinned": 0, "valid_from": "2025-01-08T11:00:00", "valid_until": None,
        "ingested_at": "2025-01-08T11:00:00", "session_id": "sess-alpha",
        "created_at": "2025-01-08T11:00:00", "updated_at": "2025-01-08T11:00:00",
        "path": None, "source": "demo",
    },
    {
        "id": "mem-006", "kind": "memory", "subtype": "fact",
        "title": "PreCompact handover survives Cursor chat compaction",
        "content": "Three-layer defence: (1) SessionEnd continuous capture, (2) PreCompact handover writes neurons before Cursor compacts, (3) SessionStart injection restores frozen snapshot. DMR benchmark shows 93.4% recall vs 35.3% for lossy summarize.",
        "tags": "compaction,handover,recall,architecture", "use_count": 18, "confidence": 0.99,
        "user_pinned": 1, "valid_from": "2025-02-01T08:00:00", "valid_until": None,
        "ingested_at": "2025-02-01T08:00:00", "session_id": "sess-beta",
        "created_at": "2025-02-01T08:00:00", "updated_at": "2025-02-01T08:00:00",
        "path": None, "source": "demo",
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
        "path": "brainkm/brainkm/services/memory.py", "source": "graphify",
    },
    {
        "id": "code-002", "kind": "code", "subtype": "module",
        "title": "brainkm/db/connection.py",
        "content": "SQLite connection factory. Applies PRAGMA foreign_keys, WAL mode, busy_timeout=10s. Row factory set to sqlite3.Row for dict-like access.",
        "tags": "db,sqlite,connection,pragma", "use_count": 44, "confidence": 1.0,
        "user_pinned": 0, "valid_from": "2025-01-05T00:00:00", "valid_until": None,
        "ingested_at": "2025-01-05T00:00:00", "session_id": None,
        "created_at": "2025-01-05T00:00:00", "updated_at": "2025-01-05T00:00:00",
        "path": "brainkm/brainkm/db/connection.py", "source": "graphify",
    },
    {
        "id": "code-003", "kind": "code", "subtype": "module",
        "title": "brainkm/tools/remember.py",
        "content": "MCP tool handler for `remember`. Validates RememberRequest Pydantic model, calls MemoryService.store(), auto-links path mentions to code nodes.",
        "tags": "mcp,tool,remember", "use_count": 26, "confidence": 1.0,
        "user_pinned": 0, "valid_from": "2025-01-10T00:00:00", "valid_until": None,
        "ingested_at": "2025-01-10T00:00:00", "session_id": None,
        "created_at": "2025-01-10T00:00:00", "updated_at": "2025-02-15T14:00:00",
        "path": "brainkm/brainkm/tools/remember.py", "source": "graphify",
    },
    {
        "id": "code-004", "kind": "code", "subtype": "module",
        "title": "brainkm/services/search.py",
        "content": "FTS5 BM25 retrieval + 2-hop graph activation. Returns ranked ResultSet with BM25 scores, deduplicates by node id, enforces min_recall_score abstention threshold.",
        "tags": "search,fts5,bm25,graph", "use_count": 38, "confidence": 1.0,
        "user_pinned": 0, "valid_from": "2025-01-18T00:00:00", "valid_until": None,
        "ingested_at": "2025-01-18T00:00:00", "session_id": None,
        "created_at": "2025-01-18T00:00:00", "updated_at": "2025-03-05T11:00:00",
        "path": "brainkm/brainkm/services/search.py", "source": "graphify",
    },
    {
        "id": "code-005", "kind": "code", "subtype": "module",
        "title": "brainkm/adapters/graphify.py",
        "content": "Graphify AST graph importer. Reads graph.json, upserts code nodes and import/call edges into brain.db. Filters to code-only nodes by default.",
        "tags": "adapter,graphify,ast,import", "use_count": 12, "confidence": 1.0,
        "user_pinned": 0, "valid_from": "2025-02-10T00:00:00", "valid_until": None,
        "ingested_at": "2025-02-10T00:00:00", "session_id": None,
        "created_at": "2025-02-10T00:00:00", "updated_at": "2025-02-10T00:00:00",
        "path": "brainkm/brainkm/adapters/graphify.py", "source": "graphify",
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
        "path": None, "source": "demo",
    },
    {
        "id": "proc-002", "kind": "procedure", "subtype": "tool_chain",
        "title": "Add a new MCP tool (V1 pattern)",
        "content": "1. Create tools/<name>.py with handler function. 2. Add Pydantic I/O models to models/schemas.py. 3. Register in server.py. 4. Add service method in services/. 5. Write pytest test in tests/tools/. Follow layer rule: tool → service → adapter → db.",
        "tags": "procedure,mcp,tool,development", "use_count": 6, "confidence": 0.93,
        "user_pinned": 0, "valid_from": "2025-02-05T00:00:00", "valid_until": None,
        "ingested_at": "2025-02-05T00:00:00", "session_id": "sess-beta",
        "created_at": "2025-02-05T00:00:00", "updated_at": "2025-02-05T00:00:00",
        "path": None, "source": "demo",
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
        "path": None, "source": "demo",
    },
    {
        "id": "sess-n-002", "kind": "session", "subtype": "context",
        "title": "Session gamma — abstention calibration",
        "content": "Implemented adaptive abstention: BM25 threshold calibrated from bench fixtures. Abstain mode returns empty list when top score < min_recall_score. Calibration stored in brain.db config table.",
        "tags": "session,abstention,calibration,bench", "use_count": 4, "confidence": 0.9,
        "user_pinned": 0, "valid_from": "2025-02-18T00:00:00", "valid_until": None,
        "ingested_at": "2025-02-18T00:00:00", "session_id": "sess-gamma",
        "created_at": "2025-02-18T00:00:00", "updated_at": "2025-02-18T00:00:00",
        "path": None, "source": "demo",
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
        "path": None, "source": "demo",
    },
]

_DEMO_EDGES: list[dict[str, Any]] = [
    {"from_id": "mem-001", "to_id": "code-002", "relationship": "influences", "weight": 0.9},
    {"from_id": "mem-002", "to_id": "mem-006", "relationship": "supports", "weight": 0.8},
    {"from_id": "mem-003", "to_id": "code-001", "relationship": "constrains", "weight": 0.95},
    {"from_id": "mem-003", "to_id": "code-003", "relationship": "constrains", "weight": 0.9},
    {"from_id": "mem-004", "to_id": "code-002", "relationship": "related_to", "weight": 0.7},
    {"from_id": "mem-004", "to_id": "proc-001", "relationship": "spawned", "weight": 0.85},
    {"from_id": "mem-005", "to_id": "code-003", "relationship": "influences", "weight": 0.88},
    {"from_id": "mem-006", "to_id": "mem-003", "relationship": "related_to", "weight": 0.75},
    {"from_id": "code-003", "to_id": "code-001", "relationship": "calls", "weight": 1.0},
    {"from_id": "code-001", "to_id": "code-004", "relationship": "calls", "weight": 1.0},
    {"from_id": "code-001", "to_id": "code-002", "relationship": "imports", "weight": 1.0},
    {"from_id": "code-004", "to_id": "code-002", "relationship": "imports", "weight": 1.0},
    {"from_id": "code-005", "to_id": "code-002", "relationship": "imports", "weight": 0.9},
    {"from_id": "proc-001", "to_id": "code-002", "relationship": "targets", "weight": 0.8},
    {"from_id": "proc-002", "to_id": "code-003", "relationship": "targets", "weight": 0.85},
    {"from_id": "proc-002", "to_id": "code-001", "relationship": "targets", "weight": 0.8},
    {"from_id": "sess-n-001", "to_id": "mem-001", "relationship": "produced", "weight": 0.7},
    {"from_id": "sess-n-001", "to_id": "mem-005", "relationship": "produced", "weight": 0.7},
    {"from_id": "sess-n-002", "to_id": "mem-004", "relationship": "produced", "weight": 0.75},
    {"from_id": "mem-005", "to_id": "mem-arch-001", "relationship": "supersedes", "weight": 1.0},
]


def _seed_demo(conn: sqlite3.Connection) -> None:
    """Insert synthetic demo neurons and edges into an in-memory DB."""
    for n in _DEMO_NODES:
        conn.execute(
            """INSERT OR IGNORE INTO nodes
               (id, kind, subtype, title, content, tags, use_count, confidence,
                user_pinned, valid_from, valid_until, ingested_at, session_id,
                created_at, updated_at, path, source)
               VALUES (:id,:kind,:subtype,:title,:content,:tags,:use_count,:confidence,
                       :user_pinned,:valid_from,:valid_until,:ingested_at,:session_id,
                       :created_at,:updated_at,:path,:source)""",
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
# Graph / version / search queries
# ---------------------------------------------------------------------------

def _query_graph(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return all nodes (including archived) and their edges as JSON-ready dict."""
    cur = conn.execute(
        """SELECT id, kind, subtype, title, content, tags, use_count, confidence,
                  user_pinned, valid_from, valid_until, ingested_at, session_id,
                  created_at, updated_at, path, source
           FROM nodes
           ORDER BY use_count DESC"""
    )
    nodes = [dict(row) for row in cur.fetchall()]
    node_ids = {n["id"] for n in nodes}

    cur = conn.execute(
        "SELECT from_id, to_id, relationship, weight FROM edges"
    )
    edges = [
        dict(row) for row in cur.fetchall()
        if row["from_id"] in node_ids and row["to_id"] in node_ids
    ]

    return {"nodes": nodes, "edges": edges}


def _query_version(conn: sqlite3.Connection) -> dict[str, Any]:
    """Lightweight fingerprint so the client can poll for live updates."""
    row = conn.execute(
        """SELECT COUNT(*) AS node_count,
                  COALESCE(MAX(updated_at), '') AS max_updated
           FROM nodes"""
    ).fetchone()
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return {
        "node_count": int(row["node_count"]),
        "edge_count": int(edge_count),
        "max_updated": row["max_updated"] or "",
    }


def _query_search(conn: sqlite3.Connection, query: str, *, limit: int = 8) -> dict[str, Any]:
    """FTS5-backed neuron search for chat grounding / RAG."""
    from brainkm.services.search import fts_search_nodes

    q = (query or "").strip()
    if not q:
        return {"query": q, "results": []}

    hits = fts_search_nodes(conn, q, limit=limit)
    if not hits:
        return {"query": q, "results": []}

    placeholders = ",".join("?" for _ in hits)
    ids = [node_id for node_id, _ in hits]
    score_by_id = {node_id: score for node_id, score in hits}
    rows = conn.execute(
        f"""SELECT id, kind, subtype, title, content, tags, path, source,
                   confidence, use_count, valid_until
            FROM nodes WHERE id IN ({placeholders})""",
        ids,
    ).fetchall()
    by_id = {row["id"]: dict(row) for row in rows}
    results = []
    for node_id, _score in hits:
        node = by_id.get(node_id)
        if not node:
            continue
        content = node.get("content") or ""
        results.append({
            "id": node["id"],
            "kind": node["kind"],
            "subtype": node.get("subtype"),
            "title": node["title"],
            "content": content[:600],
            "tags": node.get("tags"),
            "path": node.get("path"),
            "source": node.get("source"),
            "score": score_by_id[node_id],
            "archived": bool(node.get("valid_until")),
        })
    return {"query": q, "results": results}


# ---------------------------------------------------------------------------
# DB lifecycle for the HTTP handler
# ---------------------------------------------------------------------------

def _open_demo_connection() -> sqlite3.Connection:
    from brainkm.db.connection import configure_connection
    from brainkm.db.paths import migrations_dir

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    configure_connection(conn)
    for sql_path in sorted(migrations_dir().glob("*.sql")):
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    conn.commit()
    _seed_demo(conn)
    logger.info(
        "viz demo mode: seeded %d nodes, %d edges",
        len(_DEMO_NODES),
        len(_DEMO_EDGES),
    )
    return conn


def _open_live_connection(db_path: Path) -> sqlite3.Connection:
    from brainkm.db.connection import configure_connection

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    configure_connection(conn)
    return conn


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _VizHandler(BaseHTTPRequestHandler):
    """Serves /api/* JSON and static assets under viz_static/."""

    db_path: Path | None = None
    demo_conn: sqlite3.Connection | None = None
    demo: bool = False
    project_dir: Path | None = None

    def log_message(self, fmt: str, *args: object) -> None:  # type: ignore[override]
        logger.debug(fmt, *args)

    def _with_conn(self):
        """Yield a usable connection (demo shared, or fresh read-only live)."""
        if self.__class__.demo and self.__class__.demo_conn is not None:
            return self.__class__.demo_conn, False
        if self.__class__.db_path is None:
            raise FileNotFoundError("viz server has no database")
        return _open_live_connection(self.__class__.db_path), True

    def _send_json(self, data: dict | list, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel: str) -> None:
        # Prevent path traversal
        candidate = (_STATIC_DIR / rel).resolve()
        if not str(candidate).startswith(str(_STATIC_DIR.resolve())):
            self._send_json({"error": "not found"}, 404)
            return
        if not candidate.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        mime, _ = mimetypes.guess_type(str(candidate))
        if candidate.suffix == ".js":
            mime = "text/javascript; charset=utf-8"
        elif candidate.suffix == ".css":
            mime = "text/css; charset=utf-8"
        elif candidate.suffix == ".html":
            mime = "text/html; charset=utf-8"
        self._send_bytes(candidate.read_bytes(), mime or "application/octet-stream")

    def _send_model_file(self, model_id: str, rel: str) -> None:
        from brainkm.services.webllm_prefetch import WEBLLM_MODELS, model_cache_dir

        if model_id not in WEBLLM_MODELS or ".." in rel or rel.startswith("/"):
            self._send_json({"error": "not found"}, 404)
            return
        root = model_cache_dir(model_id).resolve()
        candidate = (root / rel).resolve()
        if not str(candidate).startswith(str(root)) or not candidate.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        mime, _ = mimetypes.guess_type(str(candidate))
        if candidate.suffix == ".json":
            mime = "application/json"
        self._send_bytes(candidate.read_bytes(), mime or "application/octet-stream")

    def _webllm_config(self) -> dict[str, Any]:
        from brainkm.services.webllm_prefetch import (
            DEFAULT_MODEL_ID,
            WEBLLM_MODELS,
            is_model_cached,
            model_lib_url,
            status_summary,
            webllm_engine_config,
        )

        preferred = DEFAULT_MODEL_ID
        project_dir = self.__class__.project_dir
        if project_dir is not None:
            try:
                from brainkm.services.config_loader import load_brain_config

                cfg = load_brain_config(project_dir)
                preferred = cfg.viz.webllm_model or preferred
            except Exception:  # noqa: BLE001
                pass
        if preferred not in WEBLLM_MODELS:
            preferred = DEFAULT_MODEL_ID

        cached = is_model_cached(preferred)
        payload: dict[str, Any] = {
            "preferred_model": preferred,
            "cached": cached,
            "models": status_summary(preferred)["models"],
            "use_local": cached,
        }
        if cached:
            payload["app_config"] = {
                "model_list": [
                    webllm_engine_config(
                        preferred,
                        local_model_base_url=f"/models/{preferred}",
                    )
                ]
            }
            # Absolute URL so workers resolve correctly
            host = self.headers.get("Host") or "127.0.0.1"
            base = f"http://{host}/models/{preferred}/"
            payload["app_config"]["model_list"][0]["model"] = base
            payload["model_lib"] = model_lib_url(preferred)
        return payload

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/graph":
            try:
                conn, should_close = self._with_conn()
                try:
                    self._send_json(_query_graph(conn))
                finally:
                    if should_close:
                        conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.exception("viz /api/graph failed")
                self._send_json({"error": str(exc)}, 500)
            return

        if path == "/api/version":
            try:
                conn, should_close = self._with_conn()
                try:
                    self._send_json(_query_version(conn))
                finally:
                    if should_close:
                        conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.exception("viz /api/version failed")
                self._send_json({"error": str(exc)}, 500)
            return

        if path == "/api/search":
            params = parse_qs(parsed.query)
            query = (params.get("q") or [""])[0]
            try:
                limit = int((params.get("limit") or ["8"])[0])
            except ValueError:
                limit = 8
            limit = max(1, min(limit, 20))
            try:
                conn, should_close = self._with_conn()
                try:
                    self._send_json(_query_search(conn, query, limit=limit))
                finally:
                    if should_close:
                        conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.exception("viz /api/search failed")
                self._send_json({"error": str(exc)}, 500)
            return

        if path == "/api/webllm-config":
            try:
                self._send_json(self._webllm_config())
            except Exception as exc:  # noqa: BLE001
                logger.exception("viz /api/webllm-config failed")
                self._send_json({"error": str(exc)}, 500)
            return

        if path.startswith("/models/"):
            # /models/<model_id>/<relative/path>
            parts = path.strip("/").split("/", 2)
            if len(parts) < 3:
                self._send_json({"error": "not found"}, 404)
                return
            _models, model_id, rel = parts[0], parts[1], parts[2]
            self._send_model_file(model_id, rel)
            return

        if path in ("/", "/index.html"):
            self._send_static("index.html")
            return

        # Static assets: /styles.css, /app.js, /chat.js, ...
        if path.startswith("/") and ".." not in path:
            rel = path.lstrip("/")
            if rel:
                self._send_static(rel)
                return

        self._send_json({"error": "not found"}, 404)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VizServerHandle:
    """Background viz HTTP server started for the TUI (or other callers)."""

    url: str
    port: int
    node_count: int
    edge_count: int
    demo: bool
    server: HTTPServer
    thread: threading.Thread

    def stop(self) -> None:
        """Shut down the background HTTP server."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        demo_conn = _VizHandler.demo_conn
        if demo_conn is not None:
            try:
                demo_conn.close()
            except Exception:  # noqa: BLE001
                pass
            _VizHandler.demo_conn = None


def _prepare_handler_state(
    project_dir: Path | None,
    *,
    demo: bool,
) -> dict[str, Any]:
    """Configure class-level handler state and return an initial version fingerprint."""
    from brainkm.db.paths import brain_db_path

    _VizHandler.demo = demo
    _VizHandler.demo_conn = None
    _VizHandler.db_path = None
    _VizHandler.project_dir = project_dir

    if demo:
        _VizHandler.demo_conn = _open_demo_connection()
        return _query_version(_VizHandler.demo_conn)

    db_path = brain_db_path(project_dir)
    if not db_path.exists():
        msg = (
            f"No brain.db found at {db_path}. "
            "Run 'brainkm install' first, or use demo mode."
        )
        raise FileNotFoundError(msg)
    _VizHandler.db_path = db_path
    conn = _open_live_connection(db_path)
    try:
        return _query_version(conn)
    finally:
        conn.close()


def _bind_viz_server(port: int) -> tuple[HTTPServer, int]:
    """Bind 127.0.0.1:port, falling back to an ephemeral port if busy."""
    try:
        server = HTTPServer(("127.0.0.1", port), _VizHandler)
    except OSError:
        if port == 0:
            raise
        server = HTTPServer(("127.0.0.1", 0), _VizHandler)
    return server, int(server.server_address[1])


def start_viz_server(
    project_dir: Path | None = None,
    port: int = 5757,
    open_browser: bool = True,
    demo: bool = False,
) -> VizServerHandle:
    """Start the viz HTTP server in a daemon thread (non-blocking).

    Used by the Textual TUI so the dashboard stays interactive while the
    neuron graph is served in the browser.
    """
    version = _prepare_handler_state(project_dir, demo=demo)
    node_count = int(version["node_count"])
    edge_count = int(version["edge_count"])
    server, bound_port = _bind_viz_server(port)
    url = f"http://127.0.0.1:{bound_port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True, name="brainkm-viz")
    thread.start()

    if open_browser:
        def _open_after_delay() -> None:
            time.sleep(0.4)
            webbrowser.open(url)

        threading.Thread(target=_open_after_delay, daemon=True).start()

    return VizServerHandle(
        url=url,
        port=bound_port,
        node_count=node_count,
        edge_count=edge_count,
        demo=demo,
        server=server,
        thread=thread,
    )


def run_viz_server(
    project_dir: Path | None = None,
    port: int = 5757,
    open_browser: bool = True,
    demo: bool = False,
) -> None:
    """Start the brainkm viz HTTP server and block until Ctrl+C (CLI entry)."""
    import typer

    try:
        handle = start_viz_server(
            project_dir=project_dir,
            port=port,
            open_browser=open_browser,
            demo=demo,
        )
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    mode_label = " [DEMO]" if handle.demo else ""
    typer.echo(
        f"🧠 MemNetwork Viz{mode_label} — {handle.node_count} neurons, "
        f"{handle.edge_count} edges\n"
        f"   Serving at {handle.url}\n"
        f"   Press Ctrl+C to stop."
    )

    try:
        while handle.thread.is_alive():
            handle.thread.join(timeout=0.5)
    except KeyboardInterrupt:
        typer.echo("\nViz server stopped.")
    finally:
        handle.stop()
