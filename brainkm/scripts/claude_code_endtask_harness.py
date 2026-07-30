#!/usr/bin/env python3
"""Claude Code CLI endtask A/B — uniform ``endtask_protocol/1.1`` (agent with
brainkm vs without), same shared ``endtask_v1`` Core/Full fixture as the Cursor
and Antigravity harnesses.

Unlike Antigravity (no token API — ``tokens_supported: False``), the ``claude``
CLI's ``-p --output-format stream-json`` print mode returns real per-run
``usage`` (input/output/cache tokens) and ``total_cost_usd`` on its terminal
``result`` event, so this host reports **real** token reduction, same as
Cursor.

Isolation: both arms run with ``--bare`` (skips CLAUDE.md auto-discovery,
hooks, auto-memory — a worktree checkout of this repo carries a tracked root
``CLAUDE.md`` that would otherwise leak brainkm routing text into the
``without`` arm). The ``with_brainkm`` arm instead gets an explicit
``--mcp-config`` (isolated to the seeded worktree) plus a routing prefix
prepended to the prompt, mirroring ``WITH_ARM_MCP_PREFIX`` in the Antigravity
harness. ``--bare`` requires ``ANTHROPIC_API_KEY`` (OAuth/keychain are not
read in that mode).

Examples::

    python brainkm/scripts/claude_code_endtask_harness.py --dry-run --tier core

    python brainkm/scripts/claude_code_endtask_harness.py \\
      --allow-skip-permissions --tier core --repeats 3 \\
      --model claude-haiku-4-5-20251001
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / "brainkm"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from brainkm.services.endtask_bench import (  # noqa: E402
    ArmName,
    EndTaskReport,
    EndTaskRunRecord,
    create_worktree,
    estimate_tokens_proxy,
    grade_task,
    load_endtask_fixture,
    remove_worktree,
    seed_endtask_brain,
)
from brainkm.services.endtask_protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    WITH_ARM_MCP_PREFIX,
    RunManifest,
    build_run_id,
    build_stdio_mcp_config,
    count_mcp_activity,
    enrich_record_protocol_fields,
    fixture_version,
    git_short_sha,
    render_protocol_markdown,
    select_tasks_for_tier,
    utc_now_iso,
    write_manifest_json,
    write_protocol_ndjson,
)


def resolve_claude_bin() -> str | None:
    return shutil.which("claude")


def claude_version(claude_bin: str) -> str:
    try:
        proc = subprocess.run(
            [claude_bin, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        return (proc.stdout or proc.stderr or "").strip()[:80] or Path(claude_bin).name
    except (OSError, subprocess.TimeoutExpired):
        return Path(claude_bin).name


def write_mcp_config(worktree: Path) -> Path:
    """Isolated stdio brainkm MCP config file, aimed at the seeded worktree."""
    cfg = build_stdio_mcp_config(repo_or_worktree=worktree, brainkm_pkg=_PKG)
    dest = worktree / ".claude-endtask-mcp.json"
    dest.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return dest


def run_claude_print(
    *,
    claude_bin: str,
    worktree: Path,
    prompt: str,
    model: str,
    mcp_config_path: Path | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run one ``claude -p`` turn; parse stream-json for tools/usage/result."""
    cmd = [
        claude_bin,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--dangerously-skip-permissions",
        "--bare",
        "--strict-mcp-config",
    ]
    if mcp_config_path is not None:
        cmd.extend(["--mcp-config", str(mcp_config_path)])
    cmd.append(prompt)

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env={**os.environ},
        )
    except subprocess.TimeoutExpired:
        return {
            "final_text": "",
            "tool_calls": 0,
            "status": f"error:timeout_{timeout_seconds:.0f}s",
            "wall_ms": (time.perf_counter() - t0) * 1000.0,
            "num_turns": None,
            "cost_usd": None,
            "prompt_tokens": None,
            "completion_tokens": None,
        }
    wall_ms = (time.perf_counter() - t0) * 1000.0

    tool_calls = 0
    result_event: dict[str, Any] | None = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        etype = payload.get("type")
        if etype == "assistant":
            content = ((payload.get("message") or {}).get("content")) or []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls += 1
        elif etype == "result":
            result_event = payload

    if result_event is None:
        err_tail = (proc.stderr or "").strip()[-300:]
        return {
            "final_text": err_tail,
            "tool_calls": tool_calls,
            "status": f"error:no_result_event(exit={proc.returncode})",
            "wall_ms": wall_ms,
            "num_turns": None,
            "cost_usd": None,
            "prompt_tokens": None,
            "completion_tokens": None,
        }

    is_error = bool(result_event.get("is_error"))
    status = "finished" if not is_error else f"error:{result_event.get('subtype') or 'unknown'}"
    final_text = str(result_event.get("result") or "")
    usage = result_event.get("usage") or {}
    input_tok = usage.get("input_tokens")
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_creation = usage.get("cache_creation_input_tokens") or 0
    prompt_tokens = None
    if input_tok is not None:
        prompt_tokens = int(input_tok) + int(cache_read) + int(cache_creation)
    output_tok = usage.get("output_tokens")
    return {
        "final_text": final_text,
        "tool_calls": tool_calls,
        "status": status,
        "wall_ms": wall_ms,
        "num_turns": result_event.get("num_turns"),
        "cost_usd": result_event.get("total_cost_usd"),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": int(output_tok) if output_tok is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=_REPO)
    p.add_argument("--tier", choices=("core", "full"), default="core")
    p.add_argument("--tasks", type=str, default="", help="Comma-separated task ids")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--arms", type=str, default="with_brainkm,without")
    p.add_argument(
        "--model",
        type=str,
        default="claude-haiku-4-5-20251001",
        help="Model id (default: cheap Haiku 4.5 for benchmark cost control)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-skip-permissions", action="store_true")
    p.add_argument("--timeout", type=float, default=600.0, help="Per-run timeout (seconds)")
    p.add_argument("--require-mcp", action="store_true")
    p.add_argument("--no-graph-sync", action="store_true")
    p.add_argument(
        "--work-root",
        type=Path,
        default=_REPO / ".brain" / "claude_code_endtask_worktrees",
    )
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--keep-worktrees", action="store_true")
    args = p.parse_args(argv)

    claude_bin = resolve_claude_bin()
    if not claude_bin:
        print("claude CLI not found on PATH. Install Claude Code first.", file=sys.stderr)
        return 1

    repo = args.repo.resolve()
    task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
    arms: list[ArmName] = [
        a.strip()  # type: ignore[misc]
        for a in args.arms.split(",")
        if a.strip() in ("with_brainkm", "without")
    ]
    fixture = load_endtask_fixture()
    tasks = select_tasks_for_tier(fixture, tier=args.tier, task_ids=task_ids or None)
    if not tasks:
        print("No tasks selected", file=sys.stderr)
        return 1

    sha = git_short_sha(repo)
    started = utc_now_iso()
    run_id = build_run_id(host="claude_code", tier=args.tier, short_sha=sha)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out = args.out or (
        _REPO / "docs" / "benchmarks" / f"{today}-endtask-claude_code-{args.tier}.md"
    )

    n_runs = len(tasks) * len(arms) * args.repeats
    print(
        f"Plan: claude={claude_bin} model={args.model} tier={args.tier} "
        f"tasks={len(tasks)} arms={arms} repeats={args.repeats} -> {n_runs} runs "
        f"dry_run={args.dry_run}"
    )
    if args.dry_run:
        for t in tasks:
            print(f"  - {t['id']} ({t['class']})")
        return 0

    if not args.allow_skip_permissions:
        print(
            "Refusing live tool-loop without --allow-skip-permissions "
            "(runs use --dangerously-skip-permissions in a disposable worktree).",
            file=sys.stderr,
        )
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print(
            "ANTHROPIC_API_KEY is required for live runs "
            "(--bare mode does not read OAuth/keychain auth).",
            file=sys.stderr,
        )
        return 1
    if shutil.which("git") is None:
        print("git required for worktrees", file=sys.stderr)
        return 1

    notes = [
        f"protocol={PROTOCOL_VERSION}",
        f"tier={args.tier}",
        "host=claude_code; tokens_supported=true (stream-json result.usage)",
        "isolation: --bare (+ --strict-mcp-config); with-arm gets isolated --mcp-config",
        f"model={args.model}",
        f"timeout={args.timeout:.0f}s",
    ]
    if args.require_mcp:
        notes.append("require-mcp enabled")

    records: list[EndTaskRunRecord] = []
    for task in tasks:
        for arm in arms:
            for rep in range(1, args.repeats + 1):
                label = f"{task['id']}-{arm}-r{rep}"
                print(f"\n=== {label} ===")
                worktree = create_worktree(repo, args.work_root.resolve(), label)
                with_brainkm = arm == "with_brainkm"
                mcp_config_path: Path | None = None
                try:
                    if with_brainkm:
                        seed_info = seed_endtask_brain(
                            worktree,
                            fixture,
                            run_graph_sync=not args.no_graph_sync,
                        )
                        mcp_config_path = write_mcp_config(worktree)
                        print(f"  seeded: {seed_info}")

                    base_prompt = str(task["prompt"])
                    prompt = WITH_ARM_MCP_PREFIX + base_prompt if with_brainkm else base_prompt
                    since_iso = utc_now_iso()

                    run = run_claude_print(
                        claude_bin=claude_bin,
                        worktree=worktree,
                        prompt=prompt,
                        model=args.model,
                        mcp_config_path=mcp_config_path,
                        timeout_seconds=args.timeout,
                    )

                    brain_db = worktree / ".brain" / "brain.db"
                    mcp_calls, mcp_tools = count_mcp_activity(brain_db, since_iso=since_iso)

                    status = run["status"]
                    final_text = run["final_text"]
                    if status.startswith("error"):
                        passed, detail, method = False, status, "error"
                    else:
                        grade = grade_task(task, final_text=final_text, worktree=worktree)
                        passed, detail, method = grade.passed, grade.detail, grade.method

                    error = None if status == "finished" else status
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)
                    status = "error"
                    final_text = ""
                    run = {
                        "tool_calls": 0,
                        "wall_ms": 0.0,
                        "prompt_tokens": None,
                        "completion_tokens": None,
                        "cost_usd": None,
                        "num_turns": None,
                    }
                    mcp_calls, mcp_tools = 0, {}
                    passed, detail, method = False, error, "error"
                finally:
                    if not args.keep_worktrees:
                        remove_worktree(repo, worktree)

                rec = EndTaskRunRecord(
                    task_id=str(task["id"]),
                    task_class=str(task.get("class") or "knowledge"),
                    arm=arm,
                    repeat=rep,
                    passed=passed,
                    grade_detail=detail,
                    grade_method=method,
                    context_tokens=run.get("prompt_tokens"),
                    input_tokens=run.get("prompt_tokens"),
                    output_tokens=run.get("completion_tokens"),
                    tokens_proxy=estimate_tokens_proxy(final_text),
                    wall_ms=run.get("wall_ms", 0.0),
                    tool_calls=run.get("tool_calls", 0),
                    status=status,
                    error=error,
                    final_text_preview=(final_text or "")[:400],
                    dry_run=False,
                    tokens_source=(
                        "host_usage" if run.get("prompt_tokens") is not None else "unavailable"
                    ),
                    prompt_tokens=run.get("prompt_tokens"),
                    completion_tokens=run.get("completion_tokens"),
                )
                enrich_record_protocol_fields(
                    rec,
                    mcp_calls=mcp_calls,
                    mcp_tools=mcp_tools,
                    tokens_source=rec.tokens_source,  # type: ignore[arg-type]
                )
                if args.require_mcp:
                    if with_brainkm and mcp_calls < 1:
                        rec.passed = False
                        rec.grade_detail = f"{rec.grade_detail}; mcp_unused(MCP_db=0)"
                    elif not with_brainkm and mcp_calls > 0:
                        rec.passed = False
                        rec.grade_detail = f"{rec.grade_detail}; mcp_leak(MCP_db={mcp_calls})"
                records.append(rec)
                cost = run.get("cost_usd")
                print(
                    f"  pass={rec.passed} tools={rec.tool_calls} mcp_db={mcp_calls} "
                    f"mcp_ok={rec.mcp_ok} prompt_tok={rec.prompt_tokens} "
                    f"cost=${cost if cost is not None else 0:.4f} status={status} "
                    f"wall={rec.wall_ms / 1000:.1f}s"
                )

    finished = utc_now_iso()
    manifest = RunManifest(
        protocol_version=PROTOCOL_VERSION,
        fixture_id=str(fixture.get("id") or "endtask_v1"),
        fixture_version=fixture_version(fixture),
        tier=args.tier,
        host="claude_code",
        host_cli_version=claude_version(claude_bin),
        model=args.model,
        repo_git_sha=sha,
        harness_git_sha=sha,
        started_at=started,
        finished_at=finished,
        run_id=run_id,
        tokens_supported=True,
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
