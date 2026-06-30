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
CURSOR_UNSUPPORTED_HOOK_EVENTS = frozenset({"postCompact"})
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
    """Return MCP (command, args) for mcp.json."""
    if dev:
        brainkm_bin = Path(sys.executable).resolve().parent / "brainkm"
        return str(brainkm_bin), ["mcp", "--project-dir", "."]
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
                    "matcher": "Write|Edit",
                    "command": f"{brainkm_bin} post-tool --stdin",
                    "timeout": 5,
                }
            ],
        },
    }


def build_mcp_config(*, dev: bool) -> dict[str, object]:
    command, args = resolve_brainkm_command(dev=dev)
    return {
        "mcpServers": {
            BRAINKM_MCP_SERVER_KEY: {
                "command": command,
                "args": args,
            }
        }
    }


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
) -> InstallResult:
    """Install brainkm into a target project."""
    root = resolve_project_dir(project_dir)
    cfg = config or BrainConfig()
    result = InstallResult(project_dir=root)

    cursor_dir = root / ".cursor"
    mcp_path = cursor_dir / "mcp.json"
    hooks_path = cursor_dir / "hooks.json"
    rule_path = cursor_dir / "rules" / "brainkm.mdc"
    brainkm_bin = resolve_hook_command(dev=dev)

    mcp_payload = build_mcp_config(dev=dev)
    hooks_payload = build_hooks_config(brainkm_bin, config=cfg)

    if mcp_path.is_file():
        existing_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
        merged_mcp = _deep_merge_dict(existing_mcp, mcp_payload)
        _write_json(mcp_path, merged_mcp)
        result.files_written.append(mcp_path)
    else:
        _write_json(mcp_path, mcp_payload)
        result.files_written.append(mcp_path)

    if hooks_path.is_file():
        existing_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        merged_hooks = merge_hooks_json(existing_hooks, hooks_payload)
        _write_json(hooks_path, merged_hooks)
        result.files_written.append(hooks_path)
    else:
        _write_json(hooks_path, hooks_payload)
        result.files_written.append(hooks_path)

    if rule_path.is_file() and not force:
        result.files_skipped.append(rule_path)
    else:
        _write_text(rule_path, _load_package_rule_template())
        result.files_written.append(rule_path)

    brain_root = brain_dir(root)
    brain_root.mkdir(parents=True, exist_ok=True)
    example_src = example_config_path()
    example_dst = brain_root / "config.example.json"
    _write_text(example_dst, example_src.read_text(encoding="utf-8"))
    result.files_written.append(example_dst)

    config_dst = brain_root / "config.json"
    if config_dst.is_file() and not force:
        result.files_skipped.append(config_dst)
    else:
        _write_text(config_dst, example_src.read_text(encoding="utf-8"))
        result.files_written.append(config_dst)

    for entry in GITIGNORE_ENTRIES:
        if _ensure_gitignore_entry(root, entry):
            result.files_written.append(root / ".gitignore")

    migrate(project_dir=root, run_integrity_check=True)

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

    result.warnings.extend(probe_cursor_version())
    result.warnings.extend(scan_rule_overlap(root))

    claude_hooks_src = resources.files("brainkm.hooks.claude") / "hooks.json"
    claude_dst = root / ".cursor" / "hooks.claude.example.json"
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

    logger.info("install complete project_dir=%s dev=%s", root, dev)
    return result
