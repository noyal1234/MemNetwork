"""Conflict-aware supersede candidate detection for remember."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from brainkm.adapters.embeddings import cosine_similarity, get_embedder
from brainkm.services.memory import new_ulid
from brainkm.services.search import fts_search_nodes

# Allow markdown wrappers (** `path` **) and single-segment filenames that
# exist in the code graph (matched later by DB lookup).
_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'`(*\[])"
    r"("
    r"(?:[\w.-]+/)+[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|md|json|yaml|yml|toml|tcss|mdc)"
    r"|"
    r"[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java)"
    r")"
    r"(?:$|[\s\"'`)*\],:;])",
    re.MULTILINE,
)

_NEGATION = re.compile(
    r"\b(not|never|instead of|rather than|no longer|deprecated|reject|avoid|don't|do not)\b",
    re.I,
)


@dataclass(frozen=True)
class SupersedeSuggestion:
    node_id: str
    similarity: float
    conflict: bool
    reason: str


def extract_path_mentions(text: str) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for match in _PATH_PATTERN.finditer(text):
        path = match.group(1).strip()
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


_SYMBOL_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z0-9]+(?:[A-Z][a-zA-Z0-9]+)+)\b"
    r"|\b([a-z_][a-z0-9_]{2,})\s*\("
)
_SYMBOL_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "true",
        "false",
        "none",
        "null",
        "self",
        "init",
        "main",
        "test",
        "data",
        "type",
        "name",
        "path",
        "file",
        "code",
        "list",
        "dict",
        "open",
        "read",
        "write",
        "load",
        "save",
        "get",
        "set",
        "config",
    }
)


def extract_symbol_mentions(text: str) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for match in _SYMBOL_PATTERN.finditer(text):
        symbol = (match.group(1) or match.group(2) or "").strip()
        if not symbol or symbol.lower() in _SYMBOL_STOPWORDS:
            continue
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols[:12]


def _insert_edge(
    conn: sqlite3.Connection,
    *,
    from_id: str,
    to_id: str,
    relationship: str,
    weight: float,
) -> None:
    edge_id = new_ulid()
    now_row = conn.execute("SELECT datetime('now')").fetchone()
    now = now_row[0] if now_row else "now"
    conn.execute(
        """
        INSERT OR IGNORE INTO edges (id, from_id, to_id, relationship, weight, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (edge_id, from_id, to_id, relationship, weight, now, now),
    )


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so mention text cannot widen the match."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _resolve_code_file_id(conn: sqlite3.Connection, path: str) -> str | None:
    """Prefer exact file-node path match; fall back to basename / suffix."""
    # Exact path, prefer subtype=file
    row = conn.execute(
        """
        SELECT id FROM nodes
        WHERE kind = 'code' AND path = ? AND valid_until IS NULL
        ORDER BY CASE WHEN subtype = 'file' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (path,),
    ).fetchone()
    if row is not None:
        return row[0]

    base = path.rsplit("/", 1)[-1]
    esc_base = _escape_like(base)
    esc_path = _escape_like(path)
    # Basename exact, then `/`-bounded suffix (shortened relative paths).
    # ESCAPE '\' keeps %/_ in mentions literal.
    row = conn.execute(
        """
        SELECT id FROM nodes
        WHERE kind = 'code' AND valid_until IS NULL
          AND (
            path = ?
            OR path LIKE ? ESCAPE '\\'
            OR path LIKE ? ESCAPE '\\'
          )
        ORDER BY
          CASE WHEN subtype = 'file' THEN 0 ELSE 1 END,
          LENGTH(path) ASC
        LIMIT 1
        """,
        (base, f"%/{esc_base}", f"%/{esc_path}"),
    ).fetchone()
    return row[0] if row else None


def link_code_nodes_by_path(
    conn: sqlite3.Connection,
    neuron_id: str,
    *,
    title: str,
    content: str,
) -> list[str]:
    """Create about_file edges from neuron to code nodes matching path mentions."""
    linked: list[str] = []
    blob = f"{title}\n{content}"
    for path in extract_path_mentions(blob):
        code_id = _resolve_code_file_id(conn, path)
        if code_id is None:
            continue
        _insert_edge(
            conn,
            from_id=neuron_id,
            to_id=code_id,
            relationship="about_file",
            weight=0.8,
        )
        linked.append(code_id)
    return linked


def link_code_nodes_by_symbol(
    conn: sqlite3.Connection,
    neuron_id: str,
    *,
    title: str,
    content: str,
) -> list[str]:
    """Create about_symbol edges when exactly one code node title matches."""
    linked: list[str] = []
    blob = f"{title}\n{content}"
    for symbol in extract_symbol_mentions(blob):
        # Exact title first (function nodes often store "name()" — try both).
        rows = conn.execute(
            """
            SELECT id FROM nodes
            WHERE kind = 'code'
              AND valid_until IS NULL
              AND (title = ? OR title = ?)
            LIMIT 3
            """,
            (symbol, f"{symbol}()"),
        ).fetchall()
        if len(rows) != 1:
            # Unambiguous prefix only for CamelCase / long symbols
            if len(symbol) < 6 or not symbol[0].isupper():
                continue
            rows = conn.execute(
                """
                SELECT id FROM nodes
                WHERE kind = 'code'
                  AND valid_until IS NULL
                  AND (title = ? OR title LIKE ?)
                LIMIT 3
                """,
                (symbol, f"{symbol}%"),
            ).fetchall()
            if len(rows) != 1:
                continue
        code_id = rows[0][0]
        _insert_edge(
            conn,
            from_id=neuron_id,
            to_id=code_id,
            relationship="about_symbol",
            weight=0.55,
        )
        linked.append(code_id)
    return linked


def link_neuron_to_code(
    conn: sqlite3.Connection,
    neuron_id: str,
    *,
    title: str,
    content: str,
) -> list[str]:
    """Link path + unambiguous symbol mentions. Returns linked code node ids."""
    linked = link_code_nodes_by_path(conn, neuron_id, title=title, content=content)
    for code_id in link_code_nodes_by_symbol(
        conn, neuron_id, title=title, content=content
    ):
        if code_id not in linked:
            linked.append(code_id)
    return linked


def find_supersede_candidates(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str,
    exclude_id: str | None = None,
    similarity_threshold: float = 0.85,
) -> list[str]:
    """Backward-compatible list of candidate node ids."""
    return [
        item.node_id
        for item in detect_conflicts(
            conn,
            title=title,
            content=content,
            exclude_id=exclude_id,
            similarity_threshold=similarity_threshold,
        )
    ]


def detect_conflicts(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str,
    exclude_id: str | None = None,
    similarity_threshold: float = 0.85,
) -> list[SupersedeSuggestion]:
    """High similarity + conflicting claim → supersede suggestion."""
    query = title.strip()
    if not query:
        return []

    hits = fts_search_nodes(conn, query, limit=8)
    if not hits:
        return []

    best_score = min(score for _, score in hits)
    new_blob = f"{title}\n{content}"
    new_neg = bool(_NEGATION.search(new_blob))
    embedder = get_embedder(prefer_onnx=False)
    new_vec = embedder.embed(new_blob)

    suggestions: list[SupersedeSuggestion] = []
    for node_id, score in hits:
        if exclude_id and node_id == exclude_id:
            continue
        relative = abs(score) / max(abs(best_score), 1e-9)
        row = conn.execute(
            "SELECT title, content FROM nodes WHERE id = ? AND valid_until IS NULL",
            (node_id,),
        ).fetchone()
        if row is None:
            continue
        old_blob = f"{row[0]}\n{row[1] or ''}"
        old_vec = embedder.embed(old_blob)
        emb_sim = cosine_similarity(new_vec, old_vec)
        lexical_ok = relative >= similarity_threshold
        semantic_ok = emb_sim >= 0.82
        if not (lexical_ok or semantic_ok):
            continue
        old_neg = bool(_NEGATION.search(old_blob))
        conflict = (new_neg != old_neg) or (
            semantic_ok and emb_sim < 0.97 and new_blob.strip().lower() != old_blob.strip().lower()
        )
        reason = "conflicting claim" if conflict else "near-duplicate"
        suggestions.append(
            SupersedeSuggestion(
                node_id=node_id,
                similarity=max(relative, emb_sim),
                conflict=conflict,
                reason=reason,
            )
        )

    suggestions.sort(key=lambda item: (item.conflict, item.similarity), reverse=True)
    return suggestions
