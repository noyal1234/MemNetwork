"""Compression pipeline, polarity rubric, metrics, cohort, session dedup."""

from __future__ import annotations

from pathlib import Path

from brainkm.models.brain_config import CompressionConfig
from brainkm.services.bench_db import cleanup_ephemeral_project, ephemeral_project_brain
from brainkm.services.budget import BudgetLine
from brainkm.services.compression.cohort import assign_session_cohort
from brainkm.services.compression.metrics import (
    bump_window_seconds,
    context_rot_stats,
    hit_bands_from_gaps,
    mode_a_lifetime_cost,
    mode_a_write_cost,
    warm_credit_tokens,
)
from brainkm.services.compression.net_session import (
    estimate_net_session,
    should_auto_disable_terse,
)
from brainkm.services.compression.pipeline import compress_text
from brainkm.services.compression.polarity import grade_egress, meets_answerability_bar
from brainkm.services.compression.protect import find_protected_spans
from brainkm.services.compression.rtk_lite import compress_tool_log, looks_like_tool_log
from brainkm.services.compression.session_dedup import filter_already_injected
from brainkm.services.memory import remember_neuron
from brainkm.services.session_activity import record_neuron_activity


def test_protect_spans_keep_urls_and_paths():
    text = "See https://example.com/a and path foo/bar.py must not break."
    spans = find_protected_spans(text)
    kinds = {s.kind for s in spans}
    assert kinds & {"url", "path", "obligation"}


def test_rtk_lite_collapses_passes_and_tees_failures(tmp_path: Path):
    log = "\n".join(
        [
            "running 10 tests",
            "test_a ... ok",
            "test_b ... ok",
            "test_c ... FAILED",
            "AssertionError: boom",
            "FAILED test_c",
        ]
    )
    assert looks_like_tool_log(log)
    result = compress_tool_log(log, project_dir=tmp_path)
    # Body must compress (guard ignores tee pointer); tiny logs + tee may
    # still have tokens_out > tokens_in in the final StageResult.
    assert result.skipped_reason is None
    assert result.tee_path is not None
    tee = Path(result.tee_path)
    if not tee.is_absolute():
        tee = tmp_path / tee
    assert tee.is_file()
    assert "FAILED" in result.text or "fail" in result.text.lower()
    assert "ok collapsed: 2" in result.text
    assert "test_a" not in result.text
    assert "[full output:" in result.text


def test_rtk_lite_collapses_pytest_passed_rows(tmp_path: Path):
    """Pure rtk_lite must collapse pytest -v PASSED lines (not only ... ok)."""
    rows = [f"tests/test_foo.py::test_{i} PASSED" for i in range(20)]
    log = "\n".join(
        [
            "============================= test session starts ==============================",
            "collected 21 items",
            *rows,
            "tests/test_foo.py::test_boom FAILED",
            "E       AssertionError: boom",
            "=========================== short test summary info ============================",
            "FAILED tests/test_foo.py::test_boom - AssertionError: boom",
            "======================== 1 failed, 20 passed in 0.42s =========================",
        ]
    )
    assert looks_like_tool_log(log)
    result = compress_tool_log(log, project_dir=tmp_path)
    assert result.skipped_reason is None
    assert result.tokens_out < result.tokens_in
    assert "ok collapsed: 20" in result.text
    assert "test_0 PASSED" not in result.text
    assert "test_boom FAILED" in result.text
    # Summary with counts must survive (not treated as a pass row).
    assert "1 failed, 20 passed" in result.text
    assert result.tee_path is not None


def test_rtk_lite_all_pass_pytest_no_tee(tmp_path: Path):
    rows = [f"tests/test_bar.py::test_{i} PASSED [ {i * 5:2d}%]" for i in range(12)]
    log = "\n".join(["running 12 tests", *rows, "12 passed in 0.10s"])
    result = compress_tool_log(log, project_dir=tmp_path)
    assert result.skipped_reason is None
    assert "ok collapsed: 12" in result.text
    assert result.tee_path is None
    assert "12 passed in" in result.text


def test_pipeline_does_not_lossy_rewrite_decision_store():
    body = "We must not use Redis. Prefer SQLite for local brains."
    result = compress_text(
        body,
        kind="memory",
        subtype="decision",
        allow_decision_lossy=False,
        config=CompressionConfig(prose_intensity="full"),
    )
    assert "must not" in result.text.lower()
    assert "redis" in result.text.lower()


def test_polarity_rubric_catches_negation_drop():
    full = "Agents must not commit secrets. Prefer redaction."
    bad = "Agents must commit secrets. Prefer redaction."
    result = grade_egress(full, bad)
    assert not meets_answerability_bar(full, bad, min_pct=95.0)
    assert any(not c.passed for c in result.checks)


def test_polarity_rubric_passes_intact():
    full = "Agents must not commit secrets. Prefer redaction via remember_neuron."
    assert meets_answerability_bar(full, full, min_pct=95.0)


def test_ttl_warm_credit_and_lifetime():
    assert warm_credit_tokens(100, gap_since_activity=60, ttl_seconds=300) == 100
    assert warm_credit_tokens(100, gap_since_activity=400, ttl_seconds=300) == 0
    write = mode_a_write_cost(1000)
    life = mode_a_lifetime_cost(1000, [1000, 1000])
    assert life.total > write
    bands = hit_bands_from_gaps([30.0, 60.0, 400.0], ttl_seconds=300)
    assert bands.n_samples == 3
    assert 0 < bands.p_warm < 1


