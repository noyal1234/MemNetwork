"""Tests for the first-run Wizard screen."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from brainkm.tui.app import BrainkmConfigureApp
from brainkm.tui.screens.wizard import (
    STEP_APIKEY,
    STEP_CLIENT,
    STEP_CURSOR_CLI,
    STEP_DISTILL,
    STEP_INSTALL,
    STEP_PROJECT,
    STEP_SEMANTIC,
    STEP_VIZ_LLM,
    STEPS,
    format_client_tips,
    format_install_description,
)


def test_format_install_description_lists_only_selected_apps() -> None:
    single = format_install_description(["cursor"], shared=False)
    assert "Cursor → .cursor/hooks.json" in single
    assert "Claude" not in single
    assert "Codex" not in single
    assert "extra terminal" in single

    shared = format_install_description(["cursor", "antigravity", "codex"], shared=True)
    assert "share one brain" in shared
    assert "Cursor → .cursor/hooks.json" in shared
    assert "Antigravity → .agents/" in shared
    assert "Codex → .codex/config.toml" in shared
    assert "Claude" not in shared


def test_format_client_tips_covers_claude_codex_antigravity() -> None:
    tips = format_client_tips(["cursor", "codex", "claude", "antigravity"])
    assert "Claude Code" in tips
    assert "Codex" in tips
    assert "/hooks" in tips
    assert "serverUrl" in tips
    assert format_client_tips(["cursor"]) == ""


def test_detect_wired_clients_finds_cursor_and_antigravity(tmp_path: Path) -> None:
    from brainkm.services.connect import detect_wired_clients

    assert detect_wired_clients(tmp_path) == []
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "hooks.json").write_text("{}", encoding="utf-8")
    assert detect_wired_clients(tmp_path) == ["cursor", "antigravity"]


async def test_wizard_preselects_already_wired_apps(tmp_path: Path) -> None:
    """Re-run must tick Cursor+Antigravity when both are already on disk — not Cursor-only."""
    from textual.widgets import Checkbox

    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "mcp_config.json").write_text('{"mcpServers":{}}', encoding="utf-8")

    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert STEPS[screen._current_step] == STEP_CLIENT
        assert screen._selected_apps == ["cursor", "antigravity"]
        assert screen._shared_mode is True
        assert screen.query_one("#wizard-app-cursor", Checkbox).value is True
        assert screen.query_one("#wizard-app-antigravity", Checkbox).value is True
        assert screen.query_one("#wizard-app-claude", Checkbox).value is False
        assert screen.query_one("#wizard-app-codex", Checkbox).value is False
        # No "recommended" marketing on Cursor.
        label = str(screen.query_one("#wizard-app-cursor", Checkbox).label)
        assert "recommended" not in label.lower()


async def test_wizard_is_initial_screen_for_fresh_project(tmp_path: Path) -> None:
    """`_check_project` (step 0) auto-advances on mount → land on agent client."""
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert screen._current_step == STEPS.index(STEP_CLIENT)
        assert STEPS[screen._current_step] == STEP_CLIENT


async def test_wizard_client_then_install_scaffolds_project(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        assert STEPS[app.screen._current_step] == STEP_CLIENT

        await pilot.click("#btn-wizard-run")  # confirm default cursor client
        await pilot.pause(0.3)
        assert STEPS[app.screen._current_step] == STEP_INSTALL
        assert app.screen._client == "cursor"

        await pilot.click("#btn-wizard-run")  # runs install
        await pilot.pause(2.0)

        screen = app.screen
        assert STEPS[screen._current_step] == "step-doctor"
        assert (tmp_path / ".brain").is_dir()
        assert (tmp_path / ".cursor" / "hooks.json").is_file()
        cfg = json.loads((tmp_path / ".brain" / "config.json").read_text(encoding="utf-8"))
        assert cfg["capture"]["auto_observe"] is True
        assert cfg["mcp"]["transport"] == "stdio"


async def test_wizard_claude_client_install(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert STEPS[screen._current_step] == STEP_CLIENT

        from textual.widgets import Checkbox

        # Switch from Cursor-only to Claude-only via checkboxes.
        screen.query_one("#wizard-app-cursor", Checkbox).value = False
        screen.query_one("#wizard-app-claude", Checkbox).value = True
        await pilot.pause(0.1)

        await pilot.click("#btn-wizard-run")
        await pilot.pause(0.3)
        assert screen._client == "claude"
        assert STEPS[screen._current_step] == STEP_INSTALL

        await pilot.click("#btn-wizard-run")
        await pilot.pause(2.0)

        assert (tmp_path / ".brain").is_dir()
        assert (tmp_path / ".claude" / "settings.json").is_file()
        assert (tmp_path / "CLAUDE.md").is_file()
        cfg = json.loads((tmp_path / ".brain" / "config.json").read_text(encoding="utf-8"))
        assert cfg["capture"]["auto_observe"] is True


async def test_wizard_multi_app_uses_shared_http(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        from textual.widgets import Checkbox

        screen.query_one("#wizard-app-claude", Checkbox).value = True
        await pilot.click("#btn-wizard-run")
        await pilot.pause(0.3)
        assert screen._shared_mode is True
        assert screen._selected_apps == ["cursor", "claude"]

        await pilot.click("#btn-wizard-run")
        await pilot.pause(2.5)

        cfg = json.loads((tmp_path / ".brain" / "config.json").read_text(encoding="utf-8"))
        assert cfg["mcp"]["transport"] == "http"
        assert cfg["capture"]["auto_observe"] is True
        assert (tmp_path / ".cursor" / "mcp.json").is_file()
        assert (tmp_path / ".mcp.json").is_file()


async def test_wizard_install_description_matches_selected_apps(
    tmp_path: Path,
) -> None:
    """Step 3 copy reflects checkboxes (incl. Codex), not a hardcoded trio."""
    from textual.widgets import Checkbox, Static

    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert STEPS[screen._current_step] == STEP_CLIENT

        screen.query_one("#wizard-app-antigravity", Checkbox).value = True
        screen.query_one("#wizard-app-codex", Checkbox).value = True
        await pilot.click("#btn-wizard-run")
        await pilot.pause(0.3)

        assert screen._selected_apps == ["cursor", "antigravity", "codex"]
        assert screen._shared_mode is True
        assert STEPS[screen._current_step] == STEP_INSTALL

        desc = str(screen.query_one("#wizard-install-description", Static).content)
        assert "Codex → .codex/config.toml" in desc
        assert "Antigravity → .agents/" in desc
        assert "Cursor → .cursor/hooks.json" in desc
        assert "Claude" not in desc


async def test_wizard_distill_mode_selection_writes_config(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        # client -> install -> doctor -> semantic
        for _ in range(4):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        screen = app.screen
        assert STEPS[screen._current_step] == STEP_DISTILL
        assert screen._distill_mode == "cursor"

        from textual.widgets import RadioSet

        radio_set = screen.query_one("#wizard-distill-radio", RadioSet)
        radio_set.focus()
        # Order: cursor, claude, antigravity, codex, ollama, groq
        radio_set.action_next_button()
        radio_set.action_toggle_button()
        await pilot.pause(0.1)

        await pilot.click("#btn-wizard-run")
        await pilot.pause(0.5)

        cfg_path = tmp_path / ".brain" / "config.json"
        saved = json.loads(cfg_path.read_text())
        assert saved["capture"]["distill_mode"] == "claude"
        # Agent CLI is skipped for non-cursor distill → land on API key
        assert STEPS[screen._current_step] == STEP_APIKEY


async def test_wizard_semantic_skip_advances(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        # client, install, doctor → semantic
        for _ in range(3):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        screen = app.screen
        assert STEPS[screen._current_step] == STEP_SEMANTIC
        await pilot.click("#btn-wizard-skip")
        await pilot.pause(0.3)
        assert STEPS[screen._current_step] == STEP_DISTILL


async def test_wizard_cursor_cli_skip_advances(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        # client, install, doctor, semantic, distill (default cursor)
        for _ in range(5):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        screen = app.screen
        assert STEPS[screen._current_step] == STEP_CURSOR_CLI

        await pilot.click("#btn-wizard-skip")
        await pilot.pause(0.2)
        assert STEPS[screen._current_step] == STEP_APIKEY


async def test_wizard_cursor_cli_run_with_mocked_install(tmp_path: Path) -> None:
    from brainkm.services.cursor_advisor import CursorInstallResult, CursorStatus

    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        for _ in range(5):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        screen = app.screen
        assert STEPS[screen._current_step] == STEP_CURSOR_CLI

        with (
            patch(
                "brainkm.services.cursor_advisor.probe_cursor_agent",
                side_effect=[
                    CursorStatus(found=False),
                    CursorStatus(
                        found=True,
                        bin_path="/tmp/fake-agent",
                        bin_name="agent",
                    ),
                    CursorStatus(
                        found=True,
                        bin_path="/tmp/fake-agent",
                        bin_name="agent",
                    ),
                ],
            ),
            patch(
                "brainkm.services.cursor_advisor.install_cursor_agent_cli",
                return_value=CursorInstallResult(
                    ok=True,
                    found=True,
                    bin_path="/tmp/fake-agent",
                    stdout_tail="ok",
                ),
            ),
        ):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        assert STEPS[screen._current_step] == STEP_APIKEY


async def test_wizard_skip_advances_without_running(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        assert STEPS[app.screen._current_step] == STEP_CLIENT

        await pilot.click("#btn-wizard-skip")
        await pilot.pause(0.2)
        assert STEPS[app.screen._current_step] == STEP_INSTALL


def test_wizard_step_ids_are_unique() -> None:
    assert len(STEPS) == len(set(STEPS))
    assert STEP_PROJECT in STEPS
    assert STEP_CLIENT in STEPS
    assert STEP_INSTALL in STEPS
    assert STEP_SEMANTIC in STEPS
    assert STEP_DISTILL in STEPS
    assert STEP_CURSOR_CLI in STEPS
    assert STEP_VIZ_LLM in STEPS
    assert STEPS.index(STEP_CLIENT) == STEPS.index(STEP_PROJECT) + 1
    assert STEPS.index(STEP_INSTALL) == STEPS.index(STEP_CLIENT) + 1
    assert STEPS.index(STEP_SEMANTIC) == STEPS.index("step-doctor") + 1
    assert STEPS.index(STEP_DISTILL) == STEPS.index(STEP_SEMANTIC) + 1
    assert STEPS.index(STEP_CURSOR_CLI) == STEPS.index(STEP_DISTILL) + 1
    assert STEPS[-2] == STEP_VIZ_LLM
    assert STEPS[-1] == "step-done"


async def test_wizard_viz_llm_skip_advances(tmp_path: Path) -> None:
    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        screen._current_step = STEPS.index(STEP_VIZ_LLM)
        screen._update_step_visibility()
        await pilot.pause(0.1)

        await pilot.click("#btn-wizard-skip")
        await pilot.pause(0.2)
        assert screen._current_step == STEPS.index("step-done")


async def test_wizard_viz_llm_run_uses_prefetch_mock(tmp_path: Path) -> None:
    from brainkm.services.webllm_prefetch import PrefetchResult

    app = BrainkmConfigureApp(project_dir=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        await pilot.pause(0.3)
        (tmp_path / ".brain").mkdir(exist_ok=True)
        (tmp_path / ".brain" / "config.json").write_text("{}", encoding="utf-8")

        screen = app.screen
        screen._current_step = STEPS.index(STEP_VIZ_LLM)
        screen._update_step_visibility()
        await pilot.pause(0.1)

        fake = PrefetchResult(
            model_id="Llama-3.2-1B-Instruct-q4f16_1-MLC",
            cache_dir=tmp_path / "cache",
            files_downloaded=3,
            files_skipped=0,
            bytes_downloaded=1024 * 1024,
            already_cached=False,
        )
        with patch(
            "brainkm.services.webllm_prefetch.prefetch_webllm_model",
            return_value=fake,
        ):
            await pilot.click("#btn-wizard-run")
            await pilot.pause(1.5)

        cfg = json.loads((tmp_path / ".brain" / "config.json").read_text())
        assert cfg["viz"]["webllm_model"] == "Llama-3.2-1B-Instruct-q4f16_1-MLC"
        assert screen._current_step == STEPS.index("step-done")
