#!/usr/bin/env python3
"""Antigravity CLI endtask A/B — live ``agy --print`` tool-loop (Path A).

Measures real agent runs (with vs without brainkm MCP), then parses the
CLI transcript under ``~/.gemini/antigravity-cli/brain/*/.../transcript_full.jsonl``
for **native** tool hops (``VIEW_FILE``, ``GREP_SEARCH``, …).

**MCP ground truth:** counts rows in ``.brain/brain.db`` ``session_activity``
with ``source='mcp'`` during each run window — not transcript string matches
(those false-positive on ``VIEW_FILE`` of ``brainkm/`` paths).

agy CLI often ignores workspace ``.agents/mcp_config.json`` (known 1.1.x
regression). Prefer ``--home-mcp-swap`` so the with-arm temporarily writes
stdio brainkm into ``~/.gemini/config/mcp_config.json`` (restored after).
Use ``--require-mcp`` so with-arm runs with ``mcp_calls=0`` are marked
integrity-fail and excluded from the with-brainkm headline.

Auth: Google account via ``agy login`` (no CURSOR/GROQ/GEMINI API key).
Uses plan quota.

Headless tool use requires ``--dangerously-skip-permissions`` (agy cannot
prompt in ``--print`` mode). Pass ``--allow-skip-permissions`` to opt in.

Examples::

    # Resolve CLI + dry plan
    python brainkm/scripts/antigravity_endtask_harness.py --dry-run

    # Smoke with trustworthy MCP wiring
    python brainkm/scripts/antigravity_endtask_harness.py \\
      --allow-skip-permissions --home-mcp-swap --require-mcp \\
      --tasks agy_arch_pivot --repeats 1
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / "brainkm"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from brainkm.adapters.antigravity_distill import resolve_agy_bin  # noqa: E402
from brainkm.services.endtask_bench import (  # noqa: E402
    create_worktree,
    remove_worktree,
)
from brainkm.services.memory import token_count  # noqa: E402

BRAINKM_MCP_TOOLS = frozenset(
    {
        "brain_stats",
        "recall",
        "context_pack",
        "traverse",
        "trace_changes",
        "remember",
    }
)

WITH_ARM_MCP_PREFIX = (
    "ROUTING: This workspace has a brainkm MCP server. Before grepping or "
    "opening many files, call brainkm tools first "
    "(context_pack and/or recall with a path/symbol; traverse for callers). "
    "Verify pack hints in source. Then answer the TASK.\n\n"
)

# Native AGY step types that count as tool hops (from live IDE transcripts).
AGY_TOOL_STEP_TYPES = frozenset(
    {
        "VIEW_FILE",
        "GREP_SEARCH",
        "LIST_DIRECTORY",
        "RUN_COMMAND",
        "CODE_ACTION",
        "EDIT_FILE",
        "WRITE_TO_FILE",
        "REPLACE_FILE_CONTENT",
        "READ_URL_CONTENT",
        "SEARCH_WEB",
        "FIND_BY_NAME",
        "MULTI_EDIT",
    }
)

SCENARIOS = [
    {
        "id": "agy_arch_pivot",
        "prompt": (
            "TASK (ignore any CLI flags in this message): In the MemNetwork repo, "
            "open brainkm/brainkm/adapters/antigravity_distill.py and explain: "
            "(1) why AntigravityDistillAdapter shells out to agy print mode, "
            "(2) when RulesDistillAdapter is used as fallback, "
            "(3) when GroqDistillAdapter is used. Quote function names."
        ),
        # Any 2 of 3 keyword groups → pass (answers paraphrase).
        "must_include_any": [
            ["agy", "print", "-p"],
            ["rules", "RulesDistill"],
            ["groq", "GroqDistill", "cloud_distill"],
        ],
        "min_groups": 2,
    },
    {
        "id": "agy_ast_refactor",
        "prompt": (
            "TASK: We want to add a UserPromptSubmit-style hook for Antigravity. "
            "Search/read brainkm hooks and adapters; list concrete file paths that "
            "would change (hooks.json, hooks.py, transcript parser, install)."
        ),
        "must_include_any": [
            ["hook", "hooks.json", "PreInvocation"],
            ["antigravity", ".agents"],
            ["transcript", "hooks.py", "install"],
        ],
        "min_groups": 2,
    },
    {
        "id": "agy_git_join",
        "prompt": (
            "TASK: Read brainkm/brainkm/services/antigravity_session.py and summarize "
            "resolve_antigravity_project_dir and how shadow .agents/.brain sessions "
            "are merged. Name the functions."
        ),
        "must_include_any": [
            ["resolve_antigravity_project_dir", "project_dir"],
            ["shadow", "agy_sessions", "merge"],
            ["antigravity_session", "session"],
        ],
        "min_groups": 2,
    },
]


@dataclass
class AgyEndtaskRecord:
    scenario_id: str
    arm: str
    repeat: int
    passed: bool
    grade_detail: str
    tool_calls: int
    tool_types: dict[str, int]
    turns: int
    mcp_calls: int
    mcp_tools: dict[str, int]
    mcp_ok: bool
    prompt_tokens_est: int
    completion_tokens_est: int
    wall_ms: float
    status: str
    transcript_path: str | None
    final_text_preview: str
    user_prompt_ok: bool = True
    error: str | None = None
    # Legacy alias kept in NDJSON for older scorecard parsers.
    mcp_mentions: int = 0


@dataclass
class AgyEndtaskReport:
    records: list[AgyEndtaskRecord] = field(default_factory=list)
    agy_bin: str = ""
    notes: list[str] = field(default_factory=list)
    home_mcp_swap: bool = False
    require_mcp: bool = False


def ensure_agy_on_path() -> str | None:
    """Return agy path; prefer PATH then ~/.local/bin/agy."""
    found = resolve_agy_bin()
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "agy"
    if local.is_file() and os.access(local, os.X_OK):
        # Make subsequent which() work in child processes for this session.
        os.environ["PATH"] = f"{local.parent}:{os.environ.get('PATH', '')}"
        return str(local)
    return None


def list_cli_brain_dirs() -> list[Path]:
    root = Path.home() / ".gemini" / "antigravity-cli" / "brain"
    if not root.is_dir():
        return []
    return sorted(
        [p for p in root.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def newest_transcript_after(mtime_before: float) -> Path | None:
    """Pick the newest transcript_full.jsonl newer than ``mtime_before``."""
    best: Path | None = None
    best_mtime = mtime_before
    for brain in list_cli_brain_dirs():
        candidate = brain / ".system_generated" / "logs" / "transcript_full.jsonl"
        if not candidate.is_file():
            candidate = brain / ".system_generated" / "logs" / "transcript.jsonl"
        if not candidate.is_file():
            continue
        mt = candidate.stat().st_mtime
        if mt > best_mtime and (best is None or mt > best_mtime):
            best = candidate
            best_mtime = mt
    return best


def count_tool_hops(transcript_path: Path) -> tuple[int, dict[str, int], int, str, str]:
    """Return (tool_calls, type_counts, planner_turns, final_text, user_text).

    Native AGY hops only. MCP must be counted via ``count_mcp_activity`` —
    transcript text matching on ``brainkm/`` paths is not MCP use.
    """
    type_counts: dict[str, int] = {}
    tool_calls = 0
    planner_turns = 0
    final_text = ""
    user_text = ""
    for line in transcript_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        step = str(payload.get("type") or "").upper()
        if not step:
            continue
        type_counts[step] = type_counts.get(step, 0) + 1
        if step in AGY_TOOL_STEP_TYPES:
            tool_calls += 1
        if step == "USER_INPUT":
            content = payload.get("content")
            if isinstance(content, str) and content.strip():
                user_text = content.strip()
        if step == "PLANNER_RESPONSE":
            planner_turns += 1
            content = payload.get("content")
            if isinstance(content, str) and content.strip():
                final_text = content.strip()
        raw_calls = payload.get("tool_calls")
        if isinstance(raw_calls, list) and raw_calls and step not in AGY_TOOL_STEP_TYPES:
            tool_calls += len(raw_calls)
    return tool_calls, type_counts, planner_turns, final_text, user_text


def _normalize_mcp_tool_name(raw: str) -> str:
    """Map ``recall:5`` / ``context_pack:22`` → base tool name."""
    name = (raw or "").strip().lower()
    if ":" in name:
        name = name.split(":", 1)[0]
    return name


def count_mcp_activity(
    brain_db: Path, *, since_iso: str
) -> tuple[int, dict[str, int]]:
    """Count brainkm MCP tool invocations after ``since_iso`` (UTC ISO).

    Ground truth from the MCP server write path — not AGY transcript heuristics.
    """
    if not brain_db.is_file():
        return 0, {}
    con = sqlite3.connect(str(brain_db))
    try:
        rows = con.execute(
            "SELECT tool_name FROM session_activity "
            "WHERE source = ? AND created_at >= ?",
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
        # Count all mcp source rows; highlight known brainkm tools in map.
        total += 1
        if base in BRAINKM_MCP_TOOLS or base.split("/")[-1] in BRAINKM_MCP_TOOLS:
            key = base.split("/")[-1]
            tools[key] = tools.get(key, 0) + 1
        else:
            tools[base] = tools.get(base, 0) + 1
    return total, tools


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_stdio_mcp_config(repo: Path) -> dict:
    """Stdio brainkm MCP aimed at the **repo** brain (worktrees lack .brain)."""
    venv_brainkm = repo / ".venv" / "bin" / "brainkm"
    if venv_brainkm.is_file():
        command, args = str(venv_brainkm), ["mcp", "--project-dir", str(repo)]
    else:
        command, args = sys.executable, ["-m", "brainkm", "mcp", "--project-dir", str(repo)]
    return {
        "mcpServers": {
            "brainkm": {
                "command": command,
                "args": args,
                "cwd": str(repo),
                "env": {"PYTHONPATH": str(_PKG)},
            }
        }
    }


def grade_scenario(text: str, scenario: dict) -> tuple[bool, str]:
    """Soft keyword-group grading: need ``min_groups`` groups with any hit."""
    lower = text.lower()
    # Detect argv mis-route (old bug: --print ate --print-timeout as prompt).
    if "print-timeout" in lower and "antigravitydistill" not in lower and "hook" not in lower:
        if "clarify" in lower or "could you" in lower or "flag" in lower:
            return False, "prompt_misrouted(answered_about_print-timeout)"

    groups = scenario.get("must_include_any") or []
    min_groups = int(scenario.get("min_groups") or max(1, len(groups)))
    hit_groups = 0
    detail_parts: list[str] = []
    for group in groups:
        ok = any(str(k).lower() in lower for k in group)
        if ok:
            hit_groups += 1
            detail_parts.append(f"hit:{group[0]}")
        else:
            detail_parts.append(f"miss:{'/'.join(group[:2])}")
    passed = hit_groups >= min_groups
    return passed, f"groups={hit_groups}/{min_groups} ({', '.join(detail_parts)})"


def user_prompt_looks_ok(user_text: str, scenario_prompt: str) -> bool:
    """True if transcript USER_INPUT contains task signal, not only CLI flags."""
    if not user_text:
        return False
    lower = user_text.lower()
    if "print-timeout" in lower and "task" not in lower and "memnetwork" not in lower:
        # Flag-only user message → argv bug
        if "antigravitydistill" not in lower and "hook" not in lower:
            return False
    # Require at least one distinctive token from our prompt
    markers = ("task", "memnetwork", "brainkm", "antigravity", "hook", "session")
    return any(m in lower for m in markers)


def write_arm_mcp_config(worktree: Path, *, with_brainkm: bool, repo: Path) -> None:
    """Install workspace ``.agents/mcp_config.json`` (may be ignored by agy 1.1.x).

    Always use **stdio** aimed at the repo brain — do not copy HTTP ``serverUrl``
    from the project (that looked like a with-arm but often never connected).
    """
    agents = worktree / ".agents"
    agents.mkdir(parents=True, exist_ok=True)
    if not with_brainkm:
        (agents / "mcp_config.json").write_text(
            json.dumps({"mcpServers": {}}, indent=2) + "\n",
            encoding="utf-8",
        )
        return
    cfg = build_stdio_mcp_config(repo)
    (agents / "mcp_config.json").write_text(
        json.dumps(cfg, indent=2) + "\n", encoding="utf-8"
    )
    # Routing skill helps when MCP is actually loaded.
    skill_src = repo / ".agents" / "skills" / "brainkm-routing" / "SKILL.md"
    if skill_src.is_file():
        skill_dst = agents / "skills" / "brainkm-routing"
        skill_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_src, skill_dst / "SKILL.md")


@contextmanager
def home_mcp_swap(*, enabled: bool, with_brainkm: bool, repo: Path) -> Iterator[None]:
    """Temporarily write/clear global AGY MCP configs for a single arm.

    agy CLI frequently fails to load workspace ``.agents/mcp_config.json``;
    home ``~/.gemini/config/mcp_config.json`` is the reliable path. Restores
    prior contents (including empty) on exit.
    """
    if not enabled:
        yield
        return
    primary = Path.home() / ".gemini" / "config" / "mcp_config.json"
    targets = [primary]
    cli_legacy = Path.home() / ".gemini" / "antigravity-cli" / "mcp_config.json"
    if cli_legacy.parent.is_dir():
        targets.append(cli_legacy)

    backups: list[tuple[Path, str | None]] = []
    try:
        for path in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            prev = path.read_text(encoding="utf-8") if path.is_file() else None
            backups.append((path, prev))
            if with_brainkm:
                payload = build_stdio_mcp_config(repo)
                path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            else:
                path.write_text(
                    json.dumps({"mcpServers": {}}, indent=2) + "\n", encoding="utf-8"
                )
        yield
    finally:
        for path, prev in backups:
            if prev is None:
                if path.is_file():
                    path.unlink()
            else:
                path.write_text(prev, encoding="utf-8")


def scenario_prompt_for_arm(scenario: dict, arm: str) -> str:
    base = str(scenario["prompt"])
    if arm == "with_brainkm":
        return WITH_ARM_MCP_PREFIX + base
    return base


def run_agy_print(
    *,
    agy_bin: str,
    worktree: Path,
    prompt: str,
    allow_skip_permissions: bool,
    print_timeout: str,
) -> tuple[str, float, str]:
    """Run ``agy --print <prompt>``. Returns (stdout, wall_ms, status).

    Important: ``--print`` / ``-p`` consumes the *next* argv as the prompt.
    Put all other flags *before* ``--print``, otherwise the timeout flag becomes
    the prompt (that bug made the first full suite meaningless).
    """
    cmd = [agy_bin, f"--print-timeout={print_timeout}"]
    if allow_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd.extend(["--print", prompt])
    t0 = time.perf_counter()
    try:
        completed = __import__("subprocess").run(
            cmd,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=None,
            check=False,
            env={**os.environ, "PATH": f"{Path(agy_bin).parent}:{os.environ.get('PATH', '')}"},
        )
    except Exception as exc:  # noqa: BLE001
        return "", (time.perf_counter() - t0) * 1000.0, f"error:{exc}"
    wall_ms = (time.perf_counter() - t0) * 1000.0
    out = (completed.stdout or "").strip()
    err = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return out or err, wall_ms, f"error:exit_{completed.returncode}:{err[:200]}"
    if "headless mode cannot prompt" in out or "headless mode cannot prompt" in err:
        return out, wall_ms, "error:permissions_denied"
    return out, wall_ms, "finished"


def render_markdown(report: AgyEndtaskReport) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with_recs = [r for r in report.records if r.arm == "with_brainkm"]
    without_recs = [r for r in report.records if r.arm == "without"]
    with_mcp_ok = [r for r in with_recs if r.mcp_ok]

    def _stats(recs: list[AgyEndtaskRecord], *, mcp_arm: bool = False) -> str:
        if not recs:
            return "n=0"
        ok = sum(1 for r in recs if r.passed)
        tools = sum(r.tool_calls for r in recs) / len(recs)
        mcp = sum(r.mcp_calls for r in recs) / len(recs)
        prompt_ok = sum(1 for r in recs if r.user_prompt_ok)
        mcp_ok_n = sum(1 for r in recs if r.mcp_ok)
        extra = ""
        if mcp_arm:
            extra = f" · mcp_ok={mcp_ok_n}/{len(recs)}"
        return (
            f"{ok}/{len(recs)} pass · mean tools={tools:.1f} · "
            f"mean mcp_db={mcp:.1f} · prompt_ok={prompt_ok}/{len(recs)}{extra}"
        )

    integrity = "ok"
    if with_recs and not with_mcp_ok:
        integrity = (
            "INVALID for MCP A/B — no with_brainkm run recorded "
            "session_activity MCP calls (agy likely never loaded brainkm)"
        )
    elif with_recs and len(with_mcp_ok) < len(with_recs):
        integrity = (
            f"PARTIAL — only {len(with_mcp_ok)}/{len(with_recs)} with-arm "
            "runs used MCP (headline below uses mcp_ok subset when require_mcp)"
        )

    lines = [
        "# Antigravity CLI endtask A/B (Path A — live `agy --print`)",
        "",
        f"> **Generated:** {now}  ",
        f"> **agy:** `{report.agy_bin}`  ",
        f"> **Method:** live CLI agent + native transcript hops + "
        f"**MCP via brain.db session_activity** (not pack-vs-dump)",
        f"> **MCP integrity:** {integrity}",
        "",
        "## How to read this",
        "",
        "| Column | Meaning |",
        "|--------|---------|",
        "| **Pass** | Soft keyword groups in the final answer (≥2 groups hit) |",
        "| **Tools** | Native AGY hops (`VIEW_FILE`, `GREP_SEARCH`, …) from transcript |",
        "| **MCP_db** | Rows in `.brain/brain.db` `session_activity` with "
        "`source=mcp` during the run (authoritative) |",
        "| **mcp_ok** | with_brainkm: MCP_db≥1 (or `--require-mcp` off); "
        "without: MCP_db==0 |",
        "| **prompt_ok** | USER_INPUT was the real TASK (not a mis-parsed CLI flag) |",
        "",
        "Do **not** treat transcript path strings containing `brainkm/` as MCP use. "
        "If with-arm `mcp_ok` stays N, the suite is not comparable to Cursor endtask.",
        "",
        "## Headline",
        "",
        f"- **with brainkm (all):** {_stats(with_recs, mcp_arm=True)}",
    ]
    if with_mcp_ok and len(with_mcp_ok) != len(with_recs):
        lines.append(
            f"- **with brainkm (mcp_ok only):** {_stats(with_mcp_ok, mcp_arm=True)}"
        )
    lines.extend(
        [
            f"- **without:** {_stats(without_recs)}",
            "",
            "## Notes",
            "",
        ]
    )
    for n in report.notes:
        lines.append(f"- {n}")
    lines.extend(
        [
            "",
            "## Per-run",
            "",
            "| Scenario | Arm | Rep | Pass | Tools | MCP_db | mcp_ok | prompt_ok | "
            "Turns | Wall | Status | Detail |",
            "|----------|-----|-----|------|-------|--------|--------|-----------|"
            "-------|------|--------|--------|",
        ]
    )
    for r in report.records:
        lines.append(
            f"| `{r.scenario_id}` | {r.arm} | {r.repeat} | "
            f"{'Y' if r.passed else 'N'} | {r.tool_calls} | {r.mcp_calls} | "
            f"{'Y' if r.mcp_ok else 'N'} | "
            f"{'Y' if r.user_prompt_ok else 'N'} | {r.turns} | "
            f"{r.wall_ms/1000:.1f}s | `{r.status}` | {r.grade_detail[:50]} |"
        )
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "```bash",
            "export PATH=\"$HOME/.local/bin:$PATH\"",
            "python brainkm/scripts/antigravity_endtask_harness.py \\",
            "  --allow-skip-permissions --home-mcp-swap --require-mcp --repeats 3",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=_REPO)
    p.add_argument("--tasks", type=str, default="", help="Comma-separated scenario ids")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument(
        "--arms",
        type=str,
        default="with_brainkm,without",
        help="Comma-separated arms",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--allow-skip-permissions",
        action="store_true",
        help="Required for headless tool use (passes --dangerously-skip-permissions)",
    )
    p.add_argument("--print-timeout", type=str, default="5m")
    p.add_argument(
        "--home-mcp-swap",
        action="store_true",
        help=(
            "Temporarily write/clear ~/.gemini/config/mcp_config.json per arm "
            "(agy often ignores workspace .agents/mcp_config.json). Restores after each run."
        ),
    )
    p.add_argument(
        "--require-mcp",
        action="store_true",
        help=(
            "Mark with_brainkm runs as fail when session_activity MCP_db==0; "
            "without-arm fail if MCP_db>0 (leak)."
        ),
    )
    p.add_argument(
        "--work-root",
        type=Path,
        default=_REPO / ".brain" / "agy_endtask_worktrees",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=_REPO
        / "docs"
        / "benchmarks"
        / "2026-07-22-antigravity-endtask.md",
    )
    p.add_argument("--keep-worktrees", action="store_true")
    args = p.parse_args(argv)

    agy_bin = ensure_agy_on_path()
    if not agy_bin:
        print(
            "agy not found. Install:\n"
            "  curl -fsSL https://antigravity.google/cli/install.sh | bash\n"
            "Then: agy login && export PATH=\"$HOME/.local/bin:$PATH\"",
            file=sys.stderr,
        )
        return 1

    task_ids = {t.strip() for t in args.tasks.split(",") if t.strip()}
    scenarios = [
        s for s in SCENARIOS if not task_ids or s["id"] in task_ids
    ]
    if not scenarios:
        print("No scenarios selected", file=sys.stderr)
        return 1
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    notes = [
        "Path A: live agy --print + native transcript hops + MCP via session_activity",
        "Auth: Google OAuth / plan quota (not CURSOR_API_KEY)",
        f"print-timeout={args.print_timeout}",
        "ARGV: flags BEFORE --print (fixes prior suite where --print-timeout was the prompt)",
        "MCP metric: brain.db session_activity source=mcp (not transcript path false positives)",
    ]
    if args.home_mcp_swap:
        notes.append(
            "home-mcp-swap: per-arm write/restore of ~/.gemini/config/mcp_config.json (stdio brainkm)"
        )
    else:
        notes.append(
            "WARNING: without --home-mcp-swap, agy 1.1.x often never loads workspace "
            ".agents/mcp_config.json — expect mcp_ok=N on with-arm"
        )
    if args.require_mcp:
        notes.append("require-mcp: with-arm must have MCP_db≥1; without must have MCP_db=0")
    if args.allow_skip_permissions:
        notes.append(
            "Ran with --dangerously-skip-permissions (required for headless tools)"
        )
    else:
        notes.append(
            "Without --allow-skip-permissions, tool calls are auto-denied in print mode"
        )

    n_runs = len(scenarios) * len(arms) * args.repeats
    print(
        f"Plan: agy={agy_bin} scenarios={len(scenarios)} arms={arms} "
        f"repeats={args.repeats} → {n_runs} runs dry_run={args.dry_run} "
        f"home_mcp_swap={args.home_mcp_swap} require_mcp={args.require_mcp}"
    )
    if args.dry_run:
        for s in scenarios:
            print(f"  - {s['id']}")
        return 0

    if not args.allow_skip_permissions:
        print(
            "Refusing live tool-loop without --allow-skip-permissions "
            "(agy headless cannot prompt for tool approval).",
            file=sys.stderr,
        )
        return 2

    if shutil.which("git") is None:
        print("git required for worktrees", file=sys.stderr)
        return 1

    records: list[AgyEndtaskRecord] = []
    repo = args.repo.resolve()
    brain_db = repo / ".brain" / "brain.db"
    if not brain_db.is_file():
        print(f"Missing brain DB at {brain_db} (needed for MCP_db metric)", file=sys.stderr)
        return 1

    for scenario in scenarios:
        for arm in arms:
            for rep in range(1, args.repeats + 1):
                label = f"{scenario['id']}-{arm}-r{rep}"
                print(f"\n=== {label} ===")
                worktree = create_worktree(repo, args.work_root.resolve(), label)
                with_brainkm = arm == "with_brainkm"
                write_arm_mcp_config(worktree, with_brainkm=with_brainkm, repo=repo)
                prompt = scenario_prompt_for_arm(scenario, arm)
                mtime_before = time.time()
                since_iso = utc_now_iso()
                time.sleep(0.2)
                with home_mcp_swap(
                    enabled=args.home_mcp_swap,
                    with_brainkm=with_brainkm,
                    repo=repo,
                ):
                    stdout, wall_ms, status = run_agy_print(
                        agy_bin=agy_bin,
                        worktree=worktree,
                        prompt=prompt,
                        allow_skip_permissions=True,
                        print_timeout=args.print_timeout,
                    )
                time.sleep(0.5)
                transcript = newest_transcript_after(mtime_before)
                tool_calls = 0
                tool_types: dict[str, int] = {}
                turns = 0
                user_text = ""
                final_text = stdout
                tpath = None
                prompt_ok = True
                if transcript is not None:
                    tpath = str(transcript)
                    (
                        tool_calls,
                        tool_types,
                        turns,
                        parsed_final,
                        user_text,
                    ) = count_tool_hops(transcript)
                    if parsed_final:
                        final_text = parsed_final
                    prompt_ok = user_prompt_looks_ok(user_text, str(scenario["prompt"]))
                mcp_calls, mcp_tools = count_mcp_activity(brain_db, since_iso=since_iso)
                if with_brainkm:
                    mcp_ok = mcp_calls >= 1
                else:
                    mcp_ok = mcp_calls == 0
                passed, detail = grade_scenario(final_text, scenario)
                if not prompt_ok:
                    passed = False
                    detail = f"invalid_prompt; {detail}"
                if status != "finished":
                    passed = False
                    detail = f"{detail}; status={status}"
                if args.require_mcp and not mcp_ok:
                    passed = False
                    if with_brainkm:
                        detail = f"{detail}; mcp_unused(MCP_db=0)"
                    else:
                        detail = f"{detail}; mcp_leak(MCP_db={mcp_calls})"
                elif with_brainkm and mcp_calls == 0:
                    detail = f"{detail}; mcp_unused"
                rec = AgyEndtaskRecord(
                    scenario_id=scenario["id"],
                    arm=arm,
                    repeat=rep,
                    passed=passed,
                    grade_detail=detail,
                    tool_calls=tool_calls,
                    tool_types=tool_types,
                    turns=turns,
                    mcp_calls=mcp_calls,
                    mcp_tools=mcp_tools,
                    mcp_ok=mcp_ok,
                    mcp_mentions=mcp_calls,
                    prompt_tokens_est=token_count(prompt),
                    completion_tokens_est=token_count(final_text),
                    wall_ms=wall_ms,
                    status=status,
                    transcript_path=tpath,
                    final_text_preview=(final_text or "")[:300],
                    user_prompt_ok=prompt_ok,
                    error=None if status == "finished" else status,
                )
                records.append(rec)
                print(
                    f"  pass={passed} tools={tool_calls} mcp_db={mcp_calls} "
                    f"mcp_ok={mcp_ok} prompt_ok={prompt_ok} status={status} "
                    f"wall={wall_ms/1000:.1f}s tools_map={mcp_tools}"
                )
                if not args.keep_worktrees:
                    remove_worktree(repo, worktree)

    report = AgyEndtaskReport(
        records=records,
        agy_bin=agy_bin,
        notes=notes,
        home_mcp_swap=args.home_mcp_swap,
        require_mcp=args.require_mcp,
    )
    md = render_markdown(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    ndjson = args.out.with_suffix(".ndjson")
    with ndjson.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    print(f"\nWrote {args.out}")
    print(f"Wrote {ndjson}")
    print(md)
    with_recs = [r for r in records if r.arm == "with_brainkm"]
    if with_recs and not any(r.mcp_ok for r in with_recs):
        print(
            "\nWARNING: No with_brainkm run used MCP (MCP_db=0). "
            "Scorecard is not a valid brainkm A/B. Re-run with --home-mcp-swap "
            "--require-mcp, or treat as native-tools-only.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
