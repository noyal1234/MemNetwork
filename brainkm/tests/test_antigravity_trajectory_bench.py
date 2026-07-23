"""Honest pack-vs-dump labeling for antigravity_trajectory_bench."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "antigravity_trajectory_bench.py"


def _load_bench():
    import sys

    name = "antigravity_trajectory_bench"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # dataclasses need the module registered before @dataclass runs
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_generate_markdown_marks_failed_dump_incomparable() -> None:
    bench = _load_bench()
    dump = bench.PackVsDumpRecord(
        scenario_id="agy_arch_pivot",
        scenario_title="t",
        arm="dump",
        dump_or_pack_tokens=10000,
        prompt_tokens=10000,
        completion_tokens=0,
        total_tokens=10000,
        wall_ms=100.0,
        status="error:rate_limited",
        decision_hit=None,
        response_preview="",
        mode="llm",
    )
    pack = bench.PackVsDumpRecord(
        scenario_id="agy_arch_pivot",
        scenario_title="t",
        arm="pack",
        dump_or_pack_tokens=900,
        prompt_tokens=950,
        completion_tokens=100,
        total_tokens=1050,
        wall_ms=1200.0,
        status="finished",
        decision_hit=True,
        response_preview="agy rules groq",
        mode="llm",
    )
    extra: list = []
    for sid in ("agy_ast_refactor", "agy_git_join"):
        for arm, n in (("dump", 5000), ("pack", 800)):
            extra.append(
                bench.PackVsDumpRecord(
                    scenario_id=sid,
                    scenario_title="t",
                    arm=arm,
                    dump_or_pack_tokens=n,
                    prompt_tokens=n,
                    completion_tokens=None,
                    total_tokens=n,
                    wall_ms=0.0,
                    status="tokens_only",
                    decision_hit=None,
                    response_preview="",
                    mode="tokens-only",
                )
            )
    card = bench.PackVsDumpScorecard(records=[dump, pack, *extra], driver="groq", mode="llm")
    md = bench.generate_markdown(card)
    assert "pack-vs-dump" in md.lower()
    assert "does **not** drive Google Antigravity IDE" in md
    assert "not comparable" in md
    assert "-524" not in md


def test_tokens_only_scorecard_has_no_fake_hops() -> None:
    bench = _load_bench()
    records: list = []
    for sid in ("agy_arch_pivot", "agy_ast_refactor", "agy_git_join"):
        for arm, n in (("dump", 10000), ("pack", 900)):
            records.append(
                bench.PackVsDumpRecord(
                    scenario_id=sid,
                    scenario_title="t",
                    arm=arm,
                    dump_or_pack_tokens=n,
                    prompt_tokens=n,
                    completion_tokens=None,
                    total_tokens=n,
                    wall_ms=0.0,
                    status="tokens_only",
                    decision_hit=None,
                    response_preview="",
                    mode="tokens-only",
                )
            )
    md = bench.generate_markdown(
        bench.PackVsDumpScorecard(records=records, driver="none", mode="tokens-only")
    )
    assert "Dump → pack size reduction" in md
    assert "5 turns" not in md
    assert "0 Hops" not in md
