"""Task-success bench — with-brain pack vs selective-read without-arm."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.config import set_skip_rolling_scores
from brainkm.db.migrate import migrate
from brainkm.models.brain_config import BrainConfig
from brainkm.services.bench_db import (
    cleanup_ephemeral_project,
    ensure_fixture_neuron,
    ephemeral_project_brain,
)
from brainkm.services.config_loader import load_brain_config
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.memory import token_count
from brainkm.services.token_bench import connect_for_bench

DEFAULT_TASK_FIXTURE_ID = "task_v1"


@dataclass(frozen=True)
class SelectiveSlice:
    path: str
    max_tokens: int
    start_line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True)
class TaskSeedNeuron:
    id: str
    title: str
    content: str
    subtype: str | None
    kind: str


@dataclass(frozen=True)
class TaskScenario:
    id: str
    query: str
    selective_baseline: tuple[SelectiveSlice, ...]
    gold_facts: tuple[str, ...]
    answer_facts: tuple[str, ...]
    seed_neurons: tuple[TaskSeedNeuron, ...]
    reference_answer: str


@dataclass(frozen=True)
class TaskFixture:
    version: int
    id: str
    min_coverage: float
    scenarios: list[TaskScenario]


def default_task_fixture_path(fixture_id: str = DEFAULT_TASK_FIXTURE_ID) -> Path:
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / f"{fixture_id}.json"


def load_task_fixture(path: Path | None = None) -> TaskFixture:
    if path is None:
        path = default_task_fixture_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    scenarios: list[TaskScenario] = []
    for item in data["scenarios"]:
        slices = tuple(
            SelectiveSlice(
                path=s["path"],
                max_tokens=int(s.get("max_tokens", 400)),
                start_line=s.get("start_line"),
                end_line=s.get("end_line"),
            )
            for s in item["selective_baseline"]
        )
        seeds = tuple(
            TaskSeedNeuron(
                id=n["id"],
                title=n.get("title", ""),
                content=n.get("content", ""),
                subtype=n.get("subtype"),
                kind=n.get("kind", "memory"),
            )
            for n in item.get("seed_neurons", [])
        )
        scenarios.append(
            TaskScenario(
                id=item["id"],
                query=item["query"],
                selective_baseline=slices,
                gold_facts=tuple(item.get("gold_facts", [])),
                answer_facts=tuple(item.get("answer_facts", item.get("gold_facts", []))),
                seed_neurons=seeds,
                reference_answer=item.get("reference_answer", ""),
            )
        )
    return TaskFixture(
        version=int(data["version"]),
        id=data["id"],
        min_coverage=float(data.get("min_coverage", 0.75)),
        scenarios=scenarios,
    )


def load_package_task_fixture(fixture_id: str = DEFAULT_TASK_FIXTURE_ID) -> TaskFixture:
    package_path = resources.files("brainkm.bench.fixtures") / f"{fixture_id}.json"
    return load_task_fixture(Path(str(package_path)))


def _slice_file_text(path: Path, spec: SelectiveSlice) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if spec.start_line is not None or spec.end_line is not None:
        lines = text.splitlines()
        start = max(0, (spec.start_line or 1) - 1)
        end = spec.end_line if spec.end_line is not None else len(lines)
        text = "\n".join(lines[start:end])
    # Cap by approximate tokens (chars/4 heuristic then trim via token_count loop).
    if token_count(text) <= spec.max_tokens:
        return text
    # Trim by characters until under cap (tiktoken is non-linear).
    lo, hi = 0, len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid]
        if token_count(candidate) <= spec.max_tokens:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    while best and token_count(best) > spec.max_tokens:
        best = best[: max(0, len(best) - 64)]
    return best


def measure_selective_baseline(project_dir: Path, slices: tuple[SelectiveSlice, ...]) -> tuple[str, int]:
    """Return concatenated selective excerpts and their token count."""
    parts: list[str] = []
    for spec in slices:
        header = f"# {spec.path}\n"
        header_tokens = token_count(header)
        budget = max(1, spec.max_tokens - header_tokens)
        excerpt_spec = SelectiveSlice(
            path=spec.path,
            max_tokens=budget,
            start_line=spec.start_line,
            end_line=spec.end_line,
        )
        excerpt = _slice_file_text(project_dir / spec.path, excerpt_spec)
        if excerpt:
            parts.append(f"{header}{excerpt}")
    blob = "\n\n".join(parts)
    return blob, token_count(blob)


def gold_coverage(text: str, gold_facts: tuple[str, ...]) -> float:
    if not gold_facts:
        return 1.0
    lower = text.lower()
    hits = sum(1 for fact in gold_facts if fact.lower() in lower)
    return hits / len(gold_facts)


def _ollama_chat(prompt: str, *, base_url: str, model: str, timeout: float) -> str | None:
    try:
        import httpx
    except ImportError:
        return None
    url = f"{base_url.rstrip('/')}/api/chat"
    try:
        tags = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=2.0)
        if tags.status_code != 200:
            return None
        response = httpx.post(
            url,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")
    except Exception:
        return None


def _parse_judge_payload(raw: str) -> dict[str, float | str] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    try:
        return {
            "with_score": float(data.get("with_score", 0)),
            "without_score": float(data.get("without_score", 0)),
            "winner": str(data.get("winner", "tie")),
        }
    except (TypeError, ValueError):
        return None


def judge_task_answers(
    *,
    query: str,
    reference: str,
    with_context: str,
    without_context: str,
    config: BrainConfig,
) -> dict[str, float | str] | None:
    """Optional LLM judge. Returns None if Ollama unavailable."""
    from brainkm.services.ollama_advisor import resolve_ollama_model

    prompt = (
        "You score two contexts for answering a developer question.\n"
        f"Question: {query}\n"
        f"Reference answer: {reference}\n\n"
        f"--- WITH_BRAIN context ---\n{with_context[:6000]}\n\n"
        f"--- WITHOUT_BRAIN context ---\n{without_context[:6000]}\n\n"
        "Return JSON only: "
        '{"with_score":0-1,"without_score":0-1,"winner":"with"|"without"|"tie"}'
    )
    raw = _ollama_chat(
        prompt,
        base_url=config.ollama.base_url,
        model=resolve_ollama_model(config),
        timeout=min(float(config.ollama.timeout_seconds), 60.0),
    )
    if not raw:
        return None
    return _parse_judge_payload(raw)


def ensure_eval_policy_neurons(conn) -> None:
    """Idempotent policy neurons needed for live task eval (e.g. redaction chokepoint)."""
    ensure_fixture_neuron(
        conn,
        node_id="eval-redaction-chokepoint",
        title="Redaction chokepoint",
        content=(
            "Every neuron write funnels through remember_neuron which redacts secrets "
            "via adapters/redaction.py before storage. Never bypass remember_neuron."
        ),
        kind="memory",
        subtype="rule",
    )
    conn.commit()


def evaluate_task_scenario(
    conn,
    scenario: TaskScenario,
    *,
    project_dir: Path,
    config: BrainConfig,
    min_coverage: float,
    judge: bool = False,
) -> BenchCaseResult:
    pack = compile_context_pack(
        conn,
        scenario.query,
        config=config,
        project_dir=project_dir,
    )
    pack_text = pack.pack_text
    pack_tokens = token_count(pack_text)
    selective_text, selective_tokens = measure_selective_baseline(
        project_dir, scenario.selective_baseline
    )
    with_cov = gold_coverage(pack_text, scenario.gold_facts)
    without_cov = gold_coverage(selective_text, scenario.gold_facts)
    answer_cov = gold_coverage(pack_text, scenario.answer_facts)
    cap = config.budget.total_tokens

    answer_ok = answer_cov >= 1.0 if scenario.answer_facts else True
    coverage_ok = with_cov >= without_cov or with_cov >= min_coverage
    cap_ok = pack_tokens <= cap
    passed = answer_ok and coverage_ok and cap_ok

    detail_parts = [
        f"answer_cov={answer_cov:.0%}",
        f"with_cov={with_cov:.0%}",
        f"without_cov={without_cov:.0%}",
        f"pack={pack_tokens}/{cap}",
        f"selective={selective_tokens}",
        f"savings={'yes' if pack_tokens < selective_tokens else 'no'}",
        f"included={len(pack.truncation.included_ids)}",
    ]

    if judge:
        judged = judge_task_answers(
            query=scenario.query,
            reference=scenario.reference_answer,
            with_context=pack_text,
            without_context=selective_text,
            config=config,
        )
        if judged is None:
            detail_parts.append("judge=skipped")
        else:
            detail_parts.append(
                f"judge_with={judged['with_score']:.2f} "
                f"judge_without={judged['without_score']:.2f} "
                f"winner={judged['winner']}"
            )
            # Soft: fail only when judge ran and with loses by clear margin.
            if (
                judged["winner"] == "without"
                and float(judged["without_score"]) - float(judged["with_score"]) >= 0.15
            ):
                passed = False
                detail_parts.append("judge_fail")

    return BenchCaseResult(name=scenario.id, passed=passed, detail=" ".join(detail_parts))


def run_task_suite(
    db_path: Path,
    *,
    fixture_only: bool = False,
    judge: bool = False,
) -> BenchSuiteResult:
    """Run task-success scenarios.

    ``fixture_only`` seeds an ephemeral brain (reproducible). Otherwise uses the
    live project ``brain.db`` at ``db_path``. Selective baselines always read from
    the real project directory (parent of ``.brain``).
    """
    fixture = load_package_task_fixture()
    project_dir = db_path.parent.parent
    set_skip_rolling_scores(True)
    cases: list[BenchCaseResult] = []
    ephemeral_project: Path | None = None
    conn = None
    try:
        if fixture_only:
            conn, _db, ephemeral_project = ephemeral_project_brain()
            for scenario in fixture.scenarios:
                for seed in scenario.seed_neurons:
                    ensure_fixture_neuron(
                        conn,
                        node_id=seed.id,
                        title=seed.title,
                        content=seed.content,
                        kind=seed.kind,
                        subtype=seed.subtype,
                    )
            conn.commit()
            config = BrainConfig()
        else:
            migrate(db_path=db_path, run_integrity_check=False)
            conn = connect_for_bench(db_path)
            config = load_brain_config(project_dir)
            ensure_eval_policy_neurons(conn)

        for scenario in fixture.scenarios:
            cases.append(
                evaluate_task_scenario(
                    conn,
                    scenario,
                    project_dir=project_dir,
                    config=config,
                    min_coverage=fixture.min_coverage,
                    judge=judge,
                )
            )
    finally:
        if fixture_only and ephemeral_project is not None:
            cleanup_ephemeral_project(ephemeral_project, conn)
        elif conn is not None:
            conn.close()
        set_skip_rolling_scores(False)

    passed = sum(1 for case in cases if case.passed)
    return BenchSuiteResult(suite="task", passed=passed, total=len(cases), cases=cases)


def format_task_summary(result: BenchSuiteResult) -> str:
    if result.suite != "task" or not result.cases:
        return ""
    with_covs: list[float] = []
    without_covs: list[float] = []
    for case in result.cases:
        if "with_cov=" in case.detail:
            frag = case.detail.split("with_cov=", maxsplit=1)[1]
            with_covs.append(float(frag.split("%", maxsplit=1)[0]) / 100.0)
        if "without_cov=" in case.detail:
            frag = case.detail.split("without_cov=", maxsplit=1)[1]
            without_covs.append(float(frag.split("%", maxsplit=1)[0]) / 100.0)
    if not with_covs:
        return ""
    avg_with = sum(with_covs) / len(with_covs)
    avg_without = sum(without_covs) / len(without_covs) if without_covs else 0.0
    return (
        f"Avg gold coverage: with_brain={avg_with:.0%} "
        f"without_selective={avg_without:.0%} across {len(with_covs)} tasks"
    )
