"""Graphify graph.json adapter — parse NetworkX node-link JSON (code-only offline)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from brainkm.logging_config import get_logger
from brainkm.models.graphify import GraphifyLink, GraphifyNode, ParsedGraphifyGraph

logger = get_logger("adapters.graphify")

CODE_FILE_TYPES = frozenset({"code"})
NON_CODE_FILE_TYPES = frozenset({"document", "paper", "image", "rationale", "concept"})
_FILE_LABEL = re.compile(
    r"^[\w./-]+\.(py|ts|tsx|js|jsx|mjs|go|rs|java|rb|sql|sh|cpp|c|h|cs|vue|svelte)$",
    re.I,
)


def resolve_graph_json_path(
    project_dir: Path | None,
    *,
    graph_json: str,
) -> Path:
    root = project_dir if project_dir is not None else Path.cwd()
    path = Path(graph_json)
    if path.is_absolute():
        return path
    return root / path


def load_graph_json(
    path: Path,
    *,
    code_only: bool = True,
) -> ParsedGraphifyGraph:
    """Load and normalize a Graphify NetworkX node-link export."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "graph.json root must be an object"
        raise ValueError(msg)

    node_rows = raw.get("nodes")
    if not isinstance(node_rows, list):
        msg = "graph.json missing nodes array"
        raise ValueError(msg)

    link_rows = raw.get("links")
    if link_rows is None:
        link_rows = raw.get("edges")
    if not isinstance(link_rows, list):
        msg = "graph.json missing links/edges array"
        raise ValueError(msg)

    nodes: list[GraphifyNode] = []
    for row in node_rows:
        if not isinstance(row, dict):
            continue
        graph_id = str(row.get("id", "")).strip()
        if not graph_id:
            continue
        file_type = str(row.get("file_type", "code")).lower()
        if code_only and file_type in NON_CODE_FILE_TYPES:
            continue
        if code_only and file_type not in CODE_FILE_TYPES:
            continue

        known = {"id", "label", "file_type", "source_file", "source_location"}
        extra = {key: value for key, value in row.items() if key not in known}
        nodes.append(
            GraphifyNode(
                graph_id=graph_id,
                label=str(row.get("label", graph_id)),
                file_type=file_type,
                source_file=_optional_str(row.get("source_file")),
                source_location=_optional_str(row.get("source_location")),
                extra=extra,
            )
        )

    node_ids = {node.graph_id for node in nodes}
    links: list[GraphifyLink] = []
    for row in link_rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source", "")).strip()
        target = str(row.get("target", "")).strip()
        if not source or not target:
            continue
        if source not in node_ids or target not in node_ids:
            continue

        relation = str(row.get("relation", "relates_to"))
        confidence = str(row.get("confidence", "EXTRACTED")).upper()
        weight = _link_weight(row, confidence=confidence)
        links.append(
            GraphifyLink(
                source=source,
                target=target,
                relation=relation,
                confidence=confidence,
                weight=weight,
                source_file=_optional_str(row.get("source_file")),
            )
        )

    logger.info(
        "Loaded graph.json nodes=%d links=%d code_only=%s path=%s",
        len(nodes),
        len(links),
        code_only,
        path.name,
    )
    return ParsedGraphifyGraph(
        nodes=tuple(nodes),
        links=tuple(links),
        source_path=str(path),
        code_only=code_only,
    )


def infer_code_subtype(label: str, graph_id: str) -> str:
    """Map Graphify labels to brainkm code subtypes."""
    cleaned = label.strip()
    if _FILE_LABEL.match(cleaned):
        return "file"
    if cleaned.startswith("."):
        return "function"
    if cleaned == graph_id or cleaned.replace(".py", "") == graph_id:
        return "file"
    if cleaned and cleaned[0].isupper() and "." not in cleaned and "()" not in cleaned:
        return "class"
    return "function"


def _link_weight(row: dict[str, object], *, confidence: str) -> float:
    raw_weight = row.get("weight")
    if isinstance(raw_weight, (int, float)):
        return float(raw_weight)
    if confidence == "EXTRACTED":
        return 1.0
    if confidence == "INFERRED":
        score = row.get("confidence_score")
        if isinstance(score, (int, float)):
            return float(score)
        return 0.75
    return 0.5


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
