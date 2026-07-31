"""brainkm uninstall — strip brainkm wiring from a project without wiping user content.

The inverse of :mod:`brainkm.services.install`. Install is merge-only: it adds a
``brainkm`` MCP server entry, hook commands, routing rules/skills and an
``AGENTS.md`` / ``CLAUDE.md`` section into files the user also owns. Uninstall is
therefore *subtractive*, never ``rm`` on a shared file: every JSON/TOML config is
re-read, the brainkm-owned keys removed, and the remainder written back. A file is
deleted only when nothing but brainkm content was left in it.

Project memory (``.brain/``) is user data and survives by default — pass
``purge=True`` to delete it too.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from brainkm.logging_config import get_logger
from brainkm.services.install import (
    BRAINKM_CLAUDE_MCP_TOOL_ALLOWS,
    BRAINKM_CLAUDE_MCP_TOOL_WILDCARD,
    BRAINKM_MCP_SERVER_KEY,
    GITIGNORE_ENTRIES,
    _claude_group_has_brainkm,
    _command_contains_brainkm,
    claude_global_config_path,
    resolve_project_dir,
)

logger = get_logger("services.uninstall")

# Clients whose wiring uninstall knows how to remove (mirrors connect.FIRST_CLASS_CLIENTS).
UNINSTALLABLE_CLIENTS: tuple[str, ...] = ("cursor", "claude", "antigravity", "codex")

_SNIPPET_MARKER = "# brainkm — project memory routing"

# Per-client guidance assets written by ``install_client_guidance_assets``.
# (files to delete, directories to delete, project-md file carrying the snippet)
_CLIENT_ASSETS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {
    "cursor": (
        (".cursor/rules/brainkm.mdc", ".cursor/hooks.claude.example.json"),
        (".cursor/skills/brainkm-routing",),
        "AGENTS.md",
    ),
    "claude": (
        (".claude/rules/brainkm.md",),
        (".claude/skills/brainkm-routing",),
        "CLAUDE.md",
    ),
    "antigravity": (
        (".agents/rules/brainkm.md",),
        (".agents/skills/brainkm-routing",),
        "AGENTS.md",
    ),
    "codex": (
        (".codex/rules/brainkm.md",),
        (".codex/skills/brainkm-routing",),
        "AGENTS.md",
    ),
}

# .gitignore lines install adds that are brainkm-owned. ``.env`` is deliberately
# excluded — it predates brainkm in most projects and removing it would start
# committing secrets.
_BRAINKM_GITIGNORE_ENTRIES: tuple[str, ...] = tuple(
    entry for entry in GITIGNORE_ENTRIES if entry.startswith(".brain/") or entry == "graphify-out/"
)


@dataclass
class UninstallResult:
    """What an uninstall run changed (or would change, when ``dry_run``)."""

    project_dir: Path
    clients: list[str] = field(default_factory=list)
    files_rewritten: list[Path] = field(default_factory=list)
    files_removed: list[Path] = field(default_factory=list)
    files_kept: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False
    purged: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.files_rewritten or self.files_removed)


class _Ops:
    """Filesystem mutations, recorded on the result and skipped when dry-running."""

    def __init__(self, result: UninstallResult, *, dry_run: bool) -> None:
        self.result = result
        self.dry_run = dry_run

    def write_json(self, path: Path, data: object) -> None:
        if not self.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.result.files_rewritten.append(path)

    def write_text(self, path: Path, content: str) -> None:
        if not self.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.result.files_rewritten.append(path)

    def remove_file(self, path: Path) -> None:
        if not self.dry_run:
            path.unlink(missing_ok=True)
        self.result.files_removed.append(path)

    def remove_tree(self, path: Path) -> None:
        if not self.dry_run:
            shutil.rmtree(path, ignore_errors=True)
        self.result.files_removed.append(path)

    def keep(self, path: Path) -> None:
        self.result.files_kept.append(path)

    def warn(self, message: str) -> None:
        self.result.warnings.append(message)


def _load_json_object(path: Path, ops: _Ops) -> dict[str, object] | None:
    """Parsed JSON object, or ``None`` when unreadable (warned) / not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        ops.warn(f"{path} is not valid JSON — left untouched, edit it by hand.")
        return None
    if not isinstance(data, dict):
        ops.warn(f"{path} has an unexpected top-level shape — left untouched.")
        return None
    return data


def _finish_json(path: Path, data: dict[str, object], ops: _Ops, *, changed: bool) -> None:
    """Write back the stripped config, or delete the file when nothing user-owned remains."""
    if not changed:
        ops.keep(path)
        return
    if not data or set(data) == {"version"}:
        ops.remove_file(path)
        return
    ops.write_json(path, data)


