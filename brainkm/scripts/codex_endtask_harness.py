#!/usr/bin/env python3
"""Codex CLI endtask A/B — uniform ``endtask_protocol/1.1`` (agent with brainkm
vs without), same shared ``endtask_v1`` Core/Full fixture as Cursor /
Antigravity / Claude harnesses.

Uses ``codex exec --json`` so scorecards get real ``turn.completed.usage``
tokens (``tokens_supported=true``), unlike Antigravity print-mode.

Auth: reuses saved ChatGPT CLI login in ``~/.codex/auth.json`` by default —
**no OpenAI API key required** for local research. Optional ``CODEX_API_KEY``
overrides for CI-style runs only.

Isolation (fair without-arm):
  - per-run temp ``CODEX_HOME`` (auth.json copied; no user MCP/plugins)
  - ``--ignore-rules`` / ``--ephemeral``; stdin closed
  - neutralize tracked ``AGENTS.md`` (would otherwise leak brainkm routing)
  - with-arm only: ``[mcp_servers.brainkm]`` in that temp home config
  - with-arm prompt gets ``WITH_ARM_MCP_PREFIX``

Default model: ``gpt-5.6-luna`` + ``model_reasoning_effort=low`` (cheaper than
terra) to cut token / plan spend on Core research runs.

Examples::

    python brainkm/scripts/codex_endtask_harness.py --dry-run --tier core

    python brainkm/scripts/codex_endtask_harness.py \\
      --allow-skip-permissions --require-mcp \\
      --tier core --repeats 3 \\
      --model gpt-5.6-luna --reasoning-effort low
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
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

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "low"
CHATGPT_APP_CODEX = Path(
    "/Applications/ChatGPT.app/Contents/Resources/codex"
)

# Minimal stub so tracked AGENTS.md brainkm routing cannot leak into either arm.
ISOLATION_AGENTS_MD = (
    "# Endtask harness isolation\n\n"
    "Follow the TASK in the user message. Do not assume project memory tools "
    "unless they are available via MCP in this session.\n"
)


def resolve_codex_bin() -> str | None:
    """Prefer PATH, then common local installs, then ChatGPT.app bundle."""
    found = shutil.which("codex")
    if found:
        return found
    candidates = (
        Path.home() / ".local" / "bin" / "codex",
        CHATGPT_APP_CODEX,
    )
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def codex_version(codex_bin: str) -> str:
    try:
        proc = subprocess.run(
            [codex_bin, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        text = (proc.stdout or proc.stderr or "").strip()
        # Drop sandbox PATH-alias warnings; keep the version line.
        for line in text.splitlines():
            if "codex" in line.lower() or line[:1].isdigit():
                return line.strip()[:80]
        return text[:80] or Path(codex_bin).name
    except (OSError, subprocess.TimeoutExpired):
        return Path(codex_bin).name


def has_codex_auth() -> bool:
    """True when ChatGPT login or CODEX_API_KEY is available for ``codex exec``."""
    if os.environ.get("CODEX_API_KEY", "").strip():
        return True
    auth = Path.home() / ".codex" / "auth.json"
    if not auth.is_file():
        return False
    try:
        data = json.loads(auth.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("OPENAI_API_KEY"):
        return True
    tokens = data.get("tokens")
    if isinstance(tokens, dict) and (
        tokens.get("access_token") or tokens.get("refresh_token")
    ):
        return True
    return bool(data.get("auth_mode"))


def neutralize_agents_md(worktree: Path) -> None:
    """Replace tracked AGENTS.md so brainkm routing text cannot bias the without arm."""
    path = worktree / "AGENTS.md"
    path.write_text(ISOLATION_AGENTS_MD, encoding="utf-8")


def _brainkm_stdio_entry(worktree: Path) -> tuple[str, list[str], dict[str, str]]:
    cfg = build_stdio_mcp_config(repo_or_worktree=worktree, brainkm_pkg=_PKG)
    entry = (cfg.get("mcpServers") or {}).get("brainkm") or {}
    command = str(entry.get("command") or "")
    raw_args = entry.get("args") or []
    args = [str(a) for a in raw_args] if isinstance(raw_args, list) else []
    env_raw = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    env = {str(k): str(v) for k, v in env_raw.items()}
    return command, args, env


def write_isolated_codex_home(
    *,
    worktree: Path,
    model: str,
    reasoning_effort: str,
    with_brainkm: bool,
) -> Path:
    """Temp ``CODEX_HOME`` with auth + optional brainkm MCP (user plugins stripped)."""
    home = Path(tempfile.mkdtemp(prefix="codex-endtask-home-"))
    src_auth = Path.home() / ".codex" / "auth.json"
    if src_auth.is_file():
        shutil.copy2(src_auth, home / "auth.json")

    lines = [
        "# Generated by codex_endtask_harness — disposable CODEX_HOME.",
        f"model = {json.dumps(model)}",
        f"model_reasoning_effort = {json.dumps(reasoning_effort)}",
    ]
    if with_brainkm:
        command, args, env = _brainkm_stdio_entry(worktree)
        args_toml = ", ".join(json.dumps(a) for a in args)
        lines.extend(
            [
                "",
                "[mcp_servers.brainkm]",
                f"command = {json.dumps(command)}",
                f"args = [{args_toml}]",
            ]
        )
        if env:
            lines.append("")
            lines.append("[mcp_servers.brainkm.env]")
            for key, value in env.items():
                lines.append(f"{key} = {json.dumps(value)}")
    (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return home


def remove_codex_home(home: Path | None) -> None:
    if home is None:
        return
    shutil.rmtree(home, ignore_errors=True)


def parse_codex_exec_jsonl(stdout: str) -> dict[str, Any]:
    """Parse ``codex exec --json`` JSONL into final text / tools / usage."""
    tool_calls = 0
    tool_types: dict[str, int] = {}
    final_text = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    turn_failed = False
    error_msg = ""

    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        etype = str(payload.get("type") or "")

        if etype == "turn.completed":
            usage = payload.get("usage") or {}
            if isinstance(usage, dict):
                inp = usage.get("input_tokens")
                out = usage.get("output_tokens")
                # Codex reports input_tokens as the full prompt bill (cached is a subset).
                if inp is not None:
                    prompt_tokens = int(inp)
                if out is not None:
                    completion_tokens = int(out)
        elif etype == "turn.failed":
            turn_failed = True
            error_msg = str(payload.get("error") or payload.get("message") or "turn_failed")
        elif etype == "error":
            turn_failed = True
            error_msg = str(payload.get("message") or payload.get("error") or "error")
        elif etype in ("item.completed", "item.started"):
            item = payload.get("item")
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type == "mcp_tool_call":
                # Count completed (or started-only) once per item id when possible.
                if etype != "item.completed" and item.get("status") == "in_progress":
                    continue
                tool_calls += 1
                name = str(item.get("tool") or item.get("name") or "mcp_tool_call")
                tool_types[name] = tool_types.get(name, 0) + 1
            elif item_type == "command_execution" and etype == "item.completed":
                tool_calls += 1
                tool_types["command_execution"] = tool_types.get("command_execution", 0) + 1
            elif item_type in ("file_change", "apply_patch") and etype == "item.completed":
                tool_calls += 1
                tool_types[item_type] = tool_types.get(item_type, 0) + 1
            elif item_type == "agent_message" and etype == "item.completed":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    final_text = text

    return {
        "final_text": final_text,
        "tool_calls": tool_calls,
        "tool_types": tool_types,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "turn_failed": turn_failed,
        "error_msg": error_msg,
    }


def run_codex_exec(
    *,
    codex_bin: str,
    worktree: Path,
    prompt: str,
    model: str,
    reasoning_effort: str,
    timeout_seconds: float,
    bypass_approvals: bool,
    codex_home: Path,
) -> dict[str, Any]:
    """Run one ``codex exec --json`` turn in ``worktree`` with isolated ``CODEX_HOME``."""
    cmd = [
        codex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-rules",
        "--cd",
        str(worktree),
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
    ]
    if bypass_approvals:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        # Knowledge-only friendly; change tasks need --allow-skip-permissions.
        cmd.extend(["--sandbox", "workspace-write"])
    cmd.append(prompt)

    env = {**os.environ, "CODEX_HOME": str(codex_home)}
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {
            "final_text": "",
            "tool_calls": 0,
            "status": f"error:timeout_{timeout_seconds:.0f}s",
            "wall_ms": (time.perf_counter() - t0) * 1000.0,
            "prompt_tokens": None,
            "completion_tokens": None,
        }
    wall_ms = (time.perf_counter() - t0) * 1000.0
    parsed = parse_codex_exec_jsonl(proc.stdout or "")

    if parsed["turn_failed"] and not parsed["final_text"]:
        err = parsed["error_msg"] or (proc.stderr or "").strip()[-300:]
        return {
            "final_text": err,
            "tool_calls": parsed["tool_calls"],
            "status": f"error:{err[:120]}",
            "wall_ms": wall_ms,
            "prompt_tokens": parsed["prompt_tokens"],
            "completion_tokens": parsed["completion_tokens"],
        }
    if proc.returncode != 0 and not parsed["final_text"]:
        err_tail = (proc.stderr or proc.stdout or "").strip()[-300:]
        return {
            "final_text": err_tail,
            "tool_calls": parsed["tool_calls"],
            "status": f"error:exit_{proc.returncode}:{err_tail[:120]}",
            "wall_ms": wall_ms,
            "prompt_tokens": parsed["prompt_tokens"],
            "completion_tokens": parsed["completion_tokens"],
        }
    if not parsed["final_text"] and not parsed["tool_calls"]:
        err_tail = (proc.stderr or "").strip()[-300:]
        return {
            "final_text": err_tail,
            "tool_calls": 0,
            "status": f"error:no_agent_message(exit={proc.returncode})",
            "wall_ms": wall_ms,
            "prompt_tokens": parsed["prompt_tokens"],
            "completion_tokens": parsed["completion_tokens"],
        }

    return {
        "final_text": parsed["final_text"],
        "tool_calls": parsed["tool_calls"],
        "status": "finished",
        "wall_ms": wall_ms,
        "prompt_tokens": parsed["prompt_tokens"],
        "completion_tokens": parsed["completion_tokens"],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=_REPO)
    p.add_argument("--tier", choices=("core", "full"), default="core")
    p.add_argument(
        "--fixture",
        type=str,
        default=None,
        help=(
            "Fixture path or packaged name (default: endtask_v1). Use "
            "endtask_memory_v1 for the headroom-positive suite — endtask_v1 is "
            "repo-answerable and cannot discriminate a memory arm on this host."
        ),
    )
    p.add_argument("--tasks", type=str, default="", help="Comma-separated task ids")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--arms", type=str, default="with_brainkm,without")
    p.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Model id (default: {DEFAULT_MODEL} — affordable vs terra)",
    )
    p.add_argument(
        "--reasoning-effort",
        type=str,
        default=DEFAULT_REASONING_EFFORT,
        choices=("low", "medium", "high", "xhigh", "max"),
        help="model_reasoning_effort override (default: low)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--allow-skip-permissions",
        action="store_true",
        help="Required for live runs (uses --dangerously-bypass-approvals-and-sandbox).",
    )
    p.add_argument("--timeout", type=float, default=600.0, help="Per-run timeout (seconds)")
    p.add_argument("--require-mcp", action="store_true")
    p.add_argument("--no-graph-sync", action="store_true")
    p.add_argument(
        "--work-root",
        type=Path,
        default=_REPO / ".brain" / "codex_endtask_worktrees",
    )
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--keep-worktrees", action="store_true")
    p.add_argument(
        "--codex-bin",
        type=str,
        default="",
        help="Override codex binary path (default: PATH / ChatGPT.app bundle)",
    )
    args = p.parse_args(argv)

    codex_bin = args.codex_bin.strip() or resolve_codex_bin()
    if not codex_bin:
        print(
            "codex CLI not found. Install Codex / ChatGPT app, or pass --codex-bin.",
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
    fixture = load_endtask_fixture(args.fixture)
    tasks = select_tasks_for_tier(fixture, tier=args.tier, task_ids=task_ids or None)
    if not tasks:
        print("No tasks selected", file=sys.stderr)
        return 1

    sha = git_short_sha(repo)
    started = utc_now_iso()
    run_id = build_run_id(host="codex", tier=args.tier, short_sha=sha)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out = args.out or (
        _REPO / "docs" / "benchmarks" / f"{today}-endtask-codex-{args.tier}.md"
    )

    n_runs = len(tasks) * len(arms) * args.repeats
    print(
        f"Plan: codex={codex_bin} model={args.model} effort={args.reasoning_effort} "
        f"tier={args.tier} tasks={len(tasks)} arms={arms} repeats={args.repeats} "
        f"-> {n_runs} runs dry_run={args.dry_run}"
    )
    if args.dry_run:
        for t in tasks:
            print(f"  - {t['id']} ({t['class']})")
        return 0

    if not args.allow_skip_permissions:
        print(
            "Refusing live tool-loop without --allow-skip-permissions "
            "(runs use --dangerously-bypass-approvals-and-sandbox in a disposable worktree).",
            file=sys.stderr,
        )
        return 2
    if not has_codex_auth():
        print(
            "Codex auth missing. Run `codex login` (ChatGPT) or set CODEX_API_KEY. "
            "An OpenAI API key is optional for local research when ChatGPT login exists.",
            file=sys.stderr,
        )
        return 1
    if shutil.which("git") is None:
        print("git required for worktrees", file=sys.stderr)
        return 1

    notes = [
        f"protocol={PROTOCOL_VERSION}",
        f"tier={args.tier}",
        "host=codex; tokens_supported=true (codex exec --json turn.completed.usage)",
        "isolation: temp CODEX_HOME (auth only) + --ignore-rules --ephemeral; AGENTS.md neutralized",
        "with-arm: temp CODEX_HOME [mcp_servers.brainkm] + WITH_ARM_MCP_PREFIX",
        "auth: ChatGPT login / CODEX_API_KEY (API key not required when logged in)",
        f"model={args.model}",
        f"model_reasoning_effort={args.reasoning_effort}",
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
                codex_home: Path | None = None
                try:
                    neutralize_agents_md(worktree)
                    if with_brainkm:
                        seed_info = seed_endtask_brain(
                            worktree,
                            fixture,
                            run_graph_sync=not args.no_graph_sync,
                        )
                        print(f"  seeded: {seed_info}")

                    codex_home = write_isolated_codex_home(
                        worktree=worktree,
                        model=args.model,
                        reasoning_effort=args.reasoning_effort,
                        with_brainkm=with_brainkm,
                    )
                    print(f"  codex_home: {codex_home}")

                    base_prompt = str(task["prompt"])
                    prompt = WITH_ARM_MCP_PREFIX + base_prompt if with_brainkm else base_prompt
                    since_iso = utc_now_iso()

                    run = run_codex_exec(
                        codex_bin=codex_bin,
                        worktree=worktree,
                        prompt=prompt,
                        model=args.model,
                        reasoning_effort=args.reasoning_effort,
                        timeout_seconds=args.timeout,
                        bypass_approvals=True,
                        codex_home=codex_home,
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
                    }
                    mcp_calls, mcp_tools = 0, {}
                    passed, detail, method = False, error, "error"
                finally:
                    remove_codex_home(codex_home)
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
                print(
                    f"  pass={rec.passed} tools={rec.tool_calls} mcp_db={mcp_calls} "
                    f"mcp_ok={rec.mcp_ok} prompt_tok={rec.prompt_tokens} "
                    f"status={status} wall={rec.wall_ms / 1000:.1f}s"
                )

    finished = utc_now_iso()
    manifest = RunManifest(
        protocol_version=PROTOCOL_VERSION,
        fixture_id=str(fixture.get("id") or "endtask_v1"),
        fixture_version=fixture_version(fixture),
        tier=args.tier,
        host="codex",
        host_cli_version=codex_version(codex_bin),
        model=f"{args.model}/effort={args.reasoning_effort}",
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
