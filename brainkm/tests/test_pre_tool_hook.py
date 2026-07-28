"""Tests for PreToolUse context_pack hook."""

import json

from brainkm.db.connection import connect
from brainkm.models.brain_config import BrainConfig
from brainkm.services.hooks import run_pre_tool_use
from tests.conftest import insert_node


def test_pre_tool_use_skips_without_seed(brain_db) -> None:
    project_dir = brain_db.parent.parent
    payload = json.dumps({"tool_name": "Shell", "tool_input": {}})
    result = run_pre_tool_use(payload, project_dir=project_dir, config=BrainConfig())
    assert result.skipped is True
    assert result.reason == "no meaningful pre-tool seed"


def test_pre_tool_use_injects_context_pack(brain_db) -> None:
    project_dir = brain_db.parent.parent
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="auth",
            subtype="decision",
            title="JWT middleware path",
            content="See src/auth/middleware.py",
        )
        conn.commit()
    finally:
        conn.close()

    payload = json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {"path": "src/auth/middleware.py"},
            "session_id": "sess-1",
        }
    )
    result = run_pre_tool_use(payload, project_dir=project_dir, config=BrainConfig())
    assert result.skipped is False
    assert result.additional_context is not None
    assert "Context pack" in result.additional_context


def test_pre_tool_use_records_hits_from_included_ids_not_neurons(brain_db) -> None:
    """Regression: pack.neurons is empty without include_structured; hits must still land."""
    project_dir = brain_db.parent.parent
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="auth-decision",
            subtype="decision",
            title="JWT middleware path",
            content="Auth lives in src/auth/middleware.py",
        )
        conn.commit()
    finally:
        conn.close()

    payload = json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/auth/middleware.py"},
            "session_id": "hit-counter-sess",
        }
    )
    result = run_pre_tool_use(payload, project_dir=project_dir, config=BrainConfig())
    assert result.skipped is False
    assert "Decisions" in (result.additional_context or "") or "JWT" in (
        result.additional_context or ""
    )

    conn = connect(brain_db)
    try:
        rows = conn.execute(
            """
            SELECT node_id FROM session_activity
            WHERE session_id = ? AND kind = 'neuron_hit' AND source = 'pre_tool'
            """,
            ("hit-counter-sess",),
        ).fetchall()
        assert "auth-decision" in {row[0] for row in rows}
        # Structured neurons array stays empty on the hook path.
        from brainkm.services.context_pack import compile_pre_tool_pack

        pack = compile_pre_tool_pack(
            conn,
            json.loads(payload),
            config=BrainConfig(),
            project_dir=project_dir,
        )
        assert pack is not None
        assert pack.neurons == []
        assert "auth-decision" in pack.truncation.included_ids
    finally:
        conn.close()


def test_pre_tool_use_records_procedure_hits_from_included_ids(brain_db) -> None:
    """Procedures in packs must get neuron_hit rows (hygiene ignore_rate depends on it)."""
    project_dir = brain_db.parent.parent
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="proc-edit-shell",
            kind="procedure",
            subtype="tool_chain",
            title="Edit → Shell",
            content="Tools: Edit → Shell\n\n1. Edit\n2. Shell\nRelated: src/auth/middleware.py",
        )
        conn.commit()
    finally:
        conn.close()

    payload = json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/auth/middleware.py"},
            "session_id": "proc-hit-sess",
        }
    )
    result = run_pre_tool_use(payload, project_dir=project_dir, config=BrainConfig())
    assert result.skipped is False

    conn = connect(brain_db)
    try:
        rows = conn.execute(
            """
            SELECT node_id FROM session_activity
            WHERE session_id = ? AND kind = 'neuron_hit' AND source = 'pre_tool'
            """,
            ("proc-hit-sess",),
        ).fetchall()
        assert "proc-edit-shell" in {row[0] for row in rows}
    finally:
        conn.close()


def test_pre_tool_shell_with_path_seed_injects(brain_db) -> None:
    project_dir = brain_db.parent.parent
    conn = connect(brain_db)
    try:
        insert_node(
            conn,
            node_id="hooks-fact",
            subtype="fact",
            title="hooks.py PreToolUse",
            content="Shell packs seed from source paths in commands",
        )
        conn.commit()
    finally:
        conn.close()

    payload = json.dumps(
        {
            "tool_name": "Shell",
            "tool_input": {"command": "rg persist_neuron_hits brainkm/brainkm/services/hooks.py"},
            "session_id": "shell-pack-sess",
        }
    )
    result = run_pre_tool_use(payload, project_dir=project_dir, config=BrainConfig())
    assert result.skipped is False
    assert result.additional_context is not None


def test_pre_tool_shell_noise_command_skips(brain_db) -> None:
    project_dir = brain_db.parent.parent
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "wc -l"},
            "session_id": "shell-noise-sess",
        }
    )
    result = run_pre_tool_use(payload, project_dir=project_dir, config=BrainConfig())
    assert result.skipped is True
    assert result.reason == "no meaningful pre-tool seed"