# ----------------------------------------------------------------------------
# MCP server entries
# ----------------------------------------------------------------------------


def strip_mcp_server_entry(path: Path, ops: _Ops) -> None:
    """Remove ``mcpServers.brainkm`` from a JSON MCP config, keeping foreign servers."""
    if not path.is_file():
        return
    data = _load_json_object(path, ops)
    if data is None:
        return

    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or BRAINKM_MCP_SERVER_KEY not in servers:
        ops.keep(path)
        return
    del servers[BRAINKM_MCP_SERVER_KEY]
    if servers:
        data["mcpServers"] = servers
    else:
        del data["mcpServers"]
    _finish_json(path, data, ops, changed=True)


def strip_codex_mcp_server(path: Path, ops: _Ops) -> None:
    """Remove ``[mcp_servers.brainkm]`` from ``.codex/config.toml`` (tomlkit-preserving)."""
    if not path.is_file():
        return
    import tomlkit

    try:
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # tomlkit raises several parse error types
        ops.warn(f"{path} is not valid TOML ({exc}) — left untouched, edit it by hand.")
        return

    servers = doc.get("mcp_servers")
    if not isinstance(servers, dict) or BRAINKM_MCP_SERVER_KEY not in servers:
        ops.keep(path)
        return
    del servers[BRAINKM_MCP_SERVER_KEY]
    if not servers:
        del doc["mcp_servers"]

    if not doc:
        ops.remove_file(path)
        return
    ops.write_text(path, tomlkit.dumps(doc))


# ----------------------------------------------------------------------------
# Hooks
# ----------------------------------------------------------------------------


def _strip_flat_hook_entries(hooks: dict[str, object]) -> bool:
    """Cursor schema: ``hooks[event] = [{command, ...}]``. Returns True when changed."""
    changed = False
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = [
            row
            for row in entries
            if not (
                isinstance(row, dict) and _command_contains_brainkm(str(row.get("command", "")))
            )
        ]
        if len(kept) == len(entries):
            continue
        changed = True
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    return changed


def _strip_nested_hook_groups(hooks: dict[str, object]) -> bool:
    """Claude/Codex schema: ``hooks[Event] = [{matcher, hooks: [...]}]``."""
    changed = False
    for event in list(hooks):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        kept = [row for row in groups if not _claude_group_has_brainkm(row)]
        if len(kept) == len(groups):
            continue
        changed = True
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    return changed


def strip_hooks_file(path: Path, ops: _Ops, *, nested: bool) -> None:
    """Remove brainkm hook entries from a hooks JSON file, keeping foreign hooks."""
    if not path.is_file():
        return
    data = _load_json_object(path, ops)
    if data is None:
        return

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        ops.keep(path)
        return
    changed = _strip_nested_hook_groups(hooks) if nested else _strip_flat_hook_entries(hooks)
    if not changed:
        ops.keep(path)
        return
    if hooks:
        data["hooks"] = hooks
    else:
        del data["hooks"]
        # ``description`` is brainkm's own (written by build_codex_hooks_config).
        if str(data.get("description", "")).startswith("brainkm"):
            del data["description"]
    _finish_json(path, data, ops, changed=True)


def strip_antigravity_hooks(path: Path, ops: _Ops) -> None:
    """Antigravity schema: a top-level ``brainkm`` named-handler block."""
    if not path.is_file():
        return
    data = _load_json_object(path, ops)
    if data is None:
        return
    if "brainkm" not in data:
        ops.keep(path)
        return
    del data["brainkm"]
    _finish_json(path, data, ops, changed=True)


# ----------------------------------------------------------------------------
# Claude approval / permission state
# ----------------------------------------------------------------------------


def strip_claude_settings_local(path: Path, ops: _Ops) -> None:
    """Drop brainkm MCP tool allows + server enable from ``.claude/settings.local.json``."""
    if not path.is_file():
        return
    data = _load_json_object(path, ops)
    if data is None:
        return

    changed = False
    brainkm_allows = {*BRAINKM_CLAUDE_MCP_TOOL_ALLOWS, BRAINKM_CLAUDE_MCP_TOOL_WILDCARD}
    permissions = data.get("permissions")
    if isinstance(permissions, dict):
        allow = permissions.get("allow")
        if isinstance(allow, list):
            kept = [item for item in allow if str(item) not in brainkm_allows]
            if len(kept) != len(allow):
                changed = True
                if kept:
                    permissions["allow"] = kept
                else:
                    del permissions["allow"]
        if not permissions:
            data.pop("permissions", None)

    enabled = data.get("enabledMcpjsonServers")
    if isinstance(enabled, list):
        kept_servers = [item for item in enabled if str(item) != BRAINKM_MCP_SERVER_KEY]
        if len(kept_servers) != len(enabled):
            changed = True
            if kept_servers:
                data["enabledMcpjsonServers"] = kept_servers
            else:
                del data["enabledMcpjsonServers"]

    _finish_json(path, data, ops, changed=changed)


