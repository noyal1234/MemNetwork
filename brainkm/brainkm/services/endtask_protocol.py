"""Uniform multi-host endtask protocol (Cursor / Antigravity / future hosts).

``endtask_protocol/1.1`` — shared fixture tiers, MCP integrity, nullable tokens,
run manifests, and with-arm MCP routing prefix so scorecards are comparable
across hosts. Publish set label: ``endtask_h2h/2`` (see ``H2H_PUBLISH_SET``).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from brainkm import __version__ as BRAINKM_VERSION
from brainkm.services.endtask_bench import (
    ArmName,
    EndTaskReport,
    EndTaskRunRecord,
    load_endtask_fixture,
    select_tasks,
)

PROTOCOL_VERSION = "endtask_protocol/1.1"
TokensSource = Literal["host_usage", "unavailable"]

# Publish-set label for docs / scorecard notes (dated H2H refresh).
# v1 = first Core/Full protocol (Jul 2026); v2 = Cursor+AGY Core both publishable
# with shared WITH_ARM_MCP_PREFIX (Cursor routing parity, 2026-07-30).
H2H_PUBLISH_SET = "endtask_h2h/2"

# Shared with-arm prompt nudge (Cursor / Antigravity / Claude / Codex harnesses).
# Required for fair --require-mcp H2H under protocol/1.1 — without it, agents
# often solve path-explicit tasks via Grep/Read and never call brainkm.
WITH_ARM_MCP_PREFIX = (
    "ROUTING: This workspace has a brainkm MCP server. Before grepping or "
    "opening many files, call brainkm tools first "
    "(context_pack and/or recall with a path/symbol; traverse for callers). "
    "Verify pack hints in source. Then complete the TASK.\n\n"
)

BRAINKM_MCP_TOOLS = frozenset(
    {
        "brain_stats",
        "recall",
        "context_pack",
        "traverse",
        "trace_changes",
        "remember",
        "feedback",
        "checkpoint",
    }
)

# Fallback if fixture omits core_task_ids (4 knowledge + 2 change).
DEFAULT_CORE_TASK_IDS: tuple[str, ...] = (
    "k_budget_cap",
    "k_remember_role",
    "k_fusion_mode",
    "k_layers",
    "c_budget_default",
    "c_endtask_fixture_present",
)


@dataclass
class RunManifest:
    """Versioned run metadata — embed in every published scorecard."""

    protocol_version: str = PROTOCOL_VERSION
    fixture_id: str = "endtask_v1"
    fixture_version: int = 1
    tier: str = "full"
    brainkm_version: str = BRAINKM_VERSION
    host: str = "cursor"
    host_cli_version: str = ""
    model: str = ""
    repo_git_sha: str = ""
    harness_git_sha: str = ""
    started_at: str = ""
    finished_at: str = ""
    run_id: str = ""
    tokens_supported: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def git_short_sha(repo: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def build_run_id(*, host: str, tier: str, short_sha: str, when: datetime | None = None) -> str:
    day = (when or datetime.now(UTC)).strftime("%Y-%m-%d")
    return f"{day}-{host}-{tier}-{short_sha}"


def fixture_version(fixture: dict[str, Any]) -> int:
    raw = fixture.get("version", 1)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def core_task_ids(fixture: dict[str, Any] | None = None) -> list[str]:
    """Pinned Core tier IDs (mixed knowledge + change)."""
    fix = fixture if fixture is not None else load_endtask_fixture()
    ids = fix.get("core_task_ids")
    if isinstance(ids, list) and ids:
        return [str(x) for x in ids]
    return list(DEFAULT_CORE_TASK_IDS)


def select_tasks_for_tier(
    fixture: dict[str, Any],
    *,
    tier: str,
    task_ids: list[str] | None = None,
    smoke_only: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Select tasks for ``core`` | ``full`` (or explicit ids / smoke)."""
    tier_l = (tier or "full").strip().lower()
    if task_ids:
        return select_tasks(fixture, task_ids=task_ids, limit=limit)
    if smoke_only:
        return select_tasks(fixture, smoke_only=True, limit=limit)
    if tier_l == "core":
        return select_tasks(fixture, task_ids=core_task_ids(fixture), limit=limit)
    # full
    return select_tasks(fixture, limit=limit)


