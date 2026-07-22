#!/usr/bin/env python3
"""Antigravity CLI endtask A/B — uniform ``endtask_protocol/1`` Path A.

Default: shared ``endtask_v1`` Core/Full tiers (Cursor graders + MCP integrity).
Optional ``--tier host-smoke`` keeps the older AGY-only soft-grade scenarios.

MCP: prefer ``--home-mcp-swap`` (agy 1.1.x often ignores workspace
``.agents/mcp_config.json``). Tokens: always N/A (``tokens_source=unavailable``).

Examples::

    python brainkm/scripts/antigravity_endtask_harness.py --dry-run --tier core

    python brainkm/scripts/antigravity_endtask_harness.py \\
      --allow-skip-permissions --home-mcp-swap --require-mcp \\
      --tier core --repeats 3
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / "brainkm"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from brainkm.adapters.antigravity_distill import resolve_agy_bin  # noqa: E402
from brainkm.services.endtask_bench import (  # noqa: E402
    ArmName,
    EndTaskGradeResult,
    EndTaskReport,
    EndTaskRunRecord,
    create_worktree,
    estimate_tokens_proxy,
    grade_task,
    install_brainkm_rule,
    load_endtask_fixture,
    remove_worktree,
    seed_endtask_brain,
)
from brainkm.services.endtask_protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    RunManifest,
    build_run_id,
    build_stdio_mcp_config,
    count_mcp_activity,
    enrich_record_protocol_fields,
    fixture_version,
    git_short_sha,
    mcp_ok_for_arm,
    render_protocol_markdown,
    select_tasks_for_tier,
    utc_now_iso,
    write_manifest_json,
    write_protocol_ndjson,
)
from brainkm.services.memory import token_count  # noqa: E402

WITH_ARM_MCP_PREFIX = (
    "ROUTING: This workspace has a brainkm MCP server. Before grepping or "
    "opening many files, call brainkm tools first "
    "(context_pack and/or recall with a path/symbol; traverse for callers). "
    "Verify pack hints in source. Then complete the TASK.\n\n"
)

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

# Legacy host-smoke only (not H2H).
HOST_SMOKE_SCENARIOS = [
    {
        "id": "agy_arch_pivot",
        "class": "knowledge",
        "prompt": (
            "TASK (ignore any CLI flags in this message): In the MemNetwork repo, "
            "open brainkm/brainkm/adapters/antigravity_distill.py and explain: "
            "(1) why AntigravityDistillAdapter shells out to agy print mode, "
            "(2) when RulesDistillAdapter is used as fallback, "
            "(3) when GroqDistillAdapter is used. Quote function names."
        ),
        "must_include_any": [
            ["agy", "print", "-p"],
            ["rules", "RulesDistill"],
            ["groq", "GroqDistill", "cloud_distill"],
        ],
        "min_groups": 2,
    },
]


def ensure_agy_on_path() -> str | None:
    found = resolve_agy_bin()
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "agy"
    if local.is_file() and os.access(local, os.X_OK):
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


def grade_host_smoke(text: str, scenario: dict) -> tuple[bool, str]:
    lower = text.lower()
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
    return hit_groups >= min_groups, f"groups={hit_groups}/{min_groups} ({', '.join(detail_parts)})"


def write_arm_mcp_config(worktree: Path, *, with_brainkm: bool, mcp_project_dir: Path) -> None:
    agents = worktree / ".agents"
    agents.mkdir(parents=True, exist_ok=True)
    if not with_brainkm:
        (agents / "mcp_config.json").write_text(
            json.dumps({"mcpServers": {}}, indent=2) + "\n", encoding="utf-8"
        )
        return
    cfg = build_stdio_mcp_config(repo_or_worktree=mcp_project_dir, brainkm_pkg=_PKG)
    (agents / "mcp_config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    skill_src = _REPO / ".agents" / "skills" / "brainkm-routing" / "SKILL.md"
    if skill_src.is_file():
        skill_dst = agents / "skills" / "brainkm-routing"
        skill_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_src, skill_dst / "SKILL.md")


@contextmanager
def home_mcp_swap(
    *, enabled: bool, with_brainkm: bool, mcp_project_dir: Path
) -> Iterator[None]:
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
                payload = build_stdio_mcp_config(
                    repo_or_worktree=mcp_project_dir, brainkm_pkg=_PKG
                )
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


def run_agy_print(
    *,
    agy_bin: str,
    worktree: Path,
    prompt: str,
    allow_skip_permissions: bool,
    print_timeout: str,
) -> tuple[str, float, str]:
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


def _agy_version(agy_bin: str) -> str:
    """Best-effort CLI version without opening an interactive TTY."""
    try:
        # `agy version` may try bubbletea TTY; prefer --help banner / binary mtime label.
        proc = __import__("subprocess").run(
            [agy_bin, "help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            env={**os.environ, "TERM": "dumb"},
        )
        blob = (proc.stdout or "") + (proc.stderr or "")
        for line in blob.splitlines():
            low = line.lower()
            if "version" in low or "agy" in low:
                return line.strip()[:80]
    except Exception:  # noqa: BLE001
        pass
    return Path(agy_bin).name


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=_REPO)
    p.add_argument(
        "--tier",
        choices=("core", "full", "host-smoke"),
        default="core",
        help="core/full = endtask_v1 H2H; host-smoke = legacy AGY soft scenarios",
    )
    p.add_argument("--tasks", type=str, default="", help="Comma-separated task/scenario ids")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--arms", type=str, default="with_brainkm,without")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-skip-permissions", action="store_true")
    p.add_argument("--print-timeout", type=str, default="5m")
    p.add_argument("--home-mcp-swap", action="store_true")
    p.add_argument("--require-mcp", action="store_true")
    p.add_argument("--no-graph-sync", action="store_true")
    p.add_argument(
        "--work-root",
        type=Path,
        default=_REPO / ".brain" / "agy_endtask_worktrees",
    )
    p.add_argument("--out", type=Path, default=None)
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

    repo = args.repo.resolve()
    task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
    arms: list[ArmName] = [
        a.strip()  # type: ignore[misc]
        for a in args.arms.split(",")
        if a.strip() in ("with_brainkm", "without")
    ]
    fixture = load_endtask_fixture()
    host_smoke = args.tier == "host-smoke"

    if host_smoke:
        scenarios: list[dict[str, Any]] = [
            s
            for s in HOST_SMOKE_SCENARIOS
            if not task_ids or s["id"] in task_ids
        ]
        tasks = scenarios
    else:
        tasks = select_tasks_for_tier(
            fixture,
            tier=args.tier,
            task_ids=task_ids or None,
        )
    if not tasks:
        print("No tasks selected", file=sys.stderr)
        return 1

    sha = git_short_sha(repo)
    started = utc_now_iso()
    run_id = build_run_id(host="antigravity", tier=args.tier, short_sha=sha)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = args.out or (
        _REPO
        / "docs"
        / "benchmarks"
        / f"{today}-endtask-antigravity-{args.tier}.md"
    )

    notes = [
        f"protocol={PROTOCOL_VERSION}",
        f"tier={args.tier}",
        "host=antigravity; tokens_supported=false",
        "MCP via session_activity; prefer --home-mcp-swap",
        f"print-timeout={args.print_timeout}",
    ]
    if args.home_mcp_swap:
        notes.append("home-mcp-swap enabled")
    if args.require_mcp:
        notes.append("require-mcp enabled")

    n_runs = len(tasks) * len(arms) * args.repeats
    print(
        f"Plan: agy={agy_bin} tier={args.tier} tasks={len(tasks)} arms={arms} "
        f"repeats={args.repeats} → {n_runs} runs dry_run={args.dry_run}"
    )
    if args.dry_run:
        for t in tasks:
            print(f"  - {t['id']}")
        return 0

    if not args.allow_skip_permissions:
        print(
            "Refusing live tool-loop without --allow-skip-permissions",
            file=sys.stderr,
        )
        return 2
    if shutil.which("git") is None:
        print("git required for worktrees", file=sys.stderr)
        return 1

    records: list[EndTaskRunRecord] = []
    for task in tasks:
        for arm in arms:
            for rep in range(1, args.repeats + 1):
                label = f"{task['id']}-{arm}-r{rep}"
                print(f"\n=== {label} ===")
                worktree = create_worktree(repo, args.work_root.resolve(), label)
                with_brainkm = arm == "with_brainkm"
                mcp_project = worktree
                if with_brainkm and not host_smoke:
                    seed_info = seed_endtask_brain(
                        worktree,
                        fixture,
                        run_graph_sync=not args.no_graph_sync,
                    )
                    install_brainkm_rule(worktree)
                    print(f"  seeded: {seed_info}")
                elif with_brainkm and host_smoke:
                    # Host-smoke uses shared repo brain for MCP (legacy path).
                    mcp_project = repo

                write_arm_mcp_config(
                    worktree, with_brainkm=with_brainkm, mcp_project_dir=mcp_project
                )
                base_prompt = str(task["prompt"])
                prompt = (
                    WITH_ARM_MCP_PREFIX + base_prompt if with_brainkm else base_prompt
                )
                mtime_before = time.time()
                since_iso = utc_now_iso()
                time.sleep(0.15)
                with home_mcp_swap(
                    enabled=args.home_mcp_swap,
                    with_brainkm=with_brainkm,
                    mcp_project_dir=mcp_project,
                ):
                    stdout, wall_ms, status = run_agy_print(
                        agy_bin=agy_bin,
                        worktree=worktree,
                        prompt=prompt,
                        allow_skip_permissions=True,
                        print_timeout=args.print_timeout,
                    )
                time.sleep(0.4)
                transcript = newest_transcript_after(mtime_before)
                tool_calls = 0
                final_text = stdout
                if transcript is not None:
                    tool_calls, _, _, parsed_final, _user = count_tool_hops(transcript)
                    if parsed_final:
                        final_text = parsed_final

                brain_db = mcp_project / ".brain" / "brain.db"
                if not brain_db.is_file() and host_smoke:
                    brain_db = repo / ".brain" / "brain.db"
                mcp_calls, mcp_tools = count_mcp_activity(brain_db, since_iso=since_iso)
                mcp_ok = mcp_ok_for_arm(arm=arm, mcp_calls=mcp_calls)

                if host_smoke:
                    passed, detail = grade_host_smoke(final_text, task)
                    method = "host_smoke_groups"
                else:
                    grade = grade_task(
                        task, final_text=final_text, worktree=worktree
                    )
                    passed, detail, method = grade.passed, grade.detail, grade.method

                if status != "finished":
                    passed = False
                    detail = f"{detail}; status={status}"
                if args.require_mcp and not mcp_ok:
                    passed = False
                    detail = (
                        f"{detail}; mcp_unused(MCP_db=0)"
                        if with_brainkm
                        else f"{detail}; mcp_leak(MCP_db={mcp_calls})"
                    )

                rec = EndTaskRunRecord(
                    task_id=str(task["id"]),
                    task_class=str(task.get("class") or "knowledge"),
                    arm=arm,
                    repeat=rep,
                    passed=passed,
                    grade_detail=detail,
                    grade_method=method,
                    context_tokens=None,
                    input_tokens=None,
                    output_tokens=None,
                    tokens_proxy=estimate_tokens_proxy(final_text),
                    wall_ms=wall_ms,
                    tool_calls=tool_calls,
                    status=status if status == "finished" else status,
                    error=None if status == "finished" else status,
                    final_text_preview=(final_text or "")[:400],
                    dry_run=False,
                    tokens_source="unavailable",
                    prompt_tokens=None,
                    completion_tokens=None,
                )
                enrich_record_protocol_fields(
                    rec,
                    mcp_calls=mcp_calls,
                    mcp_tools=mcp_tools,
                    tokens_source="unavailable",
                )
                # Debug-only est (not in H2H headline)
                _ = token_count(prompt)
                records.append(rec)
                print(
                    f"  pass={passed} tools={tool_calls} mcp_db={mcp_calls} "
                    f"mcp_ok={mcp_ok} status={status} wall={wall_ms/1000:.1f}s"
                )
                if not args.keep_worktrees:
                    remove_worktree(repo, worktree)

    finished = utc_now_iso()
    manifest = RunManifest(
        protocol_version=PROTOCOL_VERSION,
        fixture_id=str(fixture.get("id") or "endtask_v1"),
        fixture_version=fixture_version(fixture),
        tier=args.tier,
        host="antigravity",
        host_cli_version=_agy_version(agy_bin),
        model="agy-default",
        repo_git_sha=sha,
        harness_git_sha=sha,
        started_at=started,
        finished_at=finished,
        run_id=run_id,
        tokens_supported=False,
        notes=notes,
    )
    report = EndTaskReport(
        records=records,
        model=manifest.model,
        dry_run=False,
        fixture_id=manifest.fixture_id,
        notes=notes,
    )
    md = render_protocol_markdown(report, manifest=manifest)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    write_protocol_ndjson(out.with_suffix(".ndjson"), records, manifest=manifest)
    write_manifest_json(out.with_name(out.stem + ".manifest.json"), manifest)
    print(f"\nWrote {out}")
    print(md)

    with_recs = [r for r in records if r.arm == "with_brainkm"]
    if args.require_mcp and with_recs and not any(r.mcp_ok for r in with_recs):
        print("WARNING: no with_brainkm MCP_ok — not H2H-publishable", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