def strip_claude_global_approval(
    root: Path,
    ops: _Ops,
    *,
    config_path: Path | None = None,
) -> None:
    """Remove this project's brainkm entry from ``~/.claude.json`` ``enabledMcpjsonServers``.

    Only the project's own key is touched — other projects keep their approval.
    """
    path = config_path or claude_global_config_path()
    if not path.is_file():
        return
    data = _load_json_object(path, ops)
    if data is None:
        return

    projects = data.get("projects")
    if not isinstance(projects, dict):
        return
    project = projects.get(str(root))
    if not isinstance(project, dict):
        return
    enabled = project.get("enabledMcpjsonServers")
    if not isinstance(enabled, list) or BRAINKM_MCP_SERVER_KEY not in enabled:
        return

    project["enabledMcpjsonServers"] = [
        item for item in enabled if str(item) != BRAINKM_MCP_SERVER_KEY
    ]
    if not ops.dry_run:
        tmp_path = path.with_suffix(path.suffix + ".brainkm-tmp")
        tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(path)
    ops.result.files_rewritten.append(path)


# ----------------------------------------------------------------------------
# Guidance assets (rules, skills, AGENTS.md / CLAUDE.md snippet)
# ----------------------------------------------------------------------------


def remove_project_md_snippet(text: str) -> str | None:
    """Strip the brainkm routing section from AGENTS.md / CLAUDE.md content.

    Returns the new content, or ``None`` when the snippet is absent. The section
    runs from its ``# brainkm — project memory routing`` heading to the next
    top-level ``# `` heading (the snippet's own subsections are ``##``), so user
    content written above *or below* it survives.
    """
    start = text.find(_SNIPPET_MARKER)
    if start < 0:
        return None
    line_start = text.rfind("\n", 0, start) + 1
    body_start = start + len(_SNIPPET_MARKER)
    next_heading = re.search(r"^# ", text[body_start:], re.MULTILINE)
    end = body_start + next_heading.start() if next_heading else len(text)

    prefix = text[:line_start].rstrip()
    suffix = text[end:].lstrip("\n")
    if prefix and suffix:
        return prefix + "\n\n" + suffix
    if prefix:
        return prefix + "\n"
    return suffix


def strip_project_md_snippet(path: Path, ops: _Ops) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    new_text = remove_project_md_snippet(text)
    if new_text is None:
        ops.keep(path)
        return
    if not new_text.strip():
        ops.remove_file(path)
        return
    ops.write_text(path, new_text)


def remove_client_guidance_assets(root: Path, client: str, ops: _Ops) -> None:
    """Delete the rule / skill / project-md guidance install wrote for one client."""
    assets = _CLIENT_ASSETS.get(client)
    if assets is None:
        return
    files, dirs, project_md = assets
    for rel in files:
        path = root / rel
        if path.is_file():
            ops.remove_file(path)
    for rel in dirs:
        path = root / rel
        if path.is_dir():
            ops.remove_tree(path)
    strip_project_md_snippet(root / project_md, ops)

    # Prune now-empty scaffolding dirs (.cursor/rules, .claude/skills, …) but
    # never the client config dir itself — the IDE owns that.
    for rel in (*files, *dirs):
        parent = (root / rel).parent
        if parent.is_dir() and parent != root and not any(parent.iterdir()):
            if not ops.dry_run:
                parent.rmdir()


# ----------------------------------------------------------------------------
# Per-client teardown
# ----------------------------------------------------------------------------


def uninstall_client(root: Path, client: str, ops: _Ops) -> None:
    """Remove MCP entry, hooks and guidance assets for a single client."""
    kind = str(client).lower()
    if kind == "cursor":
        strip_mcp_server_entry(root / ".cursor" / "mcp.json", ops)
        strip_hooks_file(root / ".cursor" / "hooks.json", ops, nested=False)
    elif kind == "claude":
        strip_mcp_server_entry(root / ".mcp.json", ops)
        strip_hooks_file(root / ".claude" / "settings.json", ops, nested=True)
        strip_claude_settings_local(root / ".claude" / "settings.local.json", ops)
        strip_claude_global_approval(root, ops)
        legacy = root / ".claude" / "hooks.json"
        if legacy.is_file():
            strip_hooks_file(legacy, ops, nested=True)
    elif kind == "antigravity":
        strip_mcp_server_entry(root / ".agents" / "mcp_config.json", ops)
        strip_antigravity_hooks(root / ".agents" / "hooks.json", ops)
    elif kind == "codex":
        strip_codex_mcp_server(root / ".codex" / "config.toml", ops)
        strip_hooks_file(root / ".codex" / "hooks.json", ops, nested=True)
    else:
        ops.warn(f"unknown client '{client}' — skipped")
        return

    remove_client_guidance_assets(root, kind, ops)