def _normalize_mcp_tool_name(raw: str) -> str:
    name = (raw or "").strip().lower()
    if ":" in name:
        name = name.split(":", 1)[0]
    if "/" in name:
        name = name.split("/")[-1]
    return name


def count_mcp_activity(brain_db: Path, *, since_iso: str) -> tuple[int, dict[str, int]]:
    """Count MCP tool rows in ``session_activity`` after ``since_iso``."""
    if not brain_db.is_file():
        return 0, {}
    con = sqlite3.connect(str(brain_db))
    try:
        rows = con.execute(
            "SELECT tool_name FROM session_activity WHERE source = ? AND created_at >= ?",
            ("mcp", since_iso),
        ).fetchall()
    finally:
        con.close()
    tools: dict[str, int] = {}
    total = 0
    for (raw_name,) in rows:
        base = _normalize_mcp_tool_name(str(raw_name or ""))
        if not base:
            continue
        total += 1
        key = base if base in BRAINKM_MCP_TOOLS else base
        tools[key] = tools.get(key, 0) + 1
    return total, tools


def mcp_ok_for_arm(*, arm: ArmName, mcp_calls: int) -> bool:
    if arm == "with_brainkm":
        return mcp_calls >= 1
    return mcp_calls == 0


def resolve_prompt_tokens(rec: EndTaskRunRecord) -> int | None:
    """Host session input tokens, or None when unavailable."""
    if getattr(rec, "prompt_tokens", None) is not None:
        return rec.prompt_tokens
    if rec.context_tokens is not None:
        return rec.context_tokens
    if rec.input_tokens is not None:
        return rec.input_tokens
    return None


def resolve_completion_tokens(rec: EndTaskRunRecord) -> int | None:
    if getattr(rec, "completion_tokens", None) is not None:
        return rec.completion_tokens
    if rec.output_tokens is not None:
        return rec.output_tokens
    return None


def tokens_source_for_record(rec: EndTaskRunRecord) -> TokensSource:
    src = getattr(rec, "tokens_source", None)
    if src in ("host_usage", "unavailable"):
        return src  # type: ignore[return-value]
    if resolve_prompt_tokens(rec) is not None:
        return "host_usage"
    return "unavailable"


def build_stdio_mcp_config(*, repo_or_worktree: Path, brainkm_pkg: Path) -> dict[str, Any]:
    """Stdio brainkm MCP aimed at ``repo_or_worktree`` (usually a seeded worktree)."""
    import sys

    root = repo_or_worktree.resolve()
    venv_brainkm = root / ".venv" / "bin" / "brainkm"
    # Prefer caller repo venv when worktree has no .venv
    if not venv_brainkm.is_file():
        # walk up for .venv/bin/brainkm from brainkm_pkg parents
        for parent in [brainkm_pkg.parent, *brainkm_pkg.parents]:
            candidate = parent / ".venv" / "bin" / "brainkm"
            if candidate.is_file():
                venv_brainkm = candidate
                break
    if venv_brainkm.is_file():
        command, args = str(venv_brainkm), ["mcp", "--project-dir", str(root)]
    else:
        command, args = sys.executable, ["-m", "brainkm", "mcp", "--project-dir", str(root)]
    return {
        "mcpServers": {
            "brainkm": {
                "command": command,
                "args": args,
                "cwd": str(root),
                "env": {"PYTHONPATH": str(brainkm_pkg)},
            }
        }
    }


