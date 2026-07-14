"""Token bench — context_pack size vs naive file-read baseline."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from brainkm.models.brain_config import BrainConfig, BudgetConfig, RecallConfig
from brainkm.services.abstention_calibrate import FixtureNode, seed_fixture_corpus
from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.services.budget import BudgetLine, greedy_truncate, line_tokens, priority_for
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.memory import token_count

DEFAULT_TOKEN_FIXTURE_ID = "token_v1"
BUDGET_PROBE_PAD = (
    "Services own business logic and token budget enforcement. "
    "Adapters wrap external systems like Graphify and transcripts. "
    "This architectural boundary prevents MCP handlers from writing SQL directly "
    "and keeps pytest focused on service units rather than transport details."
)
BUDGET_PROBE_MIN_NODE_TOKENS = 200


@dataclass(frozen=True)
class TokenFixtureCase:
    name: str
    query: str
    corpus: list[FixtureNode]
    baseline_files: list[str]
    baseline_tokens: int | None
    must_include: tuple[str, ...]


@dataclass(frozen=True)
class BudgetProbe:
    query: str
    caps: tuple[int, ...]
    must_include_at_1500: tuple[str, ...]
    corpus: list[FixtureNode]


@dataclass(frozen=True)
class TokenFixture:
    version: int
    id: str
    min_reduction_pct: float
    max_pack_tokens: int
    cases: list[TokenFixtureCase]
    budget_probe: BudgetProbe | None


def default_token_fixture_path(fixture_id: str = DEFAULT_TOKEN_FIXTURE_ID) -> Path:
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / f"{fixture_id}.json"


def load_token_fixture(path: Path | None = None) -> TokenFixture:
    if path is None:
        path = default_token_fixture_path()
    data = json.loads(path.read_text(encoding="utf-8"))

    cases: list[TokenFixtureCase] = []
    for item in data["cases"]:
        corpus = [
            FixtureNode(
                id=node["id"],
                kind=node.get("kind", "memory"),
                subtype=node.get("subtype"),
                title=node.get("title", ""),
                content=node.get("content", ""),
            )
            for node in item["corpus"]
        ]
        cases.append(
            TokenFixtureCase(
                name=item["name"],
                query=item["query"],
                corpus=corpus,
                baseline_files=list(item.get("baseline_files", [])),
                baseline_tokens=item.get("baseline_tokens"),
                must_include=tuple(item.get("must_include", [])),
            )
        )

    budget_probe: BudgetProbe | None = None
    raw_probe = data.get("budget_probe")
    if raw_probe:
        probe_corpus = [
            FixtureNode(
                id=node["id"],
                kind=node.get("kind", "memory"),
                subtype=node.get("subtype"),
                title=node.get("title", ""),
                content=node.get("content", ""),
            )
            for node in raw_probe["corpus"]
        ]
        budget_probe = BudgetProbe(
            query=raw_probe["query"],
            caps=tuple(int(cap) for cap in raw_probe["caps"]),
            must_include_at_1500=tuple(raw_probe.get("must_include_at_1500", [])),
            corpus=probe_corpus,
        )

    return TokenFixture(
        version=int(data.get("version", 1)),
        id=str(data.get("id", path.stem)),
        min_reduction_pct=float(data.get("min_reduction_pct", 0.5)),
        max_pack_tokens=int(data.get("max_pack_tokens", 1500)),
        cases=cases,
        budget_probe=budget_probe,
    )


def load_package_token_fixture(fixture_id: str = DEFAULT_TOKEN_FIXTURE_ID) -> TokenFixture:
    package_path = resources.files("brainkm.bench.fixtures") / f"{fixture_id}.json"
    return load_token_fixture(Path(str(package_path)))


def _seed_nodes(conn: sqlite3.Connection, nodes: list[FixtureNode]) -> None:
    from brainkm.services.abstention_calibrate import AbstentionFixture

    seed_fixture_corpus(conn, AbstentionFixture(version=1, id="seed", corpus=nodes, queries=[]))


def measure_baseline_tokens(
    project_dir: Path,
    baseline_files: list[str],
    *,
    fallback: int | None = None,
) -> int:
    """Sum tiktoken counts for naive multi-file read; use fallback when files are absent."""
    total = 0
    found_any = False
    for relative in baseline_files:
        path = project_dir / relative
        if path.is_file():
            total += token_count(path.read_text(encoding="utf-8"))
            found_any = True
    if found_any:
        return total
    if fallback is not None:
        return fallback
    missing = ", ".join(baseline_files)
    msg = f"baseline files not found under {project_dir}: {missing}"
    raise FileNotFoundError(msg)


def _bench_config(*, total_tokens: int) -> BrainConfig:
    return BrainConfig(
        budget=BudgetConfig(total_tokens=total_tokens),
        recall=RecallConfig(abstain_on_low_confidence=False),
    )


def evaluate_token_case(
    conn: sqlite3.Connection,
    case: TokenFixtureCase,
    *,
    project_dir: Path,
    min_reduction_pct: float,
    max_pack_tokens: int,
) -> BenchCaseResult:
    _seed_nodes(conn, case.corpus)
    conn.commit()

    baseline = measure_baseline_tokens(
        project_dir,
        case.baseline_files,
        fallback=case.baseline_tokens,
    )
    pack = compile_context_pack(
        conn,
        case.query,
        config=_bench_config(total_tokens=max_pack_tokens),
        project_dir=project_dir,
    )
    pack_tokens = pack.truncation.tokens_used
    reduction = 1.0 - (pack_tokens / baseline) if baseline > 0 else 0.0
    included = set(pack.truncation.included_ids)

    missing_required = [node_id for node_id in case.must_include if node_id not in included]
    cap_ok = pack_tokens <= max_pack_tokens
    reduction_ok = reduction >= min_reduction_pct
    coverage_ok = not missing_required
    passed = cap_ok and reduction_ok and coverage_ok

    detail = (
        f"pack={pack_tokens} baseline={baseline} "
        f"reduction={reduction:.0%} omitted={len(pack.truncation.omitted_ids)}"
    )
    if missing_required:
        detail += f" missing={','.join(missing_required)}"
    return BenchCaseResult(name=case.name, passed=passed, detail=detail)


def evaluate_live_token_case(
    conn: sqlite3.Connection,
    case: TokenFixtureCase,
    *,
    project_dir: Path,
    config: BrainConfig,
) -> BenchCaseResult:
    """Run a fixture query against the project's live brain.db (no fixture seeding)."""
    baseline = measure_baseline_tokens(
        project_dir,
        case.baseline_files,
        fallback=case.baseline_tokens,
    )
    pack = compile_context_pack(
        conn,
        case.query,
        config=config,
        project_dir=project_dir,
    )
    from brainkm.services.memory import token_count

    pack_tokens = token_count(pack.pack_text)
    payload_tokens = token_count(
        json.dumps(pack.model_dump(), separators=(",", ":"), ensure_ascii=False)
    )
    reduction = 1.0 - (pack_tokens / baseline) if baseline > 0 else 0.0
    cap = config.budget.total_tokens
    memory_count = len(pack.truncation.included_ids)
    code_count = 0
    passed = pack_tokens <= cap and payload_tokens <= cap
    detail = (
        f"pack={pack_tokens}/{cap} payload={payload_tokens}/{cap} baseline={baseline} "
        f"reduction={reduction:.0%} included={memory_count} "
        f"omitted={len(pack.truncation.omitted_ids)}"
    )
    return BenchCaseResult(name=case.name, passed=passed, detail=detail)