# ----------------------------------------------------------------------------
# Shared teardown
# ----------------------------------------------------------------------------


def _remove_git_hooks(root: Path, ops: _Ops) -> None:
    from brainkm.services.git_note import (
        uninstall_post_checkout_hook,
        uninstall_post_commit_hook,
        uninstall_post_merge_hook,
    )

    hooks_dir = root / ".git" / "hooks"
    names = ("post-commit", "post-checkout", "post-merge")
    if ops.dry_run:
        for name in names:
            path = hooks_dir / name
            if path.is_file() and "brainkm" in path.read_text(encoding="utf-8", errors="ignore"):
                ops.result.files_rewritten.append(path)
        return
    removers = (uninstall_post_commit_hook, uninstall_post_checkout_hook, uninstall_post_merge_hook)
    for name, remover in zip(names, removers, strict=True):
        try:
            if remover(root):
                ops.result.files_rewritten.append(hooks_dir / name)
        except Exception as exc:
            ops.warn(f"git {name} hook removal skipped: {exc}")


def _strip_gitignore_entries(root: Path, ops: _Ops) -> None:
    path = root / ".gitignore"
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip() not in _BRAINKM_GITIGNORE_ENTRIES]
    if len(kept) == len(lines):
        ops.keep(path)
        return
    remaining = "\n".join(kept).rstrip()
    if not remaining:
        ops.remove_file(path)
        return
    ops.write_text(path, remaining + "\n")


def _stop_shared_brain(root: Path, ops: _Ops) -> None:
    from brainkm.services.serve_helper import get_serve_status, stop_serve_background

    try:
        if not get_serve_status(root).running:
            return
        if ops.dry_run:
            ops.warn("shared brain (`brainkm serve`) is running — would be stopped")
            return
        if stop_serve_background(root):
            ops.warn("stopped the shared brain (`brainkm serve`)")
    except Exception as exc:
        ops.warn(f"could not stop `brainkm serve`: {exc} — stop it manually")


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------


def run_uninstall(
    project_dir: Path | None = None,
    *,
    clients: Sequence[str] | None = None,
    purge: bool = False,
    dry_run: bool = False,
    stop_serve: bool = True,
) -> UninstallResult:
    """Remove brainkm wiring from a project.

    Args:
        project_dir: Target project root (defaults to cwd).
        clients: Clients to unwire. ``None`` unwires every client detected on
            disk, falling back to all supported clients when none are detected.
        purge: Also delete ``.brain/`` (project memory) and brainkm's
            ``.gitignore`` entries. Irreversible.
        dry_run: Report what would change without touching the filesystem.
        stop_serve: Stop a running shared brain when the last client is unwired.
    """
    from brainkm.services.connect import detect_wired_clients

    root = resolve_project_dir(project_dir)
    result = UninstallResult(project_dir=root, dry_run=dry_run)
    ops = _Ops(result, dry_run=dry_run)

    wired = detect_wired_clients(root)
    if clients is None:
        targets = list(wired) or list(UNINSTALLABLE_CLIENTS)
    else:
        targets = [str(name).lower() for name in clients]
        unknown = [name for name in targets if name not in UNINSTALLABLE_CLIENTS]
        if unknown:
            msg = f"unknown client(s): {', '.join(unknown)}"
            raise ValueError(msg)
    result.clients = targets

    for client in targets:
        uninstall_client(root, client, ops)

    remaining = [name for name in wired if name not in targets]
    if remaining:
        ops.warn(
            f"still wired for {', '.join(remaining)} — kept git hooks and .brain/. "
            "Re-run without --client to remove everything."
        )
    else:
        _remove_git_hooks(root, ops)
        if stop_serve:
            _stop_shared_brain(root, ops)

    if purge:
        brain_root = root / ".brain"
        if brain_root.is_dir():
            ops.remove_tree(brain_root)
        _strip_gitignore_entries(root, ops)
        result.purged = True
    elif (root / ".brain").is_dir():
        ops.keep(root / ".brain")

    if not result.changed:
        ops.warn("no brainkm wiring found — nothing to remove.")

    logger.info(
        "uninstall complete project_dir=%s clients=%s purge=%s dry_run=%s",
        root,
        ",".join(targets),
        purge,
        dry_run,
    )
    return result
