#!/usr/bin/env python3
"""End-task A/B harness: agent with brainkm vs without.

Backends:

- ``cursor`` (default): full Cursor SDK agent + inline MCP. Needs ``CURSOR_API_KEY``
  and ``pip install cursor-sdk`` / ``pip install -e "./brainkm[endtask]"``.
- ``groq``: knowledge-task A/B via Groq chat + seeded ``context_pack`` (with) vs
  bare prompt (without). Needs ``GROQ_API_KEY`` (env or repo ``.env``). Change
  tasks are skipped — Groq cannot edit the worktree.

Examples::

    # Cost plan only (no API)
    python brainkm/scripts/endtask_harness.py --dry-run --smoke

    # Groq knowledge smoke (uses .env GROQ_API_KEY)
    python brainkm/scripts/endtask_harness.py --backend groq --smoke --repeats 1

    # Cursor live 5-task smoke
    python brainkm/scripts/endtask_harness.py --backend cursor --smoke --repeats 1
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

# Ensure package import when run from repo root without install.
_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / "brainkm"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

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
    plan_runs,
    remove_worktree,
    render_endtask_markdown,
    run_groq_knowledge_arm,
    seed_endtask_brain,
    select_tasks,
    write_ndjson,
)
from brainkm.services.endtask_protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    H2H_PUBLISH_SET,
    WITH_ARM_MCP_PREFIX,
    RunManifest,
    build_run_id,
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=_REPO, help="Git repo root")
    p.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Path to endtask_v1.json (default: packaged fixture)",
    )
    p.add_argument("--smoke", action="store_true", help="Only tasks marked smoke=true")
    p.add_argument(
        "--tier",
        choices=("core", "full"),
        default=None,
        help="endtask_protocol tier (core=6 tasks, full=all). Ignored if --smoke/--tasks set.",
    )
    p.add_argument("--tasks", type=str, default="", help="Comma-separated task ids")
    p.add_argument("--limit", type=int, default=None, help="Max tasks after filter")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument(
        "--require-mcp",
        action="store_true",
        help="Fail with-arm if MCP_db==0; fail without if MCP_db>0",
    )
    p.add_argument(
        "--protocol-scorecard",
        action="store_true",
        help="Write uniform endtask_protocol/1.1 markdown (manifest + mcp_ok + nullable tokens)",
    )
    p.add_argument(
        "--backend",
        choices=("cursor", "groq"),
        default="cursor",
        help="cursor = full agent+MCP; groq = knowledge pack A/B via GROQ_API_KEY",
    )
    p.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model id (default: composer-2.5 for cursor, llama-3.3-70b-versatile for groq)",
    )
    p.add_argument(
        "--arms",
        type=str,
        default="with_brainkm,without",
        help="Comma-separated arms",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ollama-tiebreak", action="store_true")
    p.add_argument(
        "--work-root",
        type=Path,
        default=_REPO / ".brain" / "endtask_worktrees",
        help="Where to create disposable git worktrees",
    )
    p.add_argument(
        "--write-ndjson",
        type=Path,
        default=None,
        help="Write per-run NDJSON (default under docs/benchmarks/)",
    )
    p.add_argument(
        "--write-md",
        type=Path,
        default=None,
        help="Write markdown scorecard",
    )
    p.add_argument(
        "--keep-worktrees",
        action="store_true",
        help="Do not remove worktrees after each run (debug)",
    )
    p.add_argument(
        "--no-graph-sync",
        action="store_true",
        help="Skip graph sync when seeding the with-arm brain",
    )
    return p.parse_args(argv)


def _brainkm_mcp_command(worktree: Path) -> dict:
    """Stdio MCP config for brainkm against the worktree project dir."""
    venv_brainkm = _REPO / ".venv" / "bin" / "brainkm"
    if venv_brainkm.is_file():
        command = str(venv_brainkm)
        args = ["mcp", "--project-dir", str(worktree)]
    else:
        command = sys.executable
        args = ["-m", "brainkm", "mcp", "--project-dir", str(worktree)]
    return {
        "type": "stdio",
        "command": command,
        "args": args,
        "cwd": str(worktree),
        "env": {
            "PYTHONPATH": str(_PKG),
            "PATH": os.environ.get("PATH", ""),
        },
    }


def _run_agent(
    *,
    prompt: str,
    worktree: Path,
    arm: ArmName,
    model: str,
    api_key: str,
) -> tuple[str, dict[str, int | None], str, int]:
    """Returns (final_text, token_fields, status, tool_calls)."""
    try:
        from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions
    except ImportError as exc:
        raise SystemExit(
            "cursor-sdk is required for live runs. "
            'Install with: pip install cursor-sdk   # or pip install -e "./brainkm[endtask]"'
        ) from exc

    mcp_servers = None
    # with-arm: load project rules (brainkm.mdc) so routing matches IDE install.
    # without: empty sources so AGENTS.md / rules cannot leak brainkm guidance.
    setting_sources: list[str] = []
    if arm == "with_brainkm":
        mcp_servers = {"brainkm": _brainkm_mcp_command(worktree)}
        setting_sources = ["project"]

    options = AgentOptions(
        api_key=api_key,
        model=model,
        local=LocalAgentOptions(cwd=str(worktree), setting_sources=setting_sources),
        mcp_servers=mcp_servers,
    )

    tool_calls = 0
    final_text = ""
    try:
        with Agent.create(options) as agent:
            run = agent.send(prompt)
            chunks: list[str] = []
            for message in run.messages():
                mtype = getattr(message, "type", None)
                if mtype == "assistant":
                    content = getattr(getattr(message, "message", None), "content", None)
                    if content:
                        for block in content:
                            if getattr(block, "type", None) == "text":
                                chunks.append(getattr(block, "text", "") or "")
                elif mtype == "tool_call":
                    tool_calls += 1
            result = run.wait()
            status = str(getattr(result, "status", "unknown"))
            final_text = "".join(chunks) or str(getattr(result, "result", "") or "")
            usage = getattr(result, "usage", None) or getattr(run, "usage", None)
            tokens = {
                "context_tokens": None,
                "input_tokens": None,
                "output_tokens": None,
            }
            if usage is not None:
                tokens["input_tokens"] = int(getattr(usage, "input_tokens", 0) or 0)
                tokens["output_tokens"] = int(getattr(usage, "output_tokens", 0) or 0)
                # Prefer input tokens as "context" proxy for A/B comparison.
                tokens["context_tokens"] = tokens["input_tokens"]
            return final_text, tokens, status, tool_calls
    except CursorAgentError as err:
        return (
            "",
            {
                "context_tokens": None,
                "input_tokens": None,
                "output_tokens": None,
            },
            f"startup_error:{err}",
            tool_calls,
        )


def _resolve_model(backend: str, model: str | None) -> str:
    if model:
        return model
    if backend == "groq":
        return "llama-3.3-70b-versatile"
    return "composer-2.5"


def _resolve_groq_key() -> str:
    """GROQ_API_KEY from env, else Settings (.env)."""
    from brainkm.config import get_settings

    env_key = os.environ.get("GROQ_API_KEY", "").strip()
    if env_key:
        return env_key
    return (get_settings().groq_api_key or "").strip()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # Load repo .env for Groq/Cursor keys when running from package path.
    os.chdir(args.repo.resolve())
    repo = args.repo.resolve()
    backend = args.backend
    model = _resolve_model(backend, args.model)
    fixture = load_endtask_fixture(args.fixture)
    task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()] or None
    if task_ids or args.smoke:
        tasks = select_tasks(
            fixture,
            task_ids=task_ids,
            smoke_only=args.smoke,
            limit=args.limit,
        )
    else:
        tier = args.tier or "full"
        tasks = select_tasks_for_tier(fixture, tier=tier, limit=args.limit)
    if backend == "groq":
        skipped_change = [t for t in tasks if t.get("class") == "change"]
        tasks = [t for t in tasks if t.get("class") == "knowledge"]
        if skipped_change:
            print(
                f"Groq backend: skipping {len(skipped_change)} change task(s) (no worktree edits)."
            )
    arms: list[ArmName] = []
    for a in args.arms.split(","):
        a = a.strip()
        if a in ("with_brainkm", "without"):
            arms.append(a)  # type: ignore[arg-type]
    if not arms:
        print("No valid arms", file=sys.stderr)
        return 2
    if not tasks:
        print("No tasks selected after filters", file=sys.stderr)
        return 2

    tier_label = args.tier or ("smoke" if args.smoke else "full")
    plan = plan_runs(fixture, tasks=tasks, repeats=args.repeats, model=model, arms=arms)
    print(
        f"End-task plan: backend={backend} tier={tier_label} protocol={PROTOCOL_VERSION} "
        f"{plan.estimated_runs} runs "
        f"({len(tasks)} tasks × {len(arms)} arms × {plan.repeats} repeats) "
        f"model={plan.model} est≈${plan.estimated_usd:.2f}"
    )
    for t in tasks:
        print(f"  - {t['id']} ({t['class']})")

    if args.dry_run:
        records: list[EndTaskRunRecord] = []
        for task in tasks:
            for arm in arms:
                for rep in range(1, plan.repeats + 1):
                    records.append(
                        EndTaskRunRecord(
                            task_id=str(task["id"]),
                            task_class=str(task["class"]),
                            arm=arm,
                            repeat=rep,
                            passed=False,
                            grade_detail="dry-run",
                            grade_method="none",
                            context_tokens=None,
                            input_tokens=None,
                            output_tokens=None,
                            tokens_proxy=None,
                            wall_ms=0.0,
                            tool_calls=0,
                            status="dry_run",
                            dry_run=True,
                        )
                    )
        report = EndTaskReport(
            records=records,
            model=model,
            dry_run=True,
            fixture_id=str(fixture.get("id") or "endtask_v1"),
            notes=[
                f"Dry-run only — backend={backend}.",
                "cursor: set CURSOR_API_KEY; groq: set GROQ_API_KEY or repo .env.",
            ],
        )
        _write_outputs(args, report, backend=backend)
        print(render_endtask_markdown(report))
        return 0

    if backend == "groq":
        return _run_groq_suite(args, repo, fixture, tasks, arms, plan, model)
    return _run_cursor_suite(args, repo, fixture, tasks, arms, plan, model)


def _run_groq_suite(
    args: argparse.Namespace,
    repo: Path,
    fixture: dict,
    tasks: list[dict],
    arms: list[ArmName],
    plan,
    model: str,
) -> int:
    import tempfile

    key = _resolve_groq_key()
    if not key:
        print(
            "GROQ_API_KEY is required for --backend groq (env or repo .env).",
            file=sys.stderr,
        )
        return 1
    # Ensure httpx path sees the key even if Settings already cached empty.
    os.environ["GROQ_API_KEY"] = key
    from brainkm.config import get_settings

    get_settings.cache_clear()

    records: list[EndTaskRunRecord] = []
    for task in tasks:
        for arm in arms:
            for rep in range(1, plan.repeats + 1):
                label = f"{task['id']}-{arm}-r{rep}"
                print(f"\n=== {label} (groq) ===")
                t0 = time.perf_counter()
                work_dir = Path(tempfile.mkdtemp(prefix=f"endtask-groq-{label}-"))
                error = None
                final_text = ""
                status = "unknown"
                tool_calls = 0
                tokens: dict[str, int | None] = {
                    "context_tokens": None,
                    "input_tokens": None,
                    "output_tokens": None,
                }
                try:
                    final_text, tokens, status, tool_calls = run_groq_knowledge_arm(
                        task,
                        arm=arm,
                        fixture=fixture,
                        work_dir=work_dir,
                        model=model,
                    )
                    if status.startswith("startup_error") or status.startswith("error:"):
                        grade = EndTaskGradeResult(passed=False, detail=status, method="error")
                        error = status
                    else:
                        grade = grade_task(
                            task,
                            final_text=final_text,
                            worktree=work_dir,
                            use_ollama_tiebreak=args.ollama_tiebreak,
                        )
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)
                    status = "error"
                    grade = EndTaskGradeResult(passed=False, detail=error, method="error")
                finally:
                    wall_ms = (time.perf_counter() - t0) * 1000.0
                    if not args.keep_worktrees:
                        shutil.rmtree(work_dir, ignore_errors=True)

                proxy = estimate_tokens_proxy(final_text)
                rec = EndTaskRunRecord(
                    task_id=str(task["id"]),
                    task_class=str(task["class"]),
                    arm=arm,
                    repeat=rep,
                    passed=grade.passed,
                    grade_detail=grade.detail,
                    grade_method=grade.method,
                    context_tokens=tokens.get("context_tokens"),
                    input_tokens=tokens.get("input_tokens"),
                    output_tokens=tokens.get("output_tokens"),
                    tokens_proxy=proxy,
                    wall_ms=wall_ms,
                    tool_calls=tool_calls,
                    status=status,
                    error=error,
                    final_text_preview=(final_text or "")[:400],
                    dry_run=False,
                )
                records.append(rec)
                print(
                    f"  pass={rec.passed} status={rec.status} "
                    f"tokens={rec.context_tokens or rec.tokens_proxy} "
                    f"detail={rec.grade_detail[:120]}"
                )
                preview = (final_text or "").replace("\n", " ")[:160]
                if preview:
                    print(f"  answer: {preview}")

    report = EndTaskReport(
        records=records,
        model=model,
        dry_run=False,
        fixture_id=str(fixture.get("id") or "endtask_v1"),
        notes=[
            "backend=groq (knowledge pack A/B; not full Cursor agent)",
            f"repeats={plan.repeats}",
            "Change tasks skipped on groq backend.",
            "Publish Cursor agent results separately for the full marketing claim.",
        ],
    )
    _write_outputs(args, report, backend="groq")
    print("\n" + render_endtask_markdown(report))
    return 0


def _run_cursor_suite(
    args: argparse.Namespace,
    repo: Path,
    fixture: dict,
    tasks: list[dict],
    arms: list[ArmName],
    plan,
    model: str,
) -> int:
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        print(
            "CURSOR_API_KEY is required for --backend cursor (or use --backend groq).",
            file=sys.stderr,
        )
        return 1

    if shutil.which("git") is None:
        print("git is required to create worktrees", file=sys.stderr)
        return 1

    records = []
    for task in tasks:
        for arm in arms:
            for rep in range(1, plan.repeats + 1):
                label = f"{task['id']}-{arm}-r{rep}"
                print(f"\n=== {label} ===")
                t0 = time.perf_counter()
                worktree = create_worktree(repo, args.work_root.resolve(), label)
                error = None
                final_text = ""
                status = "unknown"
                tool_calls = 0
                tokens = {
                    "context_tokens": None,
                    "input_tokens": None,
                    "output_tokens": None,
                }
                mcp_calls = 0
                mcp_tools: dict = {}
                since_iso = utc_now_iso()
                try:
                    if arm == "with_brainkm":
                        seed_info = seed_endtask_brain(
                            worktree,
                            fixture,
                            run_graph_sync=not args.no_graph_sync,
                        )
                        install_brainkm_rule(worktree)
                        print(f"  seeded brain: {seed_info}")
                    base_prompt = str(task["prompt"])
                    prompt = (
                        WITH_ARM_MCP_PREFIX + base_prompt
                        if arm == "with_brainkm"
                        else base_prompt
                    )
                    final_text, tokens, status, tool_calls = _run_agent(
                        prompt=prompt,
                        worktree=worktree,
                        arm=arm,
                        model=model,
                        api_key=api_key,
                    )
                    brain_db = worktree / ".brain" / "brain.db"
                    mcp_calls, mcp_tools = count_mcp_activity(brain_db, since_iso=since_iso)
                    if status.startswith("startup_error"):
                        grade = EndTaskGradeResult(passed=False, detail=status, method="error")
                        error = status
                    else:
                        grade = grade_task(
                            task,
                            final_text=final_text,
                            worktree=worktree,
                            use_ollama_tiebreak=args.ollama_tiebreak,
                        )
                    if args.require_mcp:
                        if arm == "with_brainkm" and mcp_calls < 1:
                            grade = EndTaskGradeResult(
                                passed=False,
                                detail=f"{grade.detail}; mcp_unused(MCP_db=0)",
                                method=grade.method,
                            )
                        elif arm == "without" and mcp_calls > 0:
                            grade = EndTaskGradeResult(
                                passed=False,
                                detail=f"{grade.detail}; mcp_leak(MCP_db={mcp_calls})",
                                method=grade.method,
                            )
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)
                    status = "error"
                    grade = EndTaskGradeResult(passed=False, detail=error, method="error")
                finally:
                    wall_ms = (time.perf_counter() - t0) * 1000.0
                    if not args.keep_worktrees:
                        remove_worktree(repo, worktree)

                proxy = estimate_tokens_proxy(final_text)
                prompt_tok = tokens.get("context_tokens")
                completion_tok = tokens.get("output_tokens")
                rec = EndTaskRunRecord(
                    task_id=str(task["id"]),
                    task_class=str(task["class"]),
                    arm=arm,
                    repeat=rep,
                    passed=grade.passed,
                    grade_detail=grade.detail,
                    grade_method=grade.method,
                    context_tokens=tokens.get("context_tokens"),  # type: ignore[arg-type]
                    input_tokens=tokens.get("input_tokens"),  # type: ignore[arg-type]
                    output_tokens=tokens.get("output_tokens"),  # type: ignore[arg-type]
                    tokens_proxy=proxy,
                    wall_ms=wall_ms,
                    tool_calls=tool_calls,
                    status=status,
                    error=error,
                    final_text_preview=(final_text or "")[:400],
                    dry_run=False,
                    tokens_source="host_usage" if prompt_tok is not None else "unavailable",
                    prompt_tokens=prompt_tok,  # type: ignore[arg-type]
                    completion_tokens=completion_tok,  # type: ignore[arg-type]
                )
                enrich_record_protocol_fields(
                    rec,
                    mcp_calls=mcp_calls,
                    mcp_tools=mcp_tools,
                    tokens_source=rec.tokens_source,  # type: ignore[arg-type]
                )
                records.append(rec)
                print(
                    f"  pass={rec.passed} status={rec.status} "
                    f"tokens={rec.context_tokens or rec.tokens_proxy} "
                    f"mcp_db={mcp_calls} mcp_ok={rec.mcp_ok} "
                    f"detail={rec.grade_detail[:120]}"
                )

    sha = git_short_sha(repo)
    tier_label = args.tier or "full"
    started = utc_now_iso()
    report = EndTaskReport(
        records=records,
        model=model,
        dry_run=False,
        fixture_id=str(fixture.get("id") or "endtask_v1"),
        notes=[
            "backend=cursor",
            f"protocol={PROTOCOL_VERSION}",
            f"h2h_publish_set={H2H_PUBLISH_SET}",
            f"tier={tier_label}",
            f"repeats={plan.repeats}",
            "tokens_source=host_usage when SDK returns usage",
            "with-arm MCP routing: WITH_ARM_MCP_PREFIX + setting_sources=project",
            "Nondeterministic — re-run with --repeats 3 before publishing claims.",
        ],
    )
    manifest = RunManifest(
        protocol_version=PROTOCOL_VERSION,
        fixture_id=report.fixture_id,
        fixture_version=fixture_version(fixture),
        tier=tier_label,
        host="cursor",
        host_cli_version="cursor-sdk",
        model=model,
        repo_git_sha=sha,
        harness_git_sha=sha,
        started_at=started,
        finished_at=utc_now_iso(),
        run_id=build_run_id(host="cursor", tier=tier_label, short_sha=sha),
        tokens_supported=True,
        notes=list(report.notes),
    )
    _write_outputs(args, report, backend="cursor", manifest=manifest)
    if args.protocol_scorecard or args.tier:
        print("\n" + render_protocol_markdown(report, manifest=manifest))
    else:
        print("\n" + render_endtask_markdown(report))
    return 0


def _write_outputs(
    args: argparse.Namespace,
    report: EndTaskReport,
    *,
    backend: str = "cursor",
    manifest: RunManifest | None = None,
) -> None:
    from datetime import date

    today = date.today().isoformat()
    ndjson = args.write_ndjson
    md = args.write_md
    tier = getattr(args, "tier", None) or "full"
    if ndjson is None and md is None:
        out_dir = _REPO / "docs" / "benchmarks"
        suffix = "dry" if report.dry_run else backend
        if getattr(args, "tier", None):
            suffix = f"{backend}-{tier}"
        ndjson = out_dir / f"{today}-endtask-{suffix}.ndjson"
        md = out_dir / f"{today}-endtask-{suffix}.md"
    use_protocol = bool(
        manifest and (getattr(args, "protocol_scorecard", False) or getattr(args, "tier", None))
    )
    if ndjson is not None:
        if use_protocol and manifest is not None:
            write_protocol_ndjson(ndjson, report.records, manifest=manifest)
            write_manifest_json(ndjson.with_name(ndjson.stem + ".manifest.json"), manifest)
        else:
            write_ndjson(ndjson, report.records)
        print(f"Wrote NDJSON: {ndjson}")
    if md is not None:
        md.parent.mkdir(parents=True, exist_ok=True)
        if use_protocol and manifest is not None:
            md.write_text(render_protocol_markdown(report, manifest=manifest), encoding="utf-8")
        else:
            md.write_text(render_endtask_markdown(report), encoding="utf-8")
        print(f"Wrote scorecard: {md}")


if __name__ == "__main__":
    raise SystemExit(main())