def probe_context_pack(
    db_path: Path,
    query: str,
    *,
    baseline_files: list[str] | None = None,
) -> BenchCaseResult:
    """Measure a single context_pack against the project's live brain.db."""
    from brainkm.config import set_skip_rolling_scores
    from brainkm.db.migrate import migrate
    from brainkm.services.abstention import best_bm25_score, should_abstain_for_query
    from brainkm.services.config_loader import load_brain_config
    from brainkm.services.search import fts_search_nodes

    set_skip_rolling_scores(True)
    project_dir = db_path.parent.parent
    config = load_brain_config(project_dir)
    migrate(db_path=db_path, run_integrity_check=False)
    conn = connect_for_bench(db_path)
    try:
        fts_hits = fts_search_nodes(conn, query, limit=5)
        seed_scores = [score for _, score in fts_hits]
        abstained = should_abstain_for_query(
            conn,
            seed_scores,
            config.recall,
            project_dir=project_dir,
        )
        pack = compile_context_pack(
            conn,
            query,
            config=config,
            project_dir=project_dir,
        )
        pack_tokens = token_count(pack.pack_text)
        payload_tokens = token_count(
            json.dumps(pack.model_dump(), separators=(",", ":"), ensure_ascii=False)
        )
        cap = config.budget.total_tokens
        baseline: int | None = None
        reduction: float | None = None
        if baseline_files:
            baseline = measure_baseline_tokens(project_dir, baseline_files)
            reduction = 1.0 - (pack_tokens / baseline) if baseline > 0 else 0.0
        parts = [
            f"pack={pack_tokens}/{cap}",
            f"payload={payload_tokens}/{cap}",
            f"included={len(pack.truncation.included_ids)}",
            f"omitted={len(pack.truncation.omitted_ids)}",
            f"fts_hits={len(fts_hits)}",
        ]
        if seed_scores:
            parts.append(f"best_bm25={best_bm25_score(seed_scores):.2f}")
        parts.append(f"abstained={abstained}")
        if baseline is not None and reduction is not None:
            parts.insert(1, f"baseline={baseline}")
            parts.insert(2, f"reduction={reduction:.0%}")
        if pack.truncation.omitted_ids:
            parts.append(f"omitted_ids={','.join(pack.truncation.omitted_ids[:5])}")
            if len(pack.truncation.omitted_ids) > 5:
                parts[-1] += ",..."
        if pack_tokens == 0 and fts_hits:
            parts.append(f"reason={'abstention' if abstained else 'no_candidates_after_recall'}")
            parts.append(f"top_fts={fts_hits[0][0]}")
        passed = (
            pack_tokens <= cap
            and payload_tokens <= cap
            and not (pack_tokens == 0 and fts_hits)
        )
        return BenchCaseResult(
            name=query[:48],
            passed=passed,
            detail=" ".join(parts),
        )
    finally:
        conn.close()
        set_skip_rolling_scores(False)


