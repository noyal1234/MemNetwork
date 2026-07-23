"""Compare bench — with-brain context_pack vs without-brain naive file reads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from brainkm.bench.results import BenchCaseResult, BenchSuiteResult
from brainkm.config import set_skip_rolling_scores
from brainkm.db.migrate import migrate
from brainkm.services.config_loader import load_brain_config
from brainkm.services.context_pack import compile_context_pack
from brainkm.services.memory import token_count
from brainkm.services.token_bench import connect_for_bench, measure_baseline_tokens

DEFAULT_COMPARE_FIXTURE_ID = "compare_v1"


@dataclass(frozen=True)
class CompareScenario:
    id: str
    query: str
    baseline_files: list[str]
    must_include_substrings: tuple[str, ...]


@dataclass(frozen=True)
class CompareFixture:
    version: int
    id: str
    scenarios: list[CompareScenario]


def default_compare_fixture_path(fixture_id: str = DEFAULT_COMPARE_FIXTURE_ID) -> Path:
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / f"{fixture_id}.json"


def load_compare_fixture(path: Path | None = None) -> CompareFixture:
    if path is None:
        path = default_compare_fixture_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    scenarios = [
        CompareScenario(
            id=item["id"],
            query=item["query"],
            baseline_files=list(item["baseline_files"]),
            must_include_substrings=tuple(item.get("must_include_substrings", [])),
        )
        for item in data["scenarios"]
    ]
    return CompareFixture(version=int(data["version"]), id=data["id"], scenarios=scenarios)


def load_package_compare_fixture(fixture_id: str = DEFAULT_COMPARE_FIXTURE_ID) -> CompareFixture:
    package_path = resources.files("brainkm.bench.fixtures") / f"{fixture_id}.json"
    return load_compare_fixture(Path(str(package_path)))


def evaluate_compare_scenario(
    conn,
    scenario: CompareScenario,
    *,
    project_dir: Path,
    config,
) -> BenchCaseResult:
    """Score one with-brain vs without-brain scenario against the live project brain."""
    baseline_tokens = measure_baseline_tokens(project_dir, scenario.baseline_files)
    pack = compile_context_pack(
        conn,
        scenario.query,
        config=config,
        project_dir=project_dir,
    )
    pack_tokens = token_count(pack.pack_text)
    payload_tokens = token_count(
        json.dumps(pack.model_dump(), separators=(",", ":"), ensure_ascii=False)
    )
    cap = config.budget.total_tokens
    reduction = 1.0 - (pack_tokens / baseline_tokens) if baseline_tokens > 0 else 0.0
    ratio = (baseline_tokens / pack_tokens) if pack_tokens > 0 else float("inf")

    under_cap = pack_tokens <= cap and payload_tokens <= cap
    saves_tokens = pack_tokens < baseline_tokens

    pack_lower = pack.pack_text.lower()
    missing_facts: list[str] = []
    facts_checked = False
    included = len(pack.truncation.included_ids)
    if scenario.must_include_substrings:
        if included == 0:
            # Empty/abstained pack (header-only tokens) — do not fail on missing phrases.
            facts_note = "facts=skipped_empty_pack"
        else:
            facts_checked = True
            for phrase in scenario.must_include_substrings:
                if phrase.lower() not in pack_lower:
                    missing_facts.append(phrase)
            hit = len(scenario.must_include_substrings) - len(missing_facts)
            total = len(scenario.must_include_substrings)
            facts_note = f"facts={hit}/{total}"
            if missing_facts:
                facts_note += f" missing={','.join(missing_facts)}"
    else:
        facts_note = "facts=n/a"

    facts_ok = (not facts_checked) or (not missing_facts)
    passed = under_cap and saves_tokens and facts_ok

    ratio_text = f"{ratio:.1f}x" if pack_tokens > 0 and ratio != float("inf") else "n/a"
    detail = (
        f"without={baseline_tokens} with={pack_tokens}/{cap} "
        f"payload={payload_tokens}/{cap} reduction={reduction:.0%} "
        f"savings={ratio_text} included={len(pack.truncation.included_ids)} "
        f"omitted={len(pack.truncation.omitted_ids)} {facts_note}"
    )
    return BenchCaseResult(name=scenario.id, passed=passed, detail=detail)


def run_compare_suite(db_path: Path) -> BenchSuiteResult:
    """Run with-brain vs without-brain scenarios against the project's live brain.db."""
    fixture = load_package_compare_fixture()
    project_dir = db_path.parent.parent
    set_skip_rolling_scores(True)
    config = load_brain_config(project_dir)
    migrate(db_path=db_path, run_integrity_check=False)
    conn = connect_for_bench(db_path)
    cases: list[BenchCaseResult] = []
    try:
        for scenario in fixture.scenarios:
            cases.append(
                evaluate_compare_scenario(
                    conn,
                    scenario,
                    project_dir=project_dir,
                    config=config,
                )
            )
    finally:
        conn.close()
        set_skip_rolling_scores(False)

    passed = sum(1 for case in cases if case.passed)
    return BenchSuiteResult(suite="compare", passed=passed, total=len(cases), cases=cases)


def format_compare_summary(result: BenchSuiteResult) -> str:
    """Aggregate with/without savings line for compare suite output."""
    if result.suite != "compare" or not result.cases:
        return ""
    reductions: list[float] = []
    ratios: list[float] = []
    for case in result.cases:
        if "reduction=" in case.detail:
            fragment = case.detail.split("reduction=", maxsplit=1)[1]
            pct_text = fragment.split("%", maxsplit=1)[0]
            try:
                reductions.append(float(pct_text) / 100.0)
            except ValueError:
                continue
        if "savings=" in case.detail:
            fragment = case.detail.split("savings=", maxsplit=1)[1]
            token = fragment.split(maxsplit=1)[0]
            if token.endswith("x"):
                try:
                    ratios.append(float(token[:-1]))
                except ValueError:
                    continue
    if not reductions:
        return ""
    avg = sum(reductions) / len(reductions)
    parts = [f"Average with-vs-without reduction: {avg:.0%} across {len(reductions)} scenarios"]
    if ratios:
        avg_ratio = sum(ratios) / len(ratios)
        parts.append(f"(~{avg_ratio:.1f}x fewer tokens with brain)")
    return " ".join(parts)
