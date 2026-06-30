"""Models for Graphify graph.json interchange."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GraphifyNode:
    graph_id: str
    label: str
    file_type: str
    source_file: str | None
    source_location: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphifyLink:
    source: str
    target: str
    relation: str
    confidence: str
    weight: float
    source_file: str | None = None


@dataclass(frozen=True)
class ParsedGraphifyGraph:
    nodes: tuple[GraphifyNode, ...]
    links: tuple[GraphifyLink, ...]
    source_path: str
    code_only: bool = True


@dataclass(frozen=True)
class GraphImportResult:
    run_id: str
    status: str
    node_count: int
    edge_count: int
    skipped_non_code_nodes: int
    skipped_edges: int
    graph_path: str


@dataclass(frozen=True)
class GraphifyProbeResult:
    found: bool
    binary_path: str | None
    reason: str | None = None


@dataclass(frozen=True)
class GraphifyExtractResult:
    ok: bool
    graph_path: str
    exit_code: int | None = None
    stderr_snippet: str | None = None


@dataclass(frozen=True)
class GraphSyncResult:
    status: str
    graph_available: bool
    extract_ok: bool | None = None
    import_result: GraphImportResult | None = None
    message: str | None = None