def run_token_suite(db_path: Path, *, live: bool = False) -> BenchSuiteResult:
    """Compare context_pack injection size vs naive multi-file read baseline."""
    fixture = load_package_token_fixture()
    project_dir = db_path.parent.parent

    if live:
        from brainkm.config import set_skip_rolling_scores
        from brainkm.db.migrate import migrate
        from brainkm.services.config_loader import load_brain_config

        set_skip_rolling_scores(True)
        config = load_brain_config(project_dir)
        migrate(db_path=db_path, run_integrity_check=False)
        conn = connect_for_bench(db_path)
        cases: list[BenchCaseResult] = []
        try:
            for case in fixture.cases:
                cases.append(
                    evaluate_live_token_case(
                        conn,
                        case,
                        project_dir=project_dir,
                        config=config,
                    )
                )
        finally:
            conn.close()
            set_skip_rolling_scores(False)
        passed = sum(1 for case in cases if case.passed)
        return BenchSuiteResult(suite="token-live", passed=passed, total=len(cases), cases=cases)

    cases: list[BenchCaseResult] = []
    for case in fixture.cases:
        conn, bench_db = ephemeral_bench_db()
        try:
            cases.append(
                evaluate_token_case(
                    conn,
                    case,
                    project_dir=project_dir,
                    min_reduction_pct=fixture.min_reduction_pct,
                    max_pack_tokens=fixture.max_pack_tokens,
                )
            )
        finally:
            conn.close()
            bench_db.unlink(missing_ok=True)

    passed = sum(1 for case in cases if case.passed)
    return BenchSuiteResult(suite="token", passed=passed, total=len(cases), cases=cases)


def _pad_node_content(title: str, content: str, min_tokens: int) -> str:
    body = content
    while line_tokens(title, body) < min_tokens:
        body += " " + BUDGET_PROBE_PAD
    return body


def _corpus_budget_lines(
    conn: sqlite3.Connection,
    nodes: list[FixtureNode],
    *,
    min_tokens_per_node: int = 0,
) -> list[BudgetLine]:
    _seed_nodes(conn, nodes)
    conn.commit()
    lines: list[BudgetLine] = []
    for node in nodes:
        row = conn.execute(
            """
            SELECT id, kind, subtype, title, content, token_count
            FROM nodes WHERE id = ? AND valid_until IS NULL
            """,
            (node.id,),
        ).fetchone()
        if row is None:
            continue
        content = row["content"] or ""
        if min_tokens_per_node:
            content = _pad_node_content(row["title"], content, min_tokens_per_node)
        lines.append(
            BudgetLine(
                node_id=row["id"],
                kind=row["kind"],
                subtype=row["subtype"],
                title=row["title"],
                content=content,
                tokens=line_tokens(row["title"], content),
                priority=priority_for(row["kind"], row["subtype"]),
            )
        )
    return lines


