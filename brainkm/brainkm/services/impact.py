"""Blast-radius impact summary + linked memory overlay for traverse."""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from brainkm.models.schemas import ImpactSummary, NeuronResult


def compute_impact_summary(
    conn: sqlite3.Connection,
    activations: dict[str, Any],
    *,
    seed_id: str | None,
    fan_in_threshold: int = 5,
    max_high_fan_in: int = 5,
) -> ImpactSummary:
    """Summarize hop distribution and high fan-in risk among neighbors."""
    by_hop: Counter[str] = Counter()
    neighbor_ids: list[str] = []
    for node_id, meta in activations.items():
        if seed_id and node_id == seed_id:
            continue
        depth = int(getattr(meta, "depth", 1) or 1)
        by_hop[str(depth)] += 1
        neighbor_ids.append(node_id)

    high_fan_in: list[dict[str, object]] = []
    if neighbor_ids:
        placeholders = ",".join("?" for _ in neighbor_ids)
        rows = conn.execute(
            f"""
            SELECT n.id, n.title, n.path,
                   (
                     SELECT COUNT(*) FROM edges e
                     WHERE e.to_id = n.id
                       AND e.relationship IN ('calls', 'imports', 'imports_from', 'uses')
                   ) AS in_degree
            FROM nodes n
            WHERE n.id IN ({placeholders})
            ORDER BY in_degree DESC
            LIMIT ?
            """,
            (*neighbor_ids, max_high_fan_in * 3),
        ).fetchall()
        for row in rows:
            degree = int(row["in_degree"] or 0)
            if degree < fan_in_threshold:
                continue
            high_fan_in.append(
                {
                    "node_id": row["id"],
                    "title": row["title"],
                    "path": row["path"],
                    "in_degree": degree,
                }
            )
            if len(high_fan_in) >= max_high_fan_in:
                break

    return ImpactSummary(
        neighbor_count=len(neighbor_ids),
        by_hop=dict(sorted(by_hop.items(), key=lambda item: int(item[0]))),
        high_fan_in=high_fan_in,
        risk_flag=bool(high_fan_in) or len(neighbor_ids) >= 12,
    )


def linked_memories_for_code_nodes(
    conn: sqlite3.Connection,
    code_ids: list[str],
    *,
    limit_per_node: int = 2,
    max_total: int = 10,
    subtypes: tuple[str, ...] = ("decision", "error", "rule"),
) -> list[NeuronResult]:
    """Load about_file/about_symbol memories for impacted code nodes."""
    results: list[NeuronResult] = []
    seen: set[str] = set()
    for code_id in code_ids:
        if len(results) >= max_total:
            break
        placeholders = ",".join("?" for _ in subtypes) if subtypes else ""
        subtype_sql = f" AND n.subtype IN ({placeholders})" if subtypes else ""
        rows = conn.execute(
            f"""
            SELECT n.id, n.kind, n.subtype, n.title, n.content, e.relationship
            FROM edges e
            JOIN nodes n ON n.id = e.from_id
            WHERE e.to_id = ?
              AND e.relationship IN ('about_file', 'about_symbol', 'relates_to')
              AND n.valid_until IS NULL
              AND n.kind = 'memory'
              {subtype_sql}
            ORDER BY COALESCE(n.use_count, 0) DESC, n.updated_at DESC
            LIMIT ?
            """,
            (code_id, *subtypes, limit_per_node) if subtypes else (code_id, limit_per_node),
        ).fetchall()
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            results.append(
                NeuronResult(
                    node_id=row["id"],
                    kind=row["kind"],
                    subtype=row["subtype"],
                    title=row["title"],
                    content=(row["content"] or "")[:280] or None,
                    relationship=row["relationship"],
                    via=code_id,
                )
            )
            if len(results) >= max_total:
                break
    return results