def test_bump_window_from_p95():
    window = bump_window_seconds([100, 200, 1000], [50, 50], cache_ttl=300)
    assert window.n_seconds >= 300
    assert window.n_seconds >= window.p95_session_duration


def test_context_rot_reinject_rate():
    stats = context_rot_stats(
        injected_neuron_ids_per_turn=[["a", "b"], ["a", "c"], ["a"]],
        token_by_neuron={"a": 10, "b": 10, "c": 10},
    )
    assert stats.redundant_reinject_rate > 0
    assert 0 < stats.unique_neuron_token_density <= 1.0


def test_sticky_cohort():
    conn, _db, project = ephemeral_project_brain()
    try:
        cfg = CompressionConfig(
            canary_pct=1.0,
            canary_engine_version="2",
            engine_version="1",
        )
        v1, c1 = assign_session_cohort(conn, "sess-1", cfg)
        v2, c2 = assign_session_cohort(conn, "sess-1", cfg)
        assert (v1, c1) == (v2, c2)
        assert v1 == "2"
        assert c1 is True
        conn.commit()
    finally:
        cleanup_ephemeral_project(project, conn)


def test_session_dedup_suppresses_reinject():
    conn, _db, project = ephemeral_project_brain()
    try:
        n = remember_neuron(
            conn,
            title="Fact",
            content="hello",
            subtype="fact",
            session_id="s1",
        )
        record_neuron_activity(conn, "s1", [n.id], source="pre_tool")
        conn.commit()
        lines = [
            BudgetLine(
                node_id=n.id,
                kind="memory",
                subtype="fact",
                title="Fact",
                content="hello",
                tokens=5,
                priority=3,
            ),
            BudgetLine(
                node_id="other",
                kind="memory",
                subtype="fact",
                title="Other",
                content="x",
                tokens=3,
                priority=3,
            ),
        ]
        kept, suppressed = filter_already_injected(lines, conn=conn, session_id="s1")
        assert n.id in suppressed
        assert any(line.node_id == "other" for line in kept)
    finally:
        cleanup_ephemeral_project(project, conn)


def test_determinism_same_inputs():
    text = "git status\n?? a.py\n M b.py\ncollecting packages\n"
    a = compress_text(text, kind="memory", subtype="observation")
    b = compress_text(text, kind="memory", subtype="observation")
    assert a.text == b.text


def test_net_session_auto_disable():
    net = estimate_net_session(
        assistant_messages=["ok"],
        injected_packs=["pack"],
        skill_enabled=True,
    )
    assert net.likely_net_negative
    assert should_auto_disable_terse(turns=2, baseline_net=100, terse_net=200)


def test_remember_observation_uses_pipeline():
    conn, _db, project = ephemeral_project_brain()
    try:
        body = "\n".join(["running 5 tests"] + [f"test_{i} ... ok" for i in range(8)])
        rec = remember_neuron(
            conn,
            title="pytest",
            content=body + "\n" + body,
            subtype="observation",
            compress=True,
            max_body_tokens=80,
            session_id="s",
        )
        assert rec.content is not None
    finally:
        cleanup_ephemeral_project(project, conn)


def test_dual_store_view_expires_after_ttl():
    from brainkm.services.compression.dual_store import get_compressed_view, put_compressed_view

    conn, _db, project = ephemeral_project_brain()
    try:
        put_compressed_view(
            conn,
            neuron_id="n1",
            full_body="full body text",
            compressed_text="short",
            engine_version="1",
            intensity="lite",
        )
        conn.commit()

        # Fresh row: well within a generous TTL.
        assert (
            get_compressed_view(
                conn,
                neuron_id="n1",
                full_body="full body text",
                engine_version="1",
                intensity="lite",
                ttl_seconds=300.0,
            )
            == "short"
        )

        # Backdate created_at past a short TTL to simulate an expired entry.
        conn.execute(
            "UPDATE compression_views SET created_at = '2000-01-01T00:00:00+00:00' "
            "WHERE neuron_id = 'n1'"
        )
        conn.commit()

        assert (
            get_compressed_view(
                conn,
                neuron_id="n1",
                full_body="full body text",
                engine_version="1",
                intensity="lite",
                ttl_seconds=60.0,
            )
            is None
        )
        # Expired row should be purged, not just skipped.
        row = conn.execute(
            "SELECT COUNT(*) FROM compression_views WHERE neuron_id = 'n1'"
        ).fetchone()
        assert row[0] == 0

        # No ttl_seconds passed: never expires, regardless of age.
        put_compressed_view(
            conn,
            neuron_id="n2",
            full_body="full body text",
            compressed_text="short",
            engine_version="1",
            intensity="lite",
        )
        conn.execute(
            "UPDATE compression_views SET created_at = '2000-01-01T00:00:00+00:00' "
            "WHERE neuron_id = 'n2'"
        )
        conn.commit()
        assert (
            get_compressed_view(
                conn,
                neuron_id="n2",
                full_body="full body text",
                engine_version="1",
                intensity="lite",
            )
            == "short"
        )
    finally:
        cleanup_ephemeral_project(project, conn)