def run_budget_suite(db_path: Path) -> BenchSuiteResult:
    """Probe truncation coverage across budget caps (context-drop safety)."""
    fixture = load_package_token_fixture()
    if fixture.budget_probe is None:
        return BenchSuiteResult(suite="budget", passed=0, total=0, cases=[])

    probe = fixture.budget_probe
    conn, bench_db = ephemeral_bench_db()
    cases: list[BenchCaseResult] = []
    included_by_cap: dict[int, set[str]] = {}

    try:
        lines = _corpus_budget_lines(
            conn,
            probe.corpus,
            min_tokens_per_node=BUDGET_PROBE_MIN_NODE_TOKENS,
        )
        total_untruncated = sum(line.tokens for line in lines)

        for cap in probe.caps:
            included_lines, manifest = greedy_truncate(lines, max_tokens=cap)
            included = {line.node_id for line in included_lines}
            included_by_cap[cap] = included
            missing_at_cap = [
                node_id for node_id in probe.must_include_at_1500 if node_id not in included
            ]
            must_ok = cap != 1500 or not missing_at_cap
            cases.append(
                BenchCaseResult(
                    name=f"cap_{cap}",
                    passed=must_ok and manifest.tokens_used <= cap,
                    detail=(
                        f"used={manifest.tokens_used} "
                        f"included={len(included)} omitted={len(manifest.omitted_ids)}"
                    ),
                )
            )

        if total_untruncated <= min(probe.caps):
            cases.append(
                BenchCaseResult(
                    name="corpus_size",
                    passed=False,
                    detail=f"corpus={total_untruncated} tokens — too small to test truncation",
                )
            )
        else:
            cases.append(
                BenchCaseResult(
                    name="corpus_size",
                    passed=True,
                    detail=f"corpus={total_untruncated} tokens exercises truncation",
                )
            )

        caps_sorted = sorted(probe.caps)
        for lower, higher in zip(caps_sorted, caps_sorted[1:], strict=False):
            if not included_by_cap[lower].issubset(included_by_cap[higher]):
                cases.append(
                    BenchCaseResult(
                        name=f"monotonic_{lower}_to_{higher}",
                        passed=False,
                        detail="higher cap should include all nodes from lower cap",
                    )
                )
            else:
                cases.append(
                    BenchCaseResult(
                        name=f"monotonic_{lower}_to_{higher}",
                        passed=True,
                        detail=f"+{len(included_by_cap[higher]) - len(included_by_cap[lower])} nodes",
                    )
                )
    finally:
        conn.close()
        bench_db.unlink(missing_ok=True)

    passed = sum(1 for case in cases if case.passed)
    return BenchSuiteResult(suite="budget", passed=passed, total=len(cases), cases=cases)


def connect_for_bench(db_path: Path | None = None) -> sqlite3.Connection:
    from brainkm.db.connection import connect
    from brainkm.db.migrate import migrate

    target = db_path
    if target is None:
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        target = Path(handle.name)
    migrate(db_path=target, run_integrity_check=False)
    return connect(target)


def ephemeral_bench_db() -> tuple[sqlite3.Connection, Path]:
    """Fresh isolated DB for reproducible token/budget benches (no project graph)."""
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    path = Path(handle.name)
    return connect_for_bench(path), path


def format_token_summary(result: BenchSuiteResult) -> str:
    """Append aggregate savings line for token suite output."""
    if result.suite not in {"token", "token-live"} or not result.cases:
        return ""
    reductions: list[float] = []
    for case in result.cases:
        if "reduction=" in case.detail:
            fragment = case.detail.split("reduction=", maxsplit=1)[1]
            pct_text = fragment.split("%", maxsplit=1)[0]
            try:
                reductions.append(float(pct_text) / 100.0)
            except ValueError:
                continue
    if not reductions:
        return ""
    avg = sum(reductions) / len(reductions)
    return f"Average pack-vs-file reduction: {avg:.0%} across {len(reductions)} cases"
