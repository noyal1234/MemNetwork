"""brainkm install — write Cursor MCP config, hooks, rules, and brain scaffolding."""

from __future__ import annotations

import json
import re
import shlex
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
from brainkm.services.mcp_http_auth import restrict_secret_file
from brainkm.services.mcp_transport import BRAINKM_ALL_TOOL_NAMES

logger = get_logger("services.install")

CURSOR_MIN_VERSION_NOTE = "0.46"
BRAINKM_MCP_SERVER_KEY = "brainkm"
# Claude & Antigravity tool permission names (must stay in sync with TOOL_DEFINITIONS).
BRAINKM_CLAUDE_MCP_TOOL_ALLOWS: tuple[str, ...] = tuple(
    f"mcp__brainkm__{name}" for name in BRAINKM_ALL_TOOL_NAMES
)
BRAINKM_ANTIGRAVITY_MCP_TOOL_ALLOWS: tuple[str, ...] = tuple(
    f"brainkm/{name}" for name in BRAINKM_ALL_TOOL_NAMES
)
BRAINKM_CLAUDE_MCP_TOOL_WILDCARD = "mcp__brainkm__*"
# Cursor does not implement postCompact (use preCompact handover + sessionStart instead).
# postToolUseFailure is Claude-oriented; Cursor surfaces failures on postToolUse payloads.
CURSOR_UNSUPPORTED_HOOK_EVENTS = frozenset({"postCompact", "postToolUseFailure"})
# Kept here (not in codex_rollout) so GITIGNORE_ENTRIES stays a single literal
# list and uninstall can strip the same string.
CODEX_CONTEXT_SKILL_IGNORE = ".codex/skills/brainkm-context/"
GITIGNORE_ENTRIES = (
    ".brain/brain.db",
    ".brain/brain.db-wal",
    ".brain/brain.db-shm",
    ".brain/mcp_http_token",
    ".brain/exports/",
    ".env",
    "graphify-out/",
    # Regenerated memory pack for Codex (see services/codex_rollout). Rewritten
    # on every commit by the post-commit hook, so it must never be tracked.
    CODEX_CONTEXT_SKILL_IGNORE,
)
# Dev installs (``--dev``) bake the local venv's absolute ``brainkm`` binary path
# into the client's MCP config, which breaks for any other machine/teammate.
# Gitignore that file by default so it never leaves the dev checkout accidentally.
DEV_MCP_CONFIG_GITIGNORE_PATHS: dict[str, str] = {
    "cursor": ".cursor/mcp.json",
    "claude": ".mcp.json",
}
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
    """Absolute project root; expands ``~`` (Typer/Path do not)."""
    root = project_dir if project_dir is not None else Path.cwd()
    return root.expanduser().resolve()


def _venv_brainkm_bin() -> Path:
    """``brainkm`` next to the running interpreter's bin dir (do not follow python → Cellar)."""
    # ``Path(sys.executable).resolve()`` follows the venv python symlink into Homebrew
    # Cellar, which yields a fragile absolute path. Keep the venv bin directory.
    return Path(sys.executable).parent / "brainkm"


def resolve_brainkm_command(*, dev: bool) -> tuple[str, list[str]]:
    """Return MCP (command, args) for mcp.json.

    Dev/private: absolute venv ``brainkm``. Until PyPI publish (deferred while the
    repo is private), production installs prefer a PATH ``brainkm``; ``uvx`` is only
    a placeholder for the future public zero-clone path.
    """
    if dev:
        brainkm_bin = _venv_brainkm_bin()
        return str(brainkm_bin), ["mcp", "--project-dir", "."]
    found = shutil.which("brainkm")
    if found:
        return found, ["mcp", "--project-dir", "."]
    # Deferred: requires public PyPI package. Prefer ``brainkm install --dev`` today.
    return "uvx", ["brainkm@latest", "mcp", "--project-dir", "."]


def resolve_hook_command(*, dev: bool) -> str:
    """Absolute or PATH-resolved brainkm binary for hook subprocesses."""
    if dev:
        return str(_venv_brainkm_bin())
    found = shutil.which("brainkm")
    if found:
        return found
    return "brainkm"


def build_hooks_config(
    brainkm_bin: str,
    *,
    config: BrainConfig | None = None,
) -> dict[str, object]:
    """Cursor hooks — always pass ``--client cursor`` so Claude ToolSearch copy stays gated.

    PreToolUse matcher is pack patterns only (write/edit/shell). Routing-nudge
    Read/Grep/Glob matchers are Claude-only (see ``build_claude_hooks_config``);
    packs still transfer. Shell packs require a path/symbol seed.
    """
    cfg = config or BrainConfig()
    matcher = pre_tool_matcher(list(cfg.injection.pre_tool_patterns))
    # Hook commands run through the IDE's shell — quote the binary path so
    # spaces/metacharacters in install locations cannot alter the command.
    bin_q = shlex.quote(brainkm_bin)
    return {
        "version": 1,
        "hooks": {
            "sessionStart": [
                {
                    "command": f"{bin_q} session-start --stdin --client cursor",
                    "timeout": 30,
                }
            ],
            "sessionEnd": [
                {
                    "command": f"{bin_q} session-end --stdin --client cursor",
                    "timeout": 120,
                }
            ],
            "preCompact": [
                {
                    "matcher": "auto",
                    "command": f"{bin_q} handover --stdin --client cursor",
                    "timeout": 30,
                }
            ],
            "preToolUse": [
                {
                    "matcher": matcher,
                    "command": f"{bin_q} pre-tool --stdin --client cursor",
                    "timeout": 15,
                }
            ],
            "postToolUse": [
                {
                    "matcher": "Write|Edit|Shell",
                    "command": f"{bin_q} post-tool --stdin --client cursor",
                    "timeout": 5,
                }
            ],
            "beforeSubmitPrompt": [
                {
                    "command": f"{bin_q} user-prompt --stdin --client cursor",
                    "timeout": 5,
                }
            ],
            "stop": [
                {
                    "command": f"{bin_q} agent-stop --stdin --client cursor",
                    "timeout": 15,
                }
            ],
        },
    }