def enrich_record_protocol_fields(
    rec: EndTaskRunRecord,
    *,
    mcp_calls: int = 0,
    mcp_tools: dict[str, int] | None = None,
    tokens_source: TokensSource | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> EndTaskRunRecord:
    """Attach protocol fields onto an EndTaskRunRecord (mutates and returns)."""
    rec.mcp_calls = mcp_calls
    rec.mcp_tools = mcp_tools or {}
    rec.mcp_ok = mcp_ok_for_arm(arm=rec.arm, mcp_calls=mcp_calls)
    if prompt_tokens is not None:
        rec.prompt_tokens = prompt_tokens
    elif rec.prompt_tokens is None and rec.context_tokens is not None:
        rec.prompt_tokens = rec.context_tokens
    if completion_tokens is not None:
        rec.completion_tokens = completion_tokens
    elif rec.completion_tokens is None and rec.output_tokens is not None:
        rec.completion_tokens = rec.output_tokens
    if tokens_source is not None:
        rec.tokens_source = tokens_source
    elif rec.tokens_source == "unavailable" and rec.prompt_tokens is not None:
        rec.tokens_source = "host_usage"
    return rec


def _arm_protocol_stats(
    records: list[EndTaskRunRecord], arm: ArmName, *, tokens_supported: bool
) -> dict[str, Any]:
    subset = [r for r in records if r.arm == arm and not r.dry_run]
    if not subset:
        return {
            "n": 0,
            "passed": 0,
            "rate": None,
            "mean_prompt_tokens": None,
            "mean_tools": None,
            "mean_mcp": None,
            "mcp_ok_n": 0,
        }
    passed = sum(1 for r in subset if r.passed)
    tools = [float(r.tool_calls) for r in subset]
    mcp = [float(getattr(r, "mcp_calls", 0) or 0) for r in subset]
    mcp_ok_n = sum(1 for r in subset if getattr(r, "mcp_ok", True))
    tok_vals: list[float] = []
    if tokens_supported:
        for r in subset:
            if tokens_source_for_record(r) != "host_usage":
                continue
            pt = resolve_prompt_tokens(r)
            if pt is not None:
                tok_vals.append(float(pt))
    return {
        "n": len(subset),
        "passed": passed,
        "rate": passed / len(subset),
        "mean_prompt_tokens": (sum(tok_vals) / len(tok_vals)) if tok_vals else None,
        "mean_tools": sum(tools) / len(tools),
        "mean_mcp": sum(mcp) / len(mcp),
        "mcp_ok_n": mcp_ok_n,
    }


def render_protocol_markdown(
    report: EndTaskReport,
    *,
    manifest: RunManifest,
) -> str:
    """Uniform H2H scorecard with manifest + nullable tokens."""
    with_s = _arm_protocol_stats(
        report.records, "with_brainkm", tokens_supported=manifest.tokens_supported
    )
    without_s = _arm_protocol_stats(
        report.records, "without", tokens_supported=manifest.tokens_supported
    )

    def _fmt_pass(stats: dict[str, Any]) -> str:
        if not stats["n"]:
            return "n=0"
        return f"{stats['passed']}/{stats['n']}"

    def _fmt_tok(stats: dict[str, Any]) -> str:
        if not manifest.tokens_supported:
            return "N/A"
        t = stats.get("mean_prompt_tokens")
        return "—" if t is None else f"{t:.0f}"

    token_note = ""
    if (
        manifest.tokens_supported
        and with_s.get("mean_prompt_tokens") is not None
        and without_s.get("mean_prompt_tokens") is not None
        and float(without_s["mean_prompt_tokens"]) > 0
    ):
        w = float(with_s["mean_prompt_tokens"])
        wo = float(without_s["mean_prompt_tokens"])
        if w <= wo:
            pct = (1.0 - w / wo) * 100.0
            token_note = f" (−{pct:.0f}% vs without)"
        else:
            token_note = f" ({w / wo:.1f}× vs without)"

    integrity = "ok"
    with_recs = [r for r in report.records if r.arm == "with_brainkm" and not r.dry_run]
    if with_recs and with_s["mcp_ok_n"] == 0:
        integrity = "INVALID — no with_brainkm run recorded MCP (session_activity)"
    elif with_recs and with_s["mcp_ok_n"] < with_s["n"]:
        integrity = f"PARTIAL — mcp_ok {with_s['mcp_ok_n']}/{with_s['n']} on with-arm"

    lines = [
        "# End-task A/B scorecard (uniform protocol)",
        "",
        "## Run manifest",
        "",
        f"- **protocol_version:** `{manifest.protocol_version}`",
        f"- **fixture_id / version:** `{manifest.fixture_id}` / `{manifest.fixture_version}`",
        f"- **tier:** `{manifest.tier}`",
        f"- **host:** `{manifest.host}`",
        f"- **host_cli_version:** `{manifest.host_cli_version or '—'}`",
        f"- **model:** `{manifest.model or report.model}`",
        f"- **brainkm_version:** `{manifest.brainkm_version}`",
        f"- **repo_git_sha:** `{manifest.repo_git_sha or '—'}`",
        f"- **harness_git_sha:** `{manifest.harness_git_sha or '—'}`",
        f"- **run_id:** `{manifest.run_id}`",
        f"- **tokens_supported:** `{manifest.tokens_supported}`",
        f"- **started_at / finished_at:** `{manifest.started_at}` / `{manifest.finished_at}`",
        f"- **MCP integrity:** {integrity}",
        f"- **runs recorded:** {len(report.records)}",
        "",
        "## Headline",
        "",
        "| Arm | Pass | Mean tools | Mean MCP_db | mcp_ok | Mean prompt tokens |",
        "|-----|------|------------|-------------|--------|--------------------|",
        (
            f"| **with brainkm** | {_fmt_pass(with_s)} | "
            f"{(with_s['mean_tools'] if with_s['mean_tools'] is not None else 0):.1f} | "
            f"{(with_s['mean_mcp'] if with_s['mean_mcp'] is not None else 0):.1f} | "
            f"{with_s['mcp_ok_n']}/{with_s['n']} | {_fmt_tok(with_s)}{token_note} |"
        ),
        (
            f"| without | {_fmt_pass(without_s)} | "
            f"{(without_s['mean_tools'] if without_s['mean_tools'] is not None else 0):.1f} | "
            f"{(without_s['mean_mcp'] if without_s['mean_mcp'] is not None else 0):.1f} | "
            f"{without_s['mcp_ok_n']}/{without_s['n']} | {_fmt_tok(without_s)} |"
        ),
        "",
    ]
    if not manifest.tokens_supported:
        lines.extend(
            [
                "> **Tokens:** N/A on this host (`tokens_source=unavailable`). "
                "Do not invent session token reduction from prompt/final-answer estimates.",
                "",
            ]
        )

    lines.extend(
        [
            "## Per-run",
            "",
            "| Task | Class | Arm | Rep | Pass | Tools | MCP_db | mcp_ok | "
            "prompt_tok | Status | Detail |",
            "|------|-------|-----|-----|------|-------|--------|--------|"
            "------------|--------|--------|",
        ]
    )
    for r in report.records:
        pt = resolve_prompt_tokens(r)
        if not manifest.tokens_supported:
            pt_s = "N/A"
        else:
            pt_s = "—" if pt is None else str(pt)
        detail = (r.grade_detail or r.error or "").replace("|", "\\|")[:100]
        lines.append(
            f"| `{r.task_id}` | {r.task_class} | {r.arm} | {r.repeat} | "
            f"{'Y' if r.passed else 'N'} | {r.tool_calls} | "
            f"{getattr(r, 'mcp_calls', 0)} | "
            f"{'Y' if getattr(r, 'mcp_ok', True) else 'N'} | {pt_s} | "
            f"`{r.status}` | {detail} |"
        )

    lines.extend(["", "## Notes", ""])
    seen: set[str] = set()
    for n in list(manifest.notes) + list(report.notes):
        if n in seen:
            continue
        seen.add(n)
        lines.append(f"- {n}")
    lines.append("")
    return "\n".join(lines)


def write_protocol_ndjson(
    path: Path, records: list[EndTaskRunRecord], *, manifest: RunManifest
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_manifest": manifest.to_dict()}, ensure_ascii=False) + "\n")
        for rec in records:
            fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")


def write_manifest_json(path: Path, manifest: RunManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")
