"""brainkm install — write Cursor MCP config, hooks, rules, and brain scaffolding."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.db.paths import brain_db_path, brain_dir
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.config_loader import example_config_path
from brainkm.services.graph_import import import_project_graph
from brainkm.services.hooks import pre_tool_matcher

logger = get_logger("services.install")

CURSOR_MIN_VERSION_NOTE = "0.46"
BRAINKM_MCP_SERVER_KEY = "brainkm"
# Cursor does not implement postCompact (use preCompact handover + sessionStart instead).
# postToolUseFailure is Claude-oriented; Cursor surfaces failures on postToolUse payloads.
CURSOR_UNSUPPORTED_HOOK_EVENTS = frozenset({"postCompact", "postToolUseFailure"})
GITIGNORE_ENTRIES = (
    ".brain/brain.db",
    ".brain/brain.db-wal",
    ".brain/brain.db-shm",
    "graphify-out/",
)
RULE_OVERLAP_KEYWORDS = (
    "project brain",
    "brainkm",
    "memnetwork",
    "remember",
    "recall",
    "context_pack",
)


@dataclass
class InstallResult:
    project_dir: Path
    files_written: list[Path] = field(default_factory=list)
    files_skipped: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def resolve_project_dir(project_dir: Path | None) -> Path:
    return (project_dir if project_dir is not None else Path.cwd()).resolve()


def resolve_brainkm_command(*, dev: bool) -> tuple[str, list[str]]:
    """Return MCP (command, args) for mcp.json.

    Dev/private: absolute venv ``brainkm``. Until PyPI publish (deferred while the
    repo is private), production installs prefer a PATH ``brainkm``; ``uvx`` is only
    a placeholder for the future public zero-clone path.
    """
    if dev:
        brainkm_bin = Path(sys.executable).resolve().parent / "brainkm"
        return str(brainkm_bin), ["mcp", "--project-dir", "."]
    found = shutil.which("brainkm")
    if found:
        return found, ["mcp", "--project-dir", "."]
    # Deferred: requires public PyPI package. Prefer ``brainkm install --dev`` today.
    return "uvx", ["brainkm@latest", "mcp", "--project-dir", "."]


def resolve_hook_command(*, dev: bool) -> str:
    """Absolute or PATH-resolved brainkm binary for hook subprocesses."""
    if dev:
        return str(Path(sys.executable).resolve().parent / "brainkm")
    found = shutil.which("brainkm")
    if found:
        return found
    return "brainkm"


def build_hooks_config(
    brainkm_bin: str,
    *,
    config: BrainConfig | None = None,
) -> dict[str, object]:
    cfg = config or BrainConfig()
    matcher = pre_tool_matcher(cfg.injection.pre_tool_patterns)
    return {
        "version": 1,
        "hooks": {
            "sessionStart": [
                {
                    "command": f"{brainkm_bin} session-start --stdin",
                    "timeout": 30,
                }
            ],
            "sessionEnd": [
                {
                    "command": f"{brainkm_bin} session-end --stdin",
                    "timeout": 120,
                }
            ],
            "preCompact": [
                {
                    "matcher": "auto",
                    "command": f"{brainkm_bin} handover --stdin",
                    "timeout": 30,
                }
            ],
            "preToolUse": [
                {
                    "matcher": matcher,
                    "command": f"{brainkm_bin} pre-tool --stdin",
                    "timeout": 15,
                }
            ],
            "postToolUse": [
                {
                    "matcher": "Write|Edit|Shell",
                    "command": f"{brainkm_bin} post-tool --stdin",
                    "timeout": 5,
                }
            ],
            "userPromptSubmit": [
                {
                    "command": f"{brainkm_bin} user-prompt --stdin",
                    "timeout": 5,
                }
            ],
            "postToolUseFailure": [
                {
                    "command": f"{brainkm_bin} post-tool-failure --stdin",
                    "timeout": 5,
                }
            ],
        },
    }


def _claude_hook_command(brainkm_bin: str, *args: str, timeout: int | None = None) -> dict[str, object]:
    """One Claude Code command-hook entry (nested under matcher groups)."""
    cmd = f"{brainkm_bin} {' '.join(args)} --client claude"
    entry: dict[str, object] = {"type": "command", "command": cmd}
    if timeout is not None:
        entry["timeout"] = timeout
    return entry


def _claude_event_group(
    *handlers: dict[str, object],
    matcher: str | None = None,
) -> list[dict[str, object]]:
    group: dict[str, object] = {"hooks": list(handlers)}
    if matcher is not None:
        group["matcher"] = matcher
    return [group]


def build_claude_hooks_config(
    brainkm_bin: str,
    *,
    config: BrainConfig | None = None,
) -> dict[str, object]:
    """Claude Code hooks fragment for ``.claude/settings.json`` (PascalCase + nested)."""
    cfg = config or BrainConfig()
    matcher = pre_tool_matcher(cfg.injection.pre_tool_patterns)
    # Claude uses Bash instead of Shell for the terminal tool.
    claude_matcher = matcher.replace("Shell", "Bash") if matcher else "Write|Edit|Bash"
    return {
        "hooks": {
            "SessionStart": _claude_event_group(
                _claude_hook_command(brainkm_bin, "session-start", "--stdin", timeout=30),
            ),
            "SessionEnd": _claude_event_group(
                _claude_hook_command(brainkm_bin, "session-end", "--stdin", timeout=120),
            ),
            "PreCompact": _claude_event_group(
                _claude_hook_command(brainkm_bin, "handover", "--stdin", timeout=30),
                matcher="manual|auto",
            ),
            "PostCompact": _claude_event_group(
                _claude_hook_command(brainkm_bin, "post-compact", "--stdin", timeout=30),
            ),
            "PreToolUse": _claude_event_group(
                _claude_hook_command(brainkm_bin, "pre-tool", "--stdin", timeout=15),
                matcher=claude_matcher,
            ),
            "PostToolUse": _claude_event_group(
                _claude_hook_command(brainkm_bin, "post-tool", "--stdin", timeout=15),
            ),
            "PostToolUseFailure": _claude_event_group(
                _claude_hook_command(brainkm_bin, "post-tool-failure", "--stdin", timeout=15),
            ),
            "UserPromptSubmit": _claude_event_group(
                _claude_hook_command(brainkm_bin, "user-prompt", "--stdin", timeout=15),
            ),
            "SubagentStart": _claude_event_group(
                _claude_hook_command(brainkm_bin, "subagent-start", "--stdin", timeout=30),
            ),
            "SubagentStop": _claude_event_group(
                _claude_hook_command(brainkm_bin, "subagent-stop", "--stdin", timeout=60),
            ),
            "Stop": _claude_event_group(
                _claude_hook_command(brainkm_bin, "agent-stop", "--stdin", timeout=15),
            ),
        },
    }


def _command_contains_brainkm(command: str) -> bool:
    return "brainkm" in command


def _claude_group_has_brainkm(group: object) -> bool:
    if not isinstance(group, dict):
        return False
    hooks = group.get("hooks")
    if not isinstance(hooks, list):
        return False
    for item in hooks:
        if isinstance(item, dict) and _command_contains_brainkm(str(item.get("command", ""))):
            return True
    return False


def _merge_claude_event_groups(
    existing: list[object],
    incoming: list[object],
) -> list[object]:
    """Keep foreign matcher groups; replace prior brainkm groups with incoming."""
    kept = [row for row in existing if not _claude_group_has_brainkm(row)]
    for row in incoming:
        if isinstance(row, dict):
            kept.append(row)
    return kept


def merge_claude_settings_hooks(
    existing_settings: dict[str, object],
    incoming_hooks: dict[str, object],
) -> dict[str, object]:
    """Merge brainkm hooks into Claude ``.claude/settings.json`` without clobbering other keys."""
    merged = dict(existing_settings)
    incoming = incoming_hooks.get("hooks")
    if not isinstance(incoming, dict):
        return merged

    existing_hooks = merged.get("hooks")
    hooks_out: dict[str, object] = (
        dict(existing_hooks) if isinstance(existing_hooks, dict) else {}
    )
    for event, groups in incoming.items():
        if not isinstance(groups, list):
            continue
        current = hooks_out.get(event)
        if isinstance(current, list):
            hooks_out[event] = _merge_claude_event_groups(current, groups)
        else:
            hooks_out[event] = list(groups)
    merged["hooks"] = hooks_out
    return merged


def write_claude_settings_hooks(
    settings_path: Path,
    brainkm_bin: str,
    *,
    config: BrainConfig | None = None,
) -> dict[str, object]:
    """Write/merge Claude silent-memory hooks into ``.claude/settings.json``."""
    incoming = build_claude_hooks_config(brainkm_bin, config=config)
    if settings_path.is_file():
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    else:
        existing = {}
    merged = merge_claude_settings_hooks(existing, incoming)
    _write_json(settings_path, merged)
    return merged


def build_mcp_config(
    *,
    dev: bool,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> dict[str, object]:
    from brainkm.services.mcp_transport import build_mcp_config as _build

    return _build(dev=dev, transport=transport, host=host, port=port)


def _deep_merge_dict(base: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in incoming.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _brainkm_command_suffix(command: str) -> str | None:
    marker = "brainkm"
    if marker not in command:
        return None
    return command.split(marker, 1)[1].strip()


def _merge_hook_lists(
    existing: list[object],
    incoming: list[object],
) -> list[object]:
    merged = list(existing)
    incoming_suffixes = {
        suffix
        for item in incoming
        if isinstance(item, dict)
        for suffix in [_brainkm_command_suffix(str(item.get("command", "")))]
        if suffix
    }
    if incoming_suffixes:
        merged = [
            row
            for row in merged
            if not (
                isinstance(row, dict)
                and _brainkm_command_suffix(str(row.get("command", ""))) in incoming_suffixes
            )
        ]

    existing_commands = {
        str(item.get("command"))
        for item in merged
        if isinstance(item, dict) and item.get("command")
    }
    for item in incoming:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command", ""))
        if command and command not in existing_commands:
            merged.append(item)
            existing_commands.add(command)
    return merged


def merge_hooks_json(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    merged = _deep_merge_dict(existing, {"version": incoming.get("version", 1)})
    existing_hooks = existing.get("hooks")
    incoming_hooks = incoming.get("hooks")
    if not isinstance(incoming_hooks, dict):
        return merged

    hooks_out: dict[str, object] = dict(existing_hooks) if isinstance(existing_hooks, dict) else {}
    for event, entries in incoming_hooks.items():
        if not isinstance(entries, list):
            continue
        current = hooks_out.get(event)
        if isinstance(current, list):
            hooks_out[event] = _merge_hook_lists(current, entries)
        else:
            hooks_out[event] = list(entries)
    for event in CURSOR_UNSUPPORTED_HOOK_EVENTS:
        hooks_out.pop(event, None)
    merged["hooks"] = hooks_out
    return merged


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _load_package_rule_template() -> str:
    try:
        path = resources.files("brainkm.hooks.cursor").joinpath("brainkm.mdc")
        return path.read_text(encoding="utf-8")
    except Exception:
        fallback = Path(__file__).resolve().parents[1] / "hooks" / "cursor" / "brainkm.mdc"
        return fallback.read_text(encoding="utf-8")


def _ensure_gitignore_entry(project_dir: Path, entry: str) -> bool:
    gitignore = project_dir / ".gitignore"
    if gitignore.is_file():
        content = gitignore.read_text(encoding="utf-8")
        if entry in content.splitlines():
            return False
        gitignore.write_text(content.rstrip() + f"\n{entry}\n", encoding="utf-8")
        return True

    gitignore.write_text(f"{entry}\n", encoding="utf-8")
    return True


def scan_rule_overlap(project_dir: Path) -> list[str]:
    rules_dir = project_dir / ".cursor" / "rules"
    if not rules_dir.is_dir():
        return []

    warnings: list[str] = []
    for path in sorted(rules_dir.glob("*.mdc")):
        if path.name == "brainkm.mdc":
            continue
        text = path.read_text(encoding="utf-8").lower()
        hits = [keyword for keyword in RULE_OVERLAP_KEYWORDS if keyword in text]
        if hits:
            warnings.append(
                f"Rule overlap: {path.name} mentions {', '.join(hits)} — review vs brainkm.mdc"
            )
    return warnings


def probe_cursor_version() -> list[str]:
    warnings: list[str] = []
    try:
        result = subprocess.run(
            ["cursor", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        warnings.append(
            "Cursor CLI not found — cannot verify hook support. "
            f"PreCompact requires Cursor ~>={CURSOR_MIN_VERSION_NOTE}."
        )
        return warnings

    if result.returncode != 0:
        warnings.append("Could not read Cursor version — verify hooks in Settings → Hooks.")
        return warnings

    version_text = (result.stdout or result.stderr).strip()
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_text)
    if match:
        major, minor = int(match.group(1)), int(match.group(2))
        if (major, minor) < (0, 46):
            warnings.append(
                f"Cursor {match.group(0)} may lack PreCompact hooks — "
                f"recommend >={CURSOR_MIN_VERSION_NOTE}."
            )
    else:
        warnings.append(f"Cursor version unclear ({version_text}) — confirm hook support manually.")
    return warnings


def run_install(
    project_dir: Path | None = None,
    *,
    dev: bool = False,
    force: bool = False,
    config: BrainConfig | None = None,
    no_graph: bool = False,
    client: str = "cursor",
    http: bool = False,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> InstallResult:
    """Install brainkm into a target project."""
    from brainkm.services.client_adapters import get_client_adapter
    from brainkm.services.config_loader import save_brain_config

    root = resolve_project_dir(project_dir)
    cfg = config or BrainConfig()
    if http:
        cfg = cfg.model_copy(
            update={
                "mcp": cfg.mcp.model_copy(
                    update={"transport": "http", "http_host": host, "http_port": port}
                ),
                "capture": cfg.capture.model_copy(update={"auto_observe": True}),
            }
        )
    result = InstallResult(project_dir=root)
    adapter = get_client_adapter(client)

    cursor_dir = root / ".cursor"
    brainkm_bin = resolve_hook_command(dev=dev)

    transport = cfg.mcp.transport
    mcp_payload = build_mcp_config(
        dev=dev,
        transport=transport,
        host=cfg.mcp.http_host,
        port=cfg.mcp.http_port,
    )
    hooks_payload = build_hooks_config(brainkm_bin, config=cfg)

    cursor_dir.mkdir(parents=True, exist_ok=True)
    (cursor_dir / "rules").mkdir(parents=True, exist_ok=True)

    if adapter.kind == "cursor":
        mcp_path = cursor_dir / "mcp.json"
        if mcp_path.is_file():
            existing_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
            merged_mcp = _deep_merge_dict(existing_mcp, mcp_payload)
            _write_json(mcp_path, merged_mcp)
            result.files_written.append(mcp_path)
        else:
            _write_json(mcp_path, mcp_payload)
            result.files_written.append(mcp_path)

        hooks_path = cursor_dir / "hooks.json"
        if hooks_path.is_file():
            existing_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            merged_hooks = merge_hooks_json(existing_hooks, hooks_payload)
            _write_json(hooks_path, merged_hooks)
            result.files_written.append(hooks_path)
        else:
            _write_json(hooks_path, merge_hooks_json({}, hooks_payload))
            result.files_written.append(hooks_path)

        rule_path = cursor_dir / "rules" / "brainkm.mdc"
        if rule_path.is_file() and not force:
            result.files_skipped.append(rule_path)
        else:
            _write_text(rule_path, _load_package_rule_template())
            result.files_written.append(rule_path)

        # Install brainkm routing skill for Cursor agents.
        skill_src = (
            Path(__file__).resolve().parents[1]
            / "hooks"
            / "cursor"
            / "skills"
            / "brainkm-routing"
            / "SKILL.md"
        )
        if skill_src.is_file():
            skill_dst = cursor_dir / "skills" / "brainkm-routing" / "SKILL.md"
            if skill_dst.is_file() and not force:
                result.files_skipped.append(skill_dst)
            else:
                _write_text(skill_dst, skill_src.read_text(encoding="utf-8"))
                result.files_written.append(skill_dst)

    if adapter.kind == "claude":
        # Silent observe on by default for Claude (agentmemory-style capture-on).
        cfg = cfg.model_copy(
            update={"capture": cfg.capture.model_copy(update={"auto_observe": True})}
        )

        mcp_path = root / ".mcp.json"
        if mcp_path.is_file():
            existing_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
            merged_mcp = _deep_merge_dict(existing_mcp, mcp_payload)
            _write_json(mcp_path, merged_mcp)
        else:
            _write_json(mcp_path, mcp_payload)
        result.files_written.append(mcp_path)

        claude_dir = root / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_path = claude_dir / "settings.json"
        write_claude_settings_hooks(settings_path, brainkm_bin, config=cfg)
        result.files_written.append(settings_path)

        legacy_hooks = claude_dir / "hooks.json"
        if legacy_hooks.is_file():
            result.warnings.append(
                "Legacy .claude/hooks.json found — Claude Code loads hooks from "
                ".claude/settings.json only. Safe to delete the legacy file after verifying "
                "settings hooks with `brainkm doctor`."
            )

        # Path-scoped routing rule (Claude equivalent of brainkm.mdc).
        rule_src = (
            Path(__file__).resolve().parents[1] / "hooks" / "claude" / "rules" / "brainkm.md"
        )
        if rule_src.is_file():
            rule_dst = claude_dir / "rules" / "brainkm.md"
            if rule_dst.is_file() and not force:
                result.files_skipped.append(rule_dst)
            else:
                _write_text(rule_dst, rule_src.read_text(encoding="utf-8"))
                result.files_written.append(rule_dst)

        skill_src = (
            Path(__file__).resolve().parents[1]
            / "hooks"
            / "claude"
            / "skills"
            / "brainkm-routing"
            / "SKILL.md"
        )
        if skill_src.is_file():
            skill_dst = claude_dir / "skills" / "brainkm-routing" / "SKILL.md"
            if skill_dst.is_file() and not force:
                result.files_skipped.append(skill_dst)
            else:
                _write_text(skill_dst, skill_src.read_text(encoding="utf-8"))
                result.files_written.append(skill_dst)

        agents_path = root / "CLAUDE.md"
        if agents_path.is_file() and not force:
            existing = agents_path.read_text(encoding="utf-8")
            if "brainkm — project memory routing" not in existing:
                _write_text(agents_path, existing.rstrip() + "\n\n" + adapter.agents_snippet())
                result.files_written.append(agents_path)
            else:
                result.files_skipped.append(agents_path)
        else:
            _write_text(agents_path, adapter.agents_snippet())
            result.files_written.append(agents_path)

    if adapter.kind in ("codex", "generic"):
        from brainkm.services.connect import run_connect

        connect_result = run_connect(
            adapter.kind,
            root,
            transport=transport if adapter.kind == "codex" else ("http" if http else transport),
            hooks=adapter.kind == "codex",
            host=cfg.mcp.http_host,
            port=cfg.mcp.http_port,
            dev=dev,
            update_config=False,
        )
        result.files_written.extend(connect_result.files_written)
        result.warnings.extend(connect_result.warnings)

    agents_md = root / "AGENTS.md"
    snippet = adapter.agents_snippet()
    if adapter.kind == "generic" or not agents_md.is_file():
        if agents_md.is_file() and not force:
            existing = agents_md.read_text(encoding="utf-8")
            if "brainkm — project memory routing" not in existing:
                _write_text(agents_md, existing.rstrip() + "\n\n" + snippet)
                result.files_written.append(agents_md)
            else:
                result.files_skipped.append(agents_md)
        elif adapter.kind == "generic" or force or not agents_md.is_file():
            if not agents_md.is_file():
                _write_text(agents_md, snippet)
                result.files_written.append(agents_md)

    brain_root = brain_dir(root)
    brain_root.mkdir(parents=True, exist_ok=True)
    (brain_root / "team").mkdir(parents=True, exist_ok=True)
    example_src = example_config_path()
    example_dst = brain_root / "config.example.json"
    _write_text(example_dst, example_src.read_text(encoding="utf-8"))
    result.files_written.append(example_dst)

    config_dst = brain_root / "config.json"
    # Claude install always persists auto_observe=true (and other cfg updates).
    must_save_config = (
        force
        or config is not None
        or http
        or adapter.kind == "claude"
        or not config_dst.is_file()
    )
    if not must_save_config:
        result.files_skipped.append(config_dst)
    else:
        save_brain_config(root, cfg)
        result.files_written.append(config_dst)

    for entry in GITIGNORE_ENTRIES:
        if _ensure_gitignore_entry(root, entry):
            result.files_written.append(root / ".gitignore")

    migrate(project_dir=root, run_integrity_check=True)

    if cfg.team.auto_import_on_install:
        try:
            from brainkm.services.team import import_team_neurons

            imported = import_team_neurons(root, config=cfg)
            if imported:
                logger.info("Imported %d team neurons during install", imported)
        except Exception as exc:
            result.warnings.append(f"team import skipped: {exc}")

    try:
        from brainkm.services.abstention_calibrate import calibrate_reference

        calibrate_reference(project_dir=root)
        result.files_written.append(brain_dir(root) / "abstention_calibration.json")
    except Exception as exc:
        result.warnings.append(f"abstention calibration skipped: {exc}")

    graph_json = root / cfg.graphify.graph_json
    from brainkm.services.graphify_sync import probe_graphify, sync_graph

    probe = probe_graphify(cfg.graphify)
    if not probe.found:
        result.warnings.append(probe.reason or "Graphify not found")
    elif cfg.graphify.enabled and cfg.graphify.sync_on_install and not no_graph:
        try:
            sync_result = sync_graph(project_dir=root, config=cfg, extract=True)
            if sync_result.import_result and sync_result.import_result.status == "completed":
                logger.info(
                    "Graph sync during install: %d nodes",
                    sync_result.import_result.node_count,
                )
            elif sync_result.message:
                result.warnings.append(f"graph sync: {sync_result.message}")
        except Exception as exc:
            result.warnings.append(f"graph sync skipped: {exc}")
    elif cfg.graphify.enabled and graph_json.is_file():
        try:
            import_project_graph(project_dir=root, config=cfg)
            logger.info("Imported existing graph.json during install")
        except Exception as exc:
            result.warnings.append(f"graph import skipped: {exc}")

    if adapter.kind == "cursor":
        result.warnings.extend(probe_cursor_version())
    result.warnings.extend(scan_rule_overlap(root))

    claude_hooks_src = resources.files("brainkm.hooks.claude") / "hooks.json"
    claude_dst = root / ".cursor" / "hooks.claude.example.json"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    _write_text(claude_dst, claude_hooks_src.read_text(encoding="utf-8"))
    result.files_written.append(claude_dst)

    if cfg.capture.plan_files:
        try:
            from brainkm.services.plan_capture import capture_plan_files

            conn = connect(brain_db_path(root))
            try:
                count = capture_plan_files(conn, project_dir=root, config=cfg)
                conn.commit()
                if count:
                    logger.info("Captured %d neurons from plan files during install", count)
            finally:
                conn.close()
        except Exception as exc:
            result.warnings.append(f"plan capture skipped: {exc}")

    if not dev and not shutil.which("brainkm"):
        result.warnings.append(
            "brainkm not found on PATH — hooks use bare command name; "
            "use --dev for local installs or ensure brainkm is on PATH."
        )

    if transport == "http":
        result.warnings.append(
            f"HTTP transport configured — run `brainkm serve --project-dir . "
            f"--port {cfg.mcp.http_port}` then reconnect clients with "
            "`brainkm connect <client> --http`."
        )

    logger.info(
        "install complete project_dir=%s dev=%s client=%s transport=%s",
        root,
        dev,
        client,
        transport,
    )
    return result