def _claude_hook_command(
    brainkm_bin: str, *args: str, timeout: int | None = None
) -> dict[str, object]:
    """One Claude Code command-hook entry (nested under matcher groups)."""
    cmd = f"{shlex.quote(brainkm_bin)} {' '.join(args)} --client claude"
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
    matcher = pre_tool_matcher(
        list(cfg.injection.pre_tool_patterns)
        + list(cfg.injection.routing_nudge_pretool_patterns)
    )
    # Claude uses Bash instead of Shell for the terminal tool.
    claude_matcher = matcher.replace("Shell", "Bash") if matcher else "Write|Edit|Bash"
    return {
        "hooks": {
            "SessionStart": _claude_event_group(
                _claude_hook_command(brainkm_bin, "session-start", "--stdin", timeout=30),
                matcher="startup|resume|clear",
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
    hooks_out: dict[str, object] = dict(existing_hooks) if isinstance(existing_hooks, dict) else {}
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


def claude_global_config_path() -> Path:
    """``~/.claude.json`` — Claude Code's global, cross-project state file."""
    return Path.home() / ".claude.json"


def enable_claude_mcpjson_approval(
    root: Path,
    *,
    server_key: str = BRAINKM_MCP_SERVER_KEY,
    config_path: Path | None = None,
) -> str | None:
    """Pre-approve ``server_key`` for this project in Claude Code's global config.

    Claude Code gates any server declared in a project's ``.mcp.json`` behind a
    one-time approval prompt separate from the folder-trust dialog: only after
    the user accepts does the server name land in
    ``projects[<root>].enabledMcpjsonServers`` inside ``~/.claude.json``. Until
    then Claude Code silently skips loading the server — no error, just no
    tools — which historically left every fresh ``brainkm install --client
    claude`` non-functional for MCP tools even though hooks and ``.mcp.json``
    were both wired correctly.

    Returns ``None`` on success (or if already enabled/disabled-intentionally),
    or a human-readable warning string if the global config couldn't be
    patched (missing file, project not yet opened in Claude Code, bad JSON).
    """
    path = config_path or claude_global_config_path()
    if not path.is_file():
        return (
            "~/.claude.json not found — open this project in Claude Code once, then rerun "
            f"`brainkm install --client claude` (or `brainkm doctor`) to auto-approve the "
            f"'{server_key}' MCP server."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "~/.claude.json is not valid JSON — skipped MCP server approval patch."
    if not isinstance(data, dict):
        return "~/.claude.json has an unexpected top-level shape — skipped MCP server approval patch."

    projects = data.setdefault("projects", {})
    if not isinstance(projects, dict):
        return "~/.claude.json 'projects' key has an unexpected shape — skipped MCP approval patch."

    project_key = str(root)
    project = projects.get(project_key)
    if not isinstance(project, dict):
        return (
            "Project not yet registered in ~/.claude.json — open this project in Claude Code "
            f"once (to accept the folder-trust prompt), then rerun install to auto-approve "
            f"'{server_key}'."
        )

    disabled = project.get("disabledMcpjsonServers")
    if isinstance(disabled, list) and server_key in disabled:
        return (
            f"'{server_key}' is listed in disabledMcpjsonServers in ~/.claude.json — remove it "
            "manually if you want brainkm's MCP tools to load."
        )

    enabled = project.get("enabledMcpjsonServers")
    if not isinstance(enabled, list):
        enabled = []
    if server_key in enabled:
        return None
    project["enabledMcpjsonServers"] = [*enabled, server_key]

    tmp_path = path.with_suffix(path.suffix + ".brainkm-tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return None


def ensure_claude_settings_local_permissions(
    root: Path,
    *,
    server_key: str = BRAINKM_MCP_SERVER_KEY,
    tool_allows: tuple[str, ...] = BRAINKM_CLAUDE_MCP_TOOL_ALLOWS,
) -> Path:
    """Merge brainkm MCP tool allows + server enable into ``.claude/settings.local.json``.

    Claude Code gates individual MCP tools behind ``permissions.allow`` separately
    from server approval. A partial allowlist (e.g. only traverse/context_pack)
    makes Claude reluctant to call ``recall`` / ``trace_changes`` / ``remember``
    because each call prompts for approval. This helper unions the full tool set
    without removing user allows or other keys.

    Also ensures ``enabledMcpjsonServers`` contains ``server_key`` (Claude Code
    ≥2.1.196 honors project-local approval here in addition to ``~/.claude.json``).
    """
    root = resolve_project_dir(root)
    path = root / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, object] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}

    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    allow = permissions.get("allow")
    if not isinstance(allow, list):
        allow = []
    allow_strs = [str(item) for item in allow]
    for tool in tool_allows:
        if tool not in allow_strs:
            allow_strs.append(tool)
    permissions["allow"] = allow_strs
    data["permissions"] = permissions

    enabled = data.get("enabledMcpjsonServers")
    if not isinstance(enabled, list):
        enabled = []
    enabled_strs = [str(item) for item in enabled]
    if server_key not in enabled_strs:
        enabled_strs.append(server_key)
    data["enabledMcpjsonServers"] = enabled_strs

    tmp_path = path.with_suffix(path.suffix + ".brainkm-tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def ensure_antigravity_mcp_config_permissions(
    root: Path,
    *,
    server_key: str = BRAINKM_MCP_SERVER_KEY,
) -> Path:
    """Ensure ``.agents/mcp_config.json`` contains pre-authorized permissions for all 8 brainkm tools."""
    root = resolve_project_dir(root)
    path = root / ".agents" / "mcp_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, object] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}

    mcp_servers = data.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
    entry = mcp_servers.get(server_key)
    if not isinstance(entry, dict):
        entry = {}

    tool_list = list(BRAINKM_ALL_TOOL_NAMES)
    entry["alwaysAllow"] = tool_list
    entry["autoApprove"] = tool_list
    mcp_servers[server_key] = entry
    data["mcpServers"] = mcp_servers

    _write_json(path, data)
    return path


def ensure_claude_pretool_matcher(
    root: Path,
    *,
    config: BrainConfig | None = None,
) -> bool:
    """Heal a stale ``PreToolUse`` matcher in ``.claude/settings.json``.

    An install predating a new ``injection.pre_tool_patterns`` default leaves a
    narrower matcher on disk forever: reinstall replaces it, but nothing tells
    the user to reinstall, so the hook silently stops firing for whole tool
    classes. The concrete case this fixes is a matcher written before
    ``run_terminal`` was a default — Bash calls then bypass PreToolUse entirely,
    which is precisely where brainkm most needs to intervene.

    Only widens: tokens the user added by hand are preserved. Returns True when
    the file was rewritten.
    """
    root = resolve_project_dir(root)
    path = root / ".claude" / "settings.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    groups = hooks.get("PreToolUse")
    if not isinstance(groups, list):
        return False

    cfg = config or BrainConfig()
    expected = pre_tool_matcher(
        list(cfg.injection.pre_tool_patterns) + list(cfg.injection.routing_nudge_pretool_patterns)
    ).replace("Shell", "Bash")
    if not expected:
        return False
    expected_tokens = [tok for tok in expected.split("|") if tok]

    changed = False
    for group in groups:
        if not isinstance(group, dict) or not _claude_group_has_brainkm(group):
            continue
        current = group.get("matcher")
        current_tokens = [tok for tok in str(current).split("|") if tok] if current else []
        missing = [tok for tok in expected_tokens if tok not in current_tokens]
        if not missing:
            continue
        group["matcher"] = "|".join([*current_tokens, *missing])
        changed = True

    if not changed:
        return False
    tmp_path = path.with_suffix(path.suffix + ".brainkm-tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return True


def _codex_hook_command(
    brainkm_bin: str,
    *args: str,
    timeout: int | None = None,
    status_message: str | None = None,
) -> dict[str, object]:
    """One Codex CLI command-hook entry (nested under matcher groups)."""
    cmd = f"{shlex.quote(brainkm_bin)} {' '.join(args)} --client codex"
    entry: dict[str, object] = {"type": "command", "command": cmd}
    if timeout is not None:
        entry["timeout"] = timeout
    if status_message is not None:
        entry["statusMessage"] = status_message
    return entry


def build_codex_hooks_config(
    brainkm_bin: str,
    *,
    config: BrainConfig | None = None,
) -> dict[str, object]:
    """Codex CLI hooks for ``.codex/hooks.json`` (PascalCase nested schema).

    ``SessionEnd`` is deliberately NOT wired. Codex's wire schema claims to
    define it, but empirically it never lands in Codex's own trust ledger
    (``~/.codex/config.toml`` ``[hooks.state]``): all other 9 events we wire
    get a ``trusted_hash`` entry after `/hooks` trust, ``session_end`` never
    does, even after narrowing its declared timeout well under the other
    events' — confirmed 2026-08-02 on codex-cli 0.146. A prior revision of
    this docstring asserted the opposite ("Codex *does* fire SessionEnd —
    verified against the wire schema") and wired it anyway; that revision was
    wrong. Do not re-add it without a live re-verification against the
    installed `codex` CLI's own hook schema, not against the earlier claim.

    Capture for Codex is NOT hook-driven at all: it comes from
    ``brainkm codex-capture`` reading Codex rollout JSONL, invoked by the
    project's post-commit git hook (see ``services/codex_rollout.py``). Stop
    only flushes use counters, matching the Claude wiring — it does not
    substitute for capture (Stop can fire repeatedly within one conversation,
    since it marks the end of an agent loop, not the session).

    Tool matchers include ``Bash`` (Codex 0.130+ routes many edits through shell)
    plus ``apply_patch`` / ``Edit`` / ``Write`` and MCP ``mcp__.*``.

    Codex 0.146 defines 11 hook events. We wire 9. ``PermissionRequest`` is
    deliberately NOT wired: it exists so a hook can approve/deny a permission
    prompt, and brainkm has no handler for it and no business auto-answering
    permission requests on the user's behalf. That omission is a decision, not
    an oversight — do not "fix" it by pointing it at an unrelated handler.
    """
    _ = config
    tool_matcher = "Bash|apply_patch|Edit|Write|mcp__.*"
    return {
        "description": "brainkm lifecycle hooks for OpenAI Codex CLI.",
        "hooks": {
            "SessionStart": _claude_event_group(
                _codex_hook_command(
                    brainkm_bin,
                    "session-start",
                    "--stdin",
                    timeout=30,
                    status_message="Loading brainkm context",
                ),
                matcher="startup|resume|clear",
            ),
            "UserPromptSubmit": _claude_event_group(
                _codex_hook_command(brainkm_bin, "user-prompt", "--stdin", timeout=15),
            ),
            "PreToolUse": _claude_event_group(
                _codex_hook_command(
                    brainkm_bin,
                    "pre-tool",
                    "--stdin",
                    timeout=15,
                    status_message="brainkm pre-tool",
                ),
                matcher=tool_matcher,
            ),
            "PostToolUse": _claude_event_group(
                _codex_hook_command(brainkm_bin, "post-tool", "--stdin", timeout=15),
                matcher=tool_matcher,
            ),
            "PreCompact": _claude_event_group(
                _codex_hook_command(
                    brainkm_bin,
                    "handover",
                    "--stdin",
                    timeout=30,
                    status_message="brainkm handover",
                ),
                matcher="manual|auto",
            ),
            "PostCompact": _claude_event_group(
                _codex_hook_command(brainkm_bin, "post-compact", "--stdin", timeout=30),
                matcher="manual|auto",
            ),
            "Stop": _claude_event_group(
                _codex_hook_command(brainkm_bin, "agent-stop", "--stdin", timeout=15),
            ),
            "SubagentStart": _claude_event_group(
                _codex_hook_command(brainkm_bin, "subagent-start", "--stdin", timeout=30),
            ),
            "SubagentStop": _claude_event_group(
                _codex_hook_command(brainkm_bin, "subagent-stop", "--stdin", timeout=60),
            ),
        },
    }


def merge_codex_hooks_json(
    existing: dict[str, object],
    incoming_hooks: dict[str, object],
) -> dict[str, object]:
    """Merge brainkm Codex hooks without clobbering foreign matcher groups."""
    merged = dict(existing)
    if "description" in incoming_hooks and "description" not in merged:
        merged["description"] = incoming_hooks["description"]
    incoming = incoming_hooks.get("hooks")
    if not isinstance(incoming, dict):
        return merged

    existing_hooks = merged.get("hooks")
    hooks_out: dict[str, object] = dict(existing_hooks) if isinstance(existing_hooks, dict) else {}
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


def write_codex_hooks(
    hooks_path: Path,
    brainkm_bin: str,
    *,
    config: BrainConfig | None = None,
) -> dict[str, object]:
    """Write/merge Codex hooks into ``.codex/hooks.json``."""
    incoming = build_codex_hooks_config(brainkm_bin, config=config)
    if hooks_path.is_file():
        existing = json.loads(hooks_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    else:
        existing = {}
    merged = merge_codex_hooks_json(existing, incoming)
    _write_json(hooks_path, merged)
    return merged


def _agy_hook_command(
    brainkm_bin: str,
    *args: str,
    timeout: int | None = None,
    project_dir: Path | None = None,
) -> dict[str, object]:
    parts = [shlex.quote(brainkm_bin), *args]
    if project_dir is not None:
        parts.extend(["--project-dir", shlex.quote(str(project_dir.resolve()))])
    parts.extend(["--client", "antigravity"])
    entry: dict[str, object] = {"type": "command", "command": " ".join(parts)}
    if timeout is not None:
        entry["timeout"] = timeout
    return entry


def build_antigravity_hooks_config(
    brainkm_bin: str,
    *,
    config: BrainConfig | None = None,
    project_dir: Path | None = None,
) -> dict[str, object]:
    """Named-handler hooks for ``.agents/hooks.json`` (Antigravity schema).

    ``project_dir`` is baked into each command as ``--project-dir`` so hooks still
    hit the shared project ``.brain/`` when Antigravity runs them with cwd=``.agents``.
    """
    _ = config
    write_matcher = "write_to_file|replace_file_content|multi_replace_file_content|run_command"

    def _cmd(*args: str, timeout: int | None = None) -> dict[str, object]:
        return _agy_hook_command(brainkm_bin, *args, timeout=timeout, project_dir=project_dir)

    return {
        "brainkm": {
            "enabled": True,
            # Bonus: some builds accept SessionStart (Mem0); ignored if unsupported.
            "SessionStart": [
                _cmd(
                    "pre-invocation",
                    "--stdin",
                    "--event",
                    "SessionStart",
                    timeout=30,
                ),
            ],
            "PreInvocation": [
                _cmd(
                    "pre-invocation",
                    "--stdin",
                    "--event",
                    "PreInvocation",
                    timeout=30,
                ),
            ],
            # build_antigravity_hook_stdout already handles PostInvocation identically to
            # PostToolUse (services/hooks.py) — this entry was the missing wiring that made
            # that branch unreachable. Same handler (run_post_tool_use), different event name.
            "PostInvocation": [
                _cmd(
                    "post-tool",
                    "--stdin",
                    "--event",
                    "PostInvocation",
                    timeout=15,
                ),
            ],
            "PreToolUse": [
                {
                    "matcher": write_matcher,
                    "hooks": [
                        _cmd(
                            "pre-tool",
                            "--stdin",
                            "--event",
                            "PreToolUse",
                            timeout=15,
                        ),
                    ],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": write_matcher,
                    "hooks": [
                        _cmd(
                            "post-tool",
                            "--stdin",
                            "--event",
                            "PostToolUse",
                            timeout=5,
                        ),
                    ],
                }
            ],
            "Stop": [
                _cmd(
                    "agent-stop",
                    "--stdin",
                    "--event",
                    "Stop",
                    timeout=120,
                ),
            ],
        }
    }


def merge_antigravity_hooks_json(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Replace ``brainkm`` named handler; preserve other top-level hook groups."""
    merged = dict(existing)
    for name, body in incoming.items():
        merged[name] = body
    return merged


def write_antigravity_hooks(
    hooks_path: Path,
    brainkm_bin: str,
    *,
    config: BrainConfig | None = None,
    project_dir: Path | None = None,
) -> dict[str, object]:
    """Write/merge brainkm Antigravity hooks into ``.agents/hooks.json``."""
    root = resolve_project_dir(project_dir) if project_dir is not None else hooks_path.parent.parent
    incoming = build_antigravity_hooks_config(brainkm_bin, config=config, project_dir=root)
    if hooks_path.is_file():
        existing = json.loads(hooks_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    else:
        existing = {}
    merged = merge_antigravity_hooks_json(existing, incoming)
    _write_json(hooks_path, merged)
    # Always clear any leftover shadow brain after wiring hooks correctly.
    from brainkm.services.antigravity_session import heal_antigravity_wiring

    heal_antigravity_wiring(root, rewrite_hooks=False)
    return merged


def build_mcp_config(
    *,
    dev: bool,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    client: str | None = None,
    http_token: str | None = None,
) -> dict[str, object]:
    from brainkm.services.mcp_transport import build_mcp_config as _build

    return _build(
        dev=dev,
        transport=transport,
        host=host,
        port=port,
        client=client,
        http_token=http_token,
    )


def _cli_on_path(name: str) -> bool:
    return shutil.which(name) is not None


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


def _brainkm_hook_key(command: str) -> str | None:
    """Merge identity: brainkm argv after the binary, ignoring ``--client <kind>``.

    Lets ``session-start --stdin`` be replaced by ``session-start --stdin --client cursor``
    on reinstall without leaving a duplicate legacy hook.
    """
    suffix = _brainkm_command_suffix(command)
    if not suffix:
        return None
    return re.sub(r"(?:^|\s)--client\s+\S+", "", suffix).strip() or None


def _merge_hook_lists(
    existing: list[object],
    incoming: list[object],
) -> list[object]:
    merged = list(existing)
    incoming_keys = {
        key
        for item in incoming
        if isinstance(item, dict)
        for key in [_brainkm_hook_key(str(item.get("command", "")))]
        if key
    }
    if incoming_keys:
        merged = [
            row
            for row in merged
            if not (
                isinstance(row, dict)
                and _brainkm_hook_key(str(row.get("command", ""))) in incoming_keys
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


_PROJECT_MD_SNIPPET_MARKER = "# brainkm — project memory routing"


def upsert_project_md_snippet(
    path: Path,
    snippet: str,
    *,
    force: bool,
) -> str:
    """Append or replace the brainkm routing section in CLAUDE.md / AGENTS.md.

    Never clobbers user content outside the brainkm snippet. Returns one of:
    ``written``, ``appended``, ``replaced``, ``skipped``.
    """
    cleaned = snippet.rstrip() + "\n"
    if not path.is_file():
        _write_text(path, cleaned)
        return "written"
    existing = path.read_text(encoding="utf-8")
    if _PROJECT_MD_SNIPPET_MARKER not in existing:
        _write_text(path, existing.rstrip() + "\n\n" + cleaned)
        return "appended"
    if not force:
        return "skipped"
    start = existing.index(_PROJECT_MD_SNIPPET_MARKER)
    line_start = existing.rfind("\n", 0, start) + 1
    prefix = existing[:line_start].rstrip()
    new_content = (prefix + "\n\n" + cleaned) if prefix else cleaned
    _write_text(path, new_content)
    return "replaced"


def _normalize_merged_mcp_payload(merged_mcp: dict[str, object]) -> dict[str, object]:
    """Drop stale stdio/HTTP fields on the brainkm MCP entry after a deep merge."""
    from brainkm.services.mcp_transport import normalize_mcp_entry_transport_fields

    servers = merged_mcp.get("mcpServers")
    if isinstance(servers, dict) and isinstance(servers.get(BRAINKM_MCP_SERVER_KEY), dict):
        servers[BRAINKM_MCP_SERVER_KEY] = normalize_mcp_entry_transport_fields(
            servers[BRAINKM_MCP_SERVER_KEY]  # type: ignore[arg-type]
        )
    return merged_mcp


def _load_package_rule_template() -> str:
    try:
        path = resources.files("brainkm.hooks.cursor").joinpath("brainkm.mdc")
        return path.read_text(encoding="utf-8")
    except Exception:
        fallback = Path(__file__).resolve().parents[1] / "hooks" / "cursor" / "brainkm.mdc"
        return fallback.read_text(encoding="utf-8")


@dataclass
class GuidanceAssetsResult:
    """Routing rule / skill / project-md assets written by install or connect."""

    files_written: list[Path] = field(default_factory=list)
    files_skipped: list[Path] = field(default_factory=list)


def _hooks_package_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "hooks"


def _copy_guidance_text(
    *,
    src: Path | None,
    dst: Path,
    force: bool,
    content: str | None = None,
    result: GuidanceAssetsResult,
) -> None:
    """Write ``dst`` from ``content`` or ``src``.

    Managed guidance files (rules/skills) refresh when the template content
    differs, even without ``force`` — otherwise installs leave stale copies
    after template updates. Identical content is skipped.
    """
    if content is None:
        if src is None or not src.is_file():
            return
        content = src.read_text(encoding="utf-8")
    if dst.is_file() and not force:
        try:
            if dst.read_text(encoding="utf-8") == content:
                result.files_skipped.append(dst)
                return
        except OSError:
            pass
    _write_text(dst, content)
    result.files_written.append(dst)


def install_client_guidance_assets(
    project_dir: Path,
    client: str,
    *,
    force: bool = False,
) -> GuidanceAssetsResult:
    """Install per-client routing rule + skill (+ AGENTS/CLAUDE snippet).

    Used by both ``run_install`` and ``run_connect`` so secondary apps in the
    multi-IDE wizard get the same guidance assets as a primary install.
    """
    from brainkm.services.client_adapters import get_client_adapter

    root = resolve_project_dir(project_dir)
    kind = str(client).lower()
    adapter = get_client_adapter(kind)
    result = GuidanceAssetsResult()
    hooks_root = _hooks_package_dir()

    if kind == "cursor":
        cursor_dir = root / ".cursor"
        cursor_dir.mkdir(parents=True, exist_ok=True)
        (cursor_dir / "rules").mkdir(parents=True, exist_ok=True)
        _copy_guidance_text(
            src=None,
            dst=cursor_dir / "rules" / "brainkm.mdc",
            force=force,
            content=_load_package_rule_template(),
            result=result,
        )
        _copy_guidance_text(
            src=hooks_root / "cursor" / "skills" / "brainkm-routing" / "SKILL.md",
            dst=cursor_dir / "skills" / "brainkm-routing" / "SKILL.md",
            force=force,
            result=result,
        )
        return result

    if kind == "antigravity":
        agents_dir = root / ".agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        _copy_guidance_text(
            src=hooks_root / "antigravity" / "rules" / "brainkm.md",
            dst=agents_dir / "rules" / "brainkm.md",
            force=force,
            result=result,
        )
        _copy_guidance_text(
            src=hooks_root / "antigravity" / "skills" / "brainkm-routing" / "SKILL.md",
            dst=agents_dir / "skills" / "brainkm-routing" / "SKILL.md",
            force=force,
            result=result,
        )
        agents_path = root / "AGENTS.md"
        action = upsert_project_md_snippet(agents_path, adapter.agents_snippet(), force=force)
        if action == "skipped":
            result.files_skipped.append(agents_path)
        else:
            result.files_written.append(agents_path)
        return result

    if kind == "claude":
        claude_dir = root / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        _copy_guidance_text(
            src=hooks_root / "claude" / "rules" / "brainkm.md",
            dst=claude_dir / "rules" / "brainkm.md",
            force=force,
            result=result,
        )
        _copy_guidance_text(
            src=hooks_root / "claude" / "skills" / "brainkm-routing" / "SKILL.md",
            dst=claude_dir / "skills" / "brainkm-routing" / "SKILL.md",
            force=force,
            result=result,
        )
        agents_path = root / "CLAUDE.md"
        action = upsert_project_md_snippet(agents_path, adapter.agents_snippet(), force=force)
        if action == "skipped":
            result.files_skipped.append(agents_path)
        else:
            result.files_written.append(agents_path)
        return result

    if kind == "codex":
        codex_dir = root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        _copy_guidance_text(
            src=hooks_root / "codex" / "rules" / "brainkm.md",
            dst=codex_dir / "rules" / "brainkm.md",
            force=force,
            result=result,
        )
        _copy_guidance_text(
            src=hooks_root / "codex" / "skills" / "brainkm-routing" / "SKILL.md",
            dst=codex_dir / "skills" / "brainkm-routing" / "SKILL.md",
            force=force,
            result=result,
        )
        agents_path = root / "AGENTS.md"
        action = upsert_project_md_snippet(agents_path, adapter.agents_snippet(), force=force)
        if action == "skipped":
            result.files_skipped.append(agents_path)
        else:
            result.files_written.append(agents_path)
        return result

    return result


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

    # Client-specific distill defaults (schema default is cursor).
    if adapter.kind == "antigravity":
        if _cli_on_path("agy"):
            cfg = cfg.model_copy(
                update={
                    "capture": cfg.capture.model_copy(
                        update={"distill_mode": "antigravity", "auto_observe": True}
                    )
                }
            )
        else:
            mode = cfg.capture.distill_mode
            if mode in ("cursor", "mcp"):
                mode = "rules"
            cfg = cfg.model_copy(
                update={
                    "capture": cfg.capture.model_copy(
                        update={"distill_mode": mode, "auto_observe": True}
                    )
                }
            )
            result.warnings.append(
                "agy not on PATH — distill_mode set to rules (or keep groq/ollama); "
                "install Antigravity CLI for distill_mode=antigravity."
            )
    if adapter.kind == "claude":
        if _cli_on_path("claude"):
            cfg = cfg.model_copy(
                update={
                    "capture": cfg.capture.model_copy(
                        update={"distill_mode": "claude", "auto_observe": True}
                    )
                }
            )
        else:
            cfg = cfg.model_copy(
                update={"capture": cfg.capture.model_copy(update={"auto_observe": True})}
            )
            if cfg.capture.distill_mode in ("cursor", "mcp"):
                cfg = cfg.model_copy(
                    update={"capture": cfg.capture.model_copy(update={"distill_mode": "rules"})}
                )
            result.warnings.append(
                "claude CLI not on PATH — prefer distill_mode=claude after installing Claude Code CLI."  # noqa: E501
            )
    if adapter.kind == "codex":
        if _cli_on_path("codex"):
            cfg = cfg.model_copy(
                update={
                    "capture": cfg.capture.model_copy(
                        update={"distill_mode": "codex", "auto_observe": True}
                    )
                }
            )
        else:
            cfg = cfg.model_copy(
                update={"capture": cfg.capture.model_copy(update={"auto_observe": True})}
            )
            if cfg.capture.distill_mode in ("cursor", "mcp", "claude", "antigravity"):
                cfg = cfg.model_copy(
                    update={"capture": cfg.capture.model_copy(update={"distill_mode": "rules"})}
                )
            result.warnings.append(
                "codex CLI not on PATH — distill_mode set to rules (or keep groq/ollama); "
                "install Codex CLI for distill_mode=codex."
            )
        result.warnings.append(
            "Codex: trust the project `.codex/` layer, then open `/hooks` and trust "
            "brainkm commands — untrusted project hooks are skipped."
        )

    cursor_dir = root / ".cursor"
    brainkm_bin = resolve_hook_command(dev=dev)

    transport = cfg.mcp.transport
    http_token = None
    if transport == "http":
        from brainkm.services.mcp_http_auth import ensure_mcp_http_token

        http_token = ensure_mcp_http_token(root)
    mcp_payload = build_mcp_config(
        dev=dev,
        transport=transport,
        host=cfg.mcp.http_host,
        port=cfg.mcp.http_port,
        client=adapter.kind,
        http_token=http_token,
    )
    hooks_payload = build_hooks_config(brainkm_bin, config=cfg)

    if adapter.kind == "cursor":
        cursor_dir.mkdir(parents=True, exist_ok=True)
        (cursor_dir / "rules").mkdir(parents=True, exist_ok=True)

    if adapter.kind == "cursor":
        mcp_path = cursor_dir / "mcp.json"
        if mcp_path.is_file():
            existing_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
            merged_mcp = _normalize_merged_mcp_payload(_deep_merge_dict(existing_mcp, mcp_payload))
            _write_json(mcp_path, merged_mcp)
            result.files_written.append(mcp_path)
        else:
            _write_json(mcp_path, mcp_payload)
            result.files_written.append(mcp_path)
        if http_token:
            restrict_secret_file(mcp_path)

        hooks_path = cursor_dir / "hooks.json"
        if hooks_path.is_file():
            existing_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            merged_hooks = merge_hooks_json(existing_hooks, hooks_payload)
            _write_json(hooks_path, merged_hooks)
            result.files_written.append(hooks_path)
        else:
            _write_json(hooks_path, merge_hooks_json({}, hooks_payload))
            result.files_written.append(hooks_path)

        guidance = install_client_guidance_assets(root, "cursor", force=force)
        result.files_written.extend(guidance.files_written)
        result.files_skipped.extend(guidance.files_skipped)

    if adapter.kind == "antigravity":
        agents_dir = root / ".agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        mcp_path = ensure_antigravity_mcp_config_permissions(root)
        if mcp_path.is_file():
            existing_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
            merged_mcp = _normalize_merged_mcp_payload(_deep_merge_dict(existing_mcp, mcp_payload))
            _write_json(mcp_path, merged_mcp)
        else:
            _write_json(mcp_path, mcp_payload)
        result.files_written.append(mcp_path)
        if http_token:
            restrict_secret_file(mcp_path)

        hooks_path = agents_dir / "hooks.json"
        write_antigravity_hooks(hooks_path, brainkm_bin, config=cfg, project_dir=root)
        result.files_written.append(hooks_path)

        guidance = install_client_guidance_assets(root, "antigravity", force=force)
        result.files_written.extend(guidance.files_written)
        result.files_skipped.extend(guidance.files_skipped)

    if adapter.kind == "claude":
        mcp_path = root / ".mcp.json"
        if mcp_path.is_file():
            existing_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
            merged_mcp = _normalize_merged_mcp_payload(_deep_merge_dict(existing_mcp, mcp_payload))
            _write_json(mcp_path, merged_mcp)
        else:
            _write_json(mcp_path, mcp_payload)
        result.files_written.append(mcp_path)
        if http_token:
            restrict_secret_file(mcp_path)

        approval_warning = enable_claude_mcpjson_approval(root)
        if approval_warning:
            result.warnings.append(approval_warning)

        local_settings = ensure_claude_settings_local_permissions(root)
        result.files_written.append(local_settings)

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

        guidance = install_client_guidance_assets(root, "claude", force=force)
        result.files_written.extend(guidance.files_written)
        result.files_skipped.extend(guidance.files_skipped)

    if adapter.kind == "codex":
        from brainkm.services.mcp_transport import write_codex_mcp_config

        codex_dir = root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)

        mcp_path = codex_dir / "config.toml"
        write_codex_mcp_config(
            mcp_path,
            dev=dev,
            transport=transport,
            host=cfg.mcp.http_host,
            port=cfg.mcp.http_port,
            http_token=http_token,
        )
        result.files_written.append(mcp_path)
        if http_token:
            restrict_secret_file(mcp_path)

        hooks_path = codex_dir / "hooks.json"
        write_codex_hooks(hooks_path, brainkm_bin, config=cfg)
        result.files_written.append(hooks_path)

        guidance = install_client_guidance_assets(root, "codex", force=force)
        result.files_written.extend(guidance.files_written)
        result.files_skipped.extend(guidance.files_skipped)

    if adapter.kind == "generic":
        from brainkm.services.connect import run_connect

        connect_result = run_connect(
            adapter.kind,
            root,
            transport="http" if http else transport,
            hooks=False,
            host=cfg.mcp.http_host,
            port=cfg.mcp.http_port,
            dev=dev,
            update_config=False,
        )
        result.files_written.extend(connect_result.files_written)
        result.warnings.extend(connect_result.warnings)

    agents_md = root / "AGENTS.md"
    snippet = adapter.agents_snippet()
    if adapter.kind == "generic" or (
        adapter.kind not in ("claude", "antigravity", "codex") and not agents_md.is_file()
    ):
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
    from brainkm.services.config_loader import (
        grandfather_commit_trace_if_needed,
        raw_config_has_commit_trace,
        should_install_commit_hook,
    )

    grandfathered = False
    if config_dst.is_file() and not raw_config_has_commit_trace(root):
        cfg = grandfather_commit_trace_if_needed(root, cfg)
        grandfathered = True
        result.warnings.append(
            "git.commit_trace was unset — left Off (grandfather). "
            "Enable in brainkm configure → Git, or set git.commit_trace=true."
        )

    # Claude / Antigravity install always persists auto_observe + distill defaults.
    must_save_config = (
        force
        or config is not None
        or http
        or adapter.kind in ("claude", "antigravity")
        or not config_dst.is_file()
        or grandfathered
    )
    if not must_save_config:
        result.files_skipped.append(config_dst)
    else:
        save_brain_config(root, cfg)
        result.files_written.append(config_dst)

    gitignore_entries = GITIGNORE_ENTRIES
    if dev:
        dev_mcp_entry = DEV_MCP_CONFIG_GITIGNORE_PATHS.get(adapter.kind)
        if dev_mcp_entry is not None:
            gitignore_entries = (*gitignore_entries, dev_mcp_entry)

    for entry in gitignore_entries:
        if _ensure_gitignore_entry(root, entry):
            result.files_written.append(root / ".gitignore")

    if should_install_commit_hook(root, cfg):
        try:
            from brainkm.services.git_note import install_post_commit_hook

            hook_result = install_post_commit_hook(
                root,
                brainkm_bin=resolve_hook_command(dev=dev),
            )
            result.warnings.extend(hook_result.warnings)
            if hook_result.installed and hook_result.path is not None:
                result.files_written.append(hook_result.path)
            elif hook_result.skipped and not hook_result.warnings:
                result.warnings.append(
                    "git.commit_trace enabled but post-commit hook not installed (not a git repo?)"
                )
        except Exception as exc:
            result.warnings.append(f"commit-trace hook skipped: {exc}")

        # Same commit_trace gate covers post-checkout/post-merge (VCS state-change
        # hooks) — both keep the code graph / frozen snapshot from silently
        # describing a tree that no longer matches HEAD after a branch switch.
        try:
            from brainkm.services.git_note import (
                install_post_checkout_hook,
                install_post_merge_hook,
            )

            checkout_result = install_post_checkout_hook(
                root, brainkm_bin=resolve_hook_command(dev=dev)
            )
            result.warnings.extend(checkout_result.warnings)
            if checkout_result.installed and checkout_result.path is not None:
                result.files_written.append(checkout_result.path)

            merge_result = install_post_merge_hook(root, brainkm_bin=resolve_hook_command(dev=dev))
            result.warnings.extend(merge_result.warnings)
            if merge_result.installed and merge_result.path is not None:
                result.files_written.append(merge_result.path)
        except Exception as exc:
            result.warnings.append(f"branch-change hooks skipped: {exc}")
    elif cfg.git.commit_trace and config_dst.is_file() and not raw_config_has_commit_trace(root):
        pass  # already warned via grandfather
    elif not cfg.git.commit_trace:
        try:
            from brainkm.services.git_note import (
                uninstall_post_checkout_hook,
                uninstall_post_commit_hook,
                uninstall_post_merge_hook,
            )

            if uninstall_post_commit_hook(root):
                result.warnings.append("removed brainkm post-commit hook (commit_trace=false)")
            if uninstall_post_checkout_hook(root):
                result.warnings.append("removed brainkm post-checkout hook (commit_trace=false)")
            if uninstall_post_merge_hook(root):
                result.warnings.append("removed brainkm post-merge hook (commit_trace=false)")
        except Exception as exc:
            result.warnings.append(f"commit-trace uninstall skipped: {exc}")

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

    # Optional Cursor-side example of Claude hooks schema (only when installing Cursor).
    if adapter.kind == "cursor":
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
