#!/usr/bin/env python3
"""Antigravity CLI endtask A/B — uniform ``endtask_protocol/1.1`` Path A.

Default: shared ``endtask_v1`` Core/Full tiers (Cursor graders + MCP integrity).
Optional ``--tier host-smoke`` keeps the older AGY-only soft-grade scenarios.

MCP: prefer ``--home-mcp-swap`` (agy 1.1.x often ignores workspace
``.agents/mcp_config.json``). Tokens: always N/A (``tokens_source=unavailable``).
Pass ``--model`` (e.g. ``gemini-3.6-flash-low``) to conserve plan quota.

Examples::

    python brainkm/scripts/antigravity_endtask_harness.py --dry-run --tier core

    python brainkm/scripts/antigravity_endtask_harness.py \\
      --allow-skip-permissions --home-mcp-swap --require-mcp \\
      --tier core --repeats 3 --model gemini-3.6-flash-low
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / "brainkm"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from brainkm.adapters.antigravity_distill import resolve_agy_bin  # noqa: E402
from brainkm.services.endtask_bench import (  # noqa: E402
    ArmName,
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
    WITH_ARM_MCP_PREFIX,
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
def home_mcp_swap(*, enabled: bool, with_brainkm: bool, mcp_project_dir: Path) -> Iterator[None]:
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
                payload = build_stdio_mcp_config(repo_or_worktree=mcp_project_dir, brainkm_pkg=_PKG)
                path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            else:
                path.write_text(json.dumps({"mcpServers": {}}, indent=2) + "\n", encoding="utf-8")
        yield
    finally:
        for path, prev in backups:
            if prev is None:
                if path.is_file():
                    path.unlink()
            else:
                path.write_text(prev, encoding="utf-8")


def _parse_print_timeout_seconds(print_timeout: str) -> int:
    """Parse agy ``--print-timeout`` values like ``5m``, ``90s``, ``120`` → seconds."""
    raw = (print_timeout or "5m").strip().lower()
    if raw.endswith("ms") and raw[:-2].isdigit():
        return max(1, int(raw[:-2]) // 1000)
    if raw.endswith("s") and raw[:-1].isdigit():
        return max(1, int(raw[:-1]))
    if raw.endswith("m") and raw[:-1].isdigit():
        return max(1, int(raw[:-1]) * 60)
    if raw.endswith("h") and raw[:-1].isdigit():
        return max(1, int(raw[:-1]) * 3600)
    if raw.isdigit():
        return max(1, int(raw))
    return 300


def _is_quota_error(status: str, text: str = "") -> bool:
    blob = f"{status}\n{text}".lower()
    return "individual quota reached" in blob or "quota reached" in blob


def load_finished_records_from_ndjson(path: Path) -> list[EndTaskRunRecord]:
    """Load prior schedule rows with ``status == finished`` for resume/merge."""
    from dataclasses import fields

    known = {f.name for f in fields(EndTaskRunRecord)}
    out: list[EndTaskRunRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        if "_manifest" in raw:
            continue
        if str(raw.get("status") or "") != "finished":
            continue
        payload = {k: v for k, v in raw.items() if k in known}
        out.append(EndTaskRunRecord(**payload))  # type: ignore[arg-type]
    return out


def run_agy_print(
    *,
    agy_bin: str,
    worktree: Path,
    prompt: str,
    allow_skip_permissions: bool,
    print_timeout: str,
    model: str | None = None,
    effort: str | None = None,
) -> tuple[str, float, str]:
    import signal
    import subprocess
    import tempfile

    cmd = [agy_bin, f"--print-timeout={print_timeout}"]
    if model:
        cmd.append(f"--model={model}")
    if effort:
        cmd.append(f"--effort={effort}")
    if allow_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd.extend(["--print", prompt])
    # Temp files (not pipes): agy often leaves zombie parents while grandchildren
    # keep stdout/stderr open, which hangs subprocess.communicate forever.
    wall_timeout_s = _parse_print_timeout_seconds(print_timeout) + 60
    t0 = time.perf_counter()
    out_path = err_path = None
    proc = None
    try:
        with (
            tempfile.NamedTemporaryFile(
                prefix="agy_stdout_", suffix=".txt", delete=False
            ) as out_f,
            tempfile.NamedTemporaryFile(
                prefix="agy_stderr_", suffix=".txt", delete=False
            ) as err_f,
        ):
            out_path, err_path = Path(out_f.name), Path(err_f.name)
            proc = subprocess.Popen(
                cmd,
                cwd=str(worktree),
                stdout=out_f,
                stderr=err_f,
                text=True,
                start_new_session=True,
                env={
                    **os.environ,
                    "PATH": f"{Path(agy_bin).parent}:{os.environ.get('PATH', '')}",
                },
            )
        deadline = t0 + wall_timeout_s
        while proc.poll() is None:
            if time.perf_counter() >= deadline:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                out = out_path.read_text(encoding="utf-8", errors="replace").strip()
                err = err_path.read_text(encoding="utf-8", errors="replace").strip()
                return (
                    (out or err).strip(),
                    (time.perf_counter() - t0) * 1000.0,
                    f"error:wall_timeout_{wall_timeout_s}s",
                )
            time.sleep(0.25)
        out = out_path.read_text(encoding="utf-8", errors="replace").strip()
        err = err_path.read_text(encoding="utf-8", errors="replace").strip()
        wall_ms = (time.perf_counter() - t0) * 1000.0
        rc = proc.returncode or 0
        if rc != 0:
            status = f"error:exit_{rc}:{err[:200] or out[:200]}"
            return out or err, wall_ms, status
        if "headless mode cannot prompt" in out or "headless mode cannot prompt" in err:
            return out, wall_ms, "error:permissions_denied"
        if _is_quota_error("", out) or _is_quota_error("", err):
            return out or err, wall_ms, f"error:quota:{(err or out)[:200]}"
        return out, wall_ms, "finished"
    except Exception as exc:  # noqa: BLE001
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return "", (time.perf_counter() - t0) * 1000.0, f"error:{exc}"
    finally:
        for p in (out_path, err_path):
            if p is not None:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass


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
    p.add_argument(
        "--model",
        type=str,
        default="",
        help="agy --model id (e.g. gemini-3.6-flash-low). Empty = account default.",
    )
    p.add_argument(
        "--effort",
        type=str,
        default="",
        choices=("", "low", "medium", "high"),
        help="Optional agy --effort (omit when model id already encodes effort).",
    )
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
    p.add_argument(
        "--resume-from",
        type=Path,
        default=None,
        help="Prior protocol ndjson: keep finished rows, re-run only unfinished/missing slots.",
    )
    args = p.parse_args(argv)
    model = (args.model or "").strip() or None
    effort = (args.effort or "").strip() or None
    resume_from = args.resume_from.resolve() if args.resume_from else None
    prior_finished: list[EndTaskRunRecord] = []
    if resume_from is not None:
        if not resume_from.is_file():
            print(f"--resume-from not found: {resume_from}", file=sys.stderr)
            return 1
        prior_finished = load_finished_records_from_ndjson(resume_from)
        print(f"Resume: loaded {len(prior_finished)} finished rows from {resume_from}")

    agy_bin = ensure_agy_on_path()
    if not agy_bin:
        print(
            "agy not found. Install:\n"
            "  curl -fsSL https://antigravity.google/cli/install.sh | bash\n"
            'Then: agy login && export PATH="$HOME/.local/bin:$PATH"',
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
            s for s in HOST_SMOKE_SCENARIOS if not task_ids or s["id"] in task_ids
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
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out = args.out or (
        _REPO / "docs" / "benchmarks" / f"{today}-endtask-antigravity-{args.tier}.md"
    )

    notes = [
        f"protocol={PROTOCOL_VERSION}",
        f"tier={args.tier}",
        "host=antigravity; tokens_supported=false",
        "MCP via session_activity; prefer --home-mcp-swap",
        f"print-timeout={args.print_timeout}",
        f"model={model or 'agy-default'}",
    ]
    if effort:
        notes.append(f"effort={effort}")
    if resume_from is not None:
        notes.append(f"resume-from={resume_from.name} kept_finished={len(prior_finished)}")
        notes.append(
            "multi-model schedule: prior finished rows retained; "
            f"new slots use model={model or 'agy-default'}"
        )
    if args.home_mcp_swap:
        notes.append("home-mcp-swap enabled")
    if args.require_mcp:
        notes.append("require-mcp enabled")

    n_runs = len(tasks) * len(arms) * args.repeats
    skip_keys = {(r.task_id, r.arm, r.repeat) for r in prior_finished}
    schedule_keys = {
        (str(t["id"]), arm, rep)
        for t in tasks
        for arm in arms
        for rep in range(1, args.repeats + 1)
    }
    resume_skip_n = len(skip_keys & schedule_keys)
    remaining = len(schedule_keys) - resume_skip_n
    print(
        f"Plan: agy={agy_bin} tier={args.tier} model={model or 'agy-default'} "
        f"effort={effort or '-'} tasks={len(tasks)} arms={arms} "
        f"repeats={args.repeats} → {n_runs} slots "
        f"(resume_skip={resume_skip_n} remaining={remaining}) dry_run={args.dry_run}"
    )
    if args.dry_run:
        for t in tasks:
            for arm in arms:
                for rep in range(1, args.repeats + 1):
                    key = (str(t["id"]), arm, rep)
                    mark = "skip" if key in skip_keys else "RUN"
                    print(f"  [{mark}] {t['id']}-{arm}-r{rep}")
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

    records: list[EndTaskRunRecord] = list(prior_finished)
    quota_abort = False
    for task in tasks:
        if quota_abort:
            break
        for arm in arms:
            if quota_abort:
                break
            for rep in range(1, args.repeats + 1):
                key = (str(task["id"]), arm, rep)
                if key in skip_keys:
                    print(f"\n=== {task['id']}-{arm}-r{rep} ===\n  resume-skip (finished)")
                    continue
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
                prompt = WITH_ARM_MCP_PREFIX + base_prompt if with_brainkm else base_prompt
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
                        model=model,
                        effort=effort,
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
                    grade = grade_task(task, final_text=final_text, worktree=worktree)
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
                    f"mcp_ok={mcp_ok} status={status} wall={wall_ms / 1000:.1f}s"
                )
                if not args.keep_worktrees:
                    remove_worktree(repo, worktree)

                if _is_quota_error(status, final_text or ""):
                    print(
                        "\nABORT: Antigravity quota reached — refusing incomplete "
                        "scorecard. Re-run after quota resets.",
                        file=sys.stderr,
                    )
                    quota_abort = True
                    break

    if quota_abort:
        notes.append("ABORTED: individual quota reached — not publishable")
        abort_out = out.with_name(out.stem + "-quota-aborted.md")
        out = abort_out

    # Stable schedule order for the merged scorecard.
    # When resuming a subset, keep prior rows ordered by Core/Full ids.
    if resume_from is not None and args.tier in ("core", "full") and not host_smoke:
        order_tasks = select_tasks_for_tier(fixture, tier=args.tier)
        order_arms: list[ArmName] = ["with_brainkm", "without"]
        order_reps = 3
    else:
        order_tasks = tasks
        order_arms = arms
        order_reps = args.repeats
    order_index = {
        (str(t["id"]), arm, rep): i
        for i, (t, arm, rep) in enumerate(
            (t, arm, rep)
            for t in order_tasks
            for arm in order_arms
            for rep in range(1, order_reps + 1)
        )
    }
    records.sort(
        key=lambda r: order_index.get((r.task_id, r.arm, r.repeat), 10_000)
    )

    finished = utc_now_iso()
    if resume_from is not None and model:
        manifest_model = f"mixed:{model}+prior"
    else:
        manifest_model = model or "agy-default"
    manifest = RunManifest(
        protocol_version=PROTOCOL_VERSION,
        fixture_id=str(fixture.get("id") or "endtask_v1"),
        fixture_version=fixture_version(fixture),
        tier=args.tier,
        host="antigravity",
        host_cli_version=_agy_version(agy_bin),
        model=manifest_model,
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
    if quota_abort:
        return 4
    # Resume merges prior finished rows; expect the full retained schedule,
    # not just this invocation's task×arm×repeat product.
    expected_keys = set(order_index.keys()) if resume_from is not None else {
        (str(t["id"]), arm, rep)
        for t in tasks
        for arm in arms
        for rep in range(1, args.repeats + 1)
    }
    got_keys = {(r.task_id, r.arm, r.repeat) for r in records}
    if expected_keys - got_keys:
        print(
            f"WARNING: incomplete schedule missing={sorted(expected_keys - got_keys)[:8]} "
            f"({len(got_keys)}/{len(expected_keys)}) — not publishable",
            file=sys.stderr,
        )
        return 5
    unfinished = [r for r in records if r.status != "finished"]
    if unfinished:
        print(
            f"WARNING: {len(unfinished)} non-finished runs — not publishable",
            file=sys.stderr,
        )
        return 5
    if args.require_mcp and with_recs and not any(r.mcp_ok for r in with_recs):
        print("WARNING: no with_brainkm MCP_ok — not H2H-publishable", file=sys.stderr)
        return 3
    if args.require_mcp and with_recs:
        mcp_ok_n = sum(1 for r in with_recs if r.mcp_ok)
        if mcp_ok_n < len(with_recs):
            print(
                f"WARNING: with-arm mcp_ok {mcp_ok_n}/{len(with_recs)} — "
                "partial MCP integrity (publish only if intentional)",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
