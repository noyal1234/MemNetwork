"""brainkm CLI — install, capture/handover, graph sync, Cursor hooks, bench/review/hygiene, MCP server."""

import json
from pathlib import Path

import typer

from brainkm.logging_config import get_logger

app = typer.Typer(
    name="brainkm",
    help="MemNetwork local project brain — MCP server and CLI",
    no_args_is_help=True,
)

logger = get_logger("cli")


@app.callback()
def main() -> None:
    """Initialize logging for all subcommands."""
    from brainkm.logging_config import configure_logging

    configure_logging()


@app.command()
def version() -> None:
    """Print installed version."""
    from brainkm import __version__

    logger.debug("version requested")
    typer.echo(__version__)


@app.command("configure")
def configure_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
) -> None:
    """Launch the Textual configuration dashboard."""
    try:
        from brainkm.tui.app import BrainkmConfigureApp
    except ImportError:
        typer.echo(
            "Textual is not installed. Run:\n"
            '  pip install -e "./brainkm[tui]"',
            err=True,
        )
        raise typer.Exit(code=1)

    # Detach stderr logging *before* Textual takes over the terminal. Waiting
    # until App.on_mount is too late — Textual may already have replaced
    # sys.stderr, and migration INFO lines then paint above the UI.
    from brainkm.logging_config import install_tui_logging, restore_stderr_logging

    install_tui_logging()
    try:
        BrainkmConfigureApp(project_dir=project_dir).run()
    finally:
        restore_stderr_logging()


@app.command("migrate")
def migrate_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
) -> None:
    """Apply pending database migrations to .brain/brain.db."""
    from brainkm.db.migrate import migrate

    applied = migrate(project_dir=project_dir)
    if applied:
        typer.echo(f"Applied migrations: {', '.join(applied)}")
    else:
        typer.echo("Database schema is up to date")


@app.command("capture")
def capture_cmd(
    transcript: Path = typer.Argument(..., help="Path to agent-transcript JSONL file"),
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    session_id: str | None = typer.Option(None, help="Override session id"),
) -> None:
    """Ingest a Cursor transcript: chunks → distill → neurons + chunk_sources."""
    from brainkm.services.capture import capture_transcript_file

    result = capture_transcript_file(
        transcript,
        project_dir=project_dir,
        session_id=session_id,
    )
    if result.skipped:
        typer.echo(f"Skipped: {result.reason}")
        raise typer.Exit(code=0)
    typer.echo(
        f"Captured session {result.session_id}: "
        f"{result.chunk_count} chunks, {result.neuron_count} neurons ({result.distill_mode})"
    )


def _hook_client_option() -> str:
    return typer.Option(
        "cursor",
        "--client",
        help="Hook host: cursor | claude | antigravity (stdout envelope + fail-soft)",
    )


@app.command("handover")
def handover_cmd(
    transcript: Path | None = typer.Argument(
        None,
        help="Path to agent-transcript JSONL (omit when using --stdin)",
    ),
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    session_id: str | None = typer.Option(None, help="Override session id"),
    stdin: bool = typer.Option(
        False,
        "--stdin",
        help="Read PreCompact hook payload JSON from stdin",
    ),
    client: str = _hook_client_option(),
) -> None:
    """PreCompact handover: distill transcript, WAL checkpoint, exit 0 when durable."""
    import sys

    from brainkm.services.handover import run_handover, run_handover_from_stdin

    kind = (client or "cursor").strip().lower()
    # Hook mode (--stdin): keep stdout JSON-clean (empty). Manual CLI keeps status lines.
    hook_mode = bool(stdin)
    # Hooks must never block the host. Manual CLI still surfaces checkpoint failure
    # for Cursor; Claude/Antigravity stay fail-soft in both modes.
    fail_soft = kind in ("claude", "antigravity") or hook_mode

    try:
        if stdin:
            payload = sys.stdin.read()
            result = run_handover_from_stdin(payload, project_dir=project_dir)
        elif transcript is not None:
            result = run_handover(
                transcript,
                project_dir=project_dir,
                session_id=session_id,
            )
        else:
            typer.echo("Provide a transcript path or use --stdin", err=True)
            raise typer.Exit(code=1)
    except Exception as exc:
        logger.error("handover failed: %s", exc)
        if fail_soft:
            raise typer.Exit(code=0) from exc
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if not hook_mode:
        if result.skipped:
            typer.echo(f"Skipped: {result.reason}")
        else:
            export_note = f", export={result.export_path.name}" if result.export_path else ""
            typer.echo(
                f"Handover session {result.session_id}: "
                f"{result.chunk_count} chunks, {result.neuron_count} neurons "
                f"({result.distill_mode}){export_note}"
            )

    if not result.checkpoint_ok:
        if fail_soft:
            raise typer.Exit(code=0)
        typer.echo("WAL checkpoint failed — compaction may race brain.db writes", err=True)
        raise typer.Exit(code=1)

    raise typer.Exit(code=0)


graph_app = typer.Typer(help="Code graph operations (Graphify import)")
app.add_typer(graph_app, name="graph")


@graph_app.command("import")
def graph_import_cmd(
    graph_json: Path | None = typer.Argument(
        None,
        help="Path to graph.json (defaults to .brain/config graphify.graph_json)",
    ),
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    include_docs: bool = typer.Option(
        False,
        "--include-docs",
        help="Import non-code Graphify nodes (documents, papers, etc.)",
    ),
) -> None:
    """Import Graphify graph.json into brain.db (code-only by default, offline)."""
    from brainkm.services.config_loader import load_brain_config
    from brainkm.services.graph_import import import_graph_json, import_project_graph

    cfg = load_brain_config(project_dir)
    code_only = cfg.graphify.code_only if not include_docs else False

    try:
        if graph_json is not None:
            result = import_graph_json(
                graph_json,
                project_dir=project_dir,
                config=cfg,
                code_only=code_only,
            )
        else:
            result = import_project_graph(project_dir=project_dir, config=cfg)
    except FileNotFoundError as exc:
        logger.error("graph import failed: %s", exc)
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if result.status == "skipped":
        typer.echo("Skipped: graphify disabled in config")
        raise typer.Exit(code=0)

    typer.echo(
        f"Imported graph: {result.node_count} code nodes, {result.edge_count} edges "
        f"(run={result.run_id}, status={result.status})"
    )


@graph_app.command("sync")
def graph_sync_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    skip_extract: bool = typer.Option(
        False,
        "--skip-extract",
        help="Import existing graph.json only",
    ),
    force_extract: bool = typer.Option(
        False,
        "--force-extract",
        help="Pass --force to graphify extract",
    ),
) -> None:
    """Extract (optional) and import graph.json with code_only:true."""
    from brainkm.services.config_loader import load_brain_config
    from brainkm.services.graphify_sync import sync_graph

    cfg = load_brain_config(project_dir)
    result = sync_graph(
        project_dir=project_dir,
        config=cfg,
        extract=not skip_extract,
        force=force_extract,
    )
    if result.status in {"skipped", "skipped_locked", "skipped_empty"}:
        typer.echo(f"Skipped: {result.message or result.status}")
        raise typer.Exit(code=0)
    if result.status in {"extract_failed", "missing_graph"}:
        typer.echo(result.message or result.status, err=True)
        raise typer.Exit(code=1)
    import_result = result.import_result
    if import_result:
        typer.echo(
            f"Synced graph: {import_result.node_count} code nodes, "
            f"{import_result.edge_count} edges (status={import_result.status})"
        )
    typer.echo(f"graph_available={result.graph_available}")


@graph_app.command("extract")
def graph_extract_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Pass --force to graphify extract",
    ),
) -> None:
    """Run graphify extract only (no brain.db import)."""
    from brainkm.services.config_loader import load_brain_config
    from brainkm.services.graphify_sync import run_graphify_extract

    root = project_dir if project_dir is not None else Path.cwd()
    cfg = load_brain_config(project_dir)
    result = run_graphify_extract(root.resolve(), cfg, force=force)
    if not result.ok:
        typer.echo(result.stderr_snippet or "graphify extract failed", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Extracted graph: {result.graph_path}")


@graph_app.command("status")
def graph_status_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
) -> None:
    """Show Graphify binary, graph.json, and import status."""
    from brainkm.services.config_loader import load_brain_config
    from brainkm.services.graphify_sync import build_graph_status

    cfg = load_brain_config(project_dir)
    status = build_graph_status(project_dir, cfg)
    typer.echo(f"graphify_found: {status['graphify_found']}")
    if status["graphify_binary"]:
        typer.echo(f"graphify_binary: {status['graphify_binary']}")
    elif status["graphify_reason"]:
        typer.echo(f"graphify_reason: {status['graphify_reason']}", err=True)
    typer.echo(f"graph_json: {status['graph_json']}")
    typer.echo(f"graph_json_exists: {status['graph_json_exists']}")
    if status["graph_json_mtime"]:
        typer.echo(f"graph_json_mtime: {status['graph_json_mtime']}")
    typer.echo(f"graph_stale: {status['graph_stale']}")
    typer.echo(f"graph_available: {status['graph_available']}")
    typer.echo(f"code_node_count: {status['code_node_count']}")
    typer.echo(f"last_import_status: {status['last_import_status']}")
    if status["last_import_at"]:
        typer.echo(f"last_import_at: {status['last_import_at']}")
    typer.echo(f"auto_sync_enabled: {status['auto_sync_enabled']}")
    typer.echo(f"watch_filesystem_enabled: {status['watch_filesystem_enabled']}")
    typer.echo(f"sync_request_pending: {status['sync_request_pending']}")


@app.command("install")
def install_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    dev: bool = typer.Option(
        False,
        "--dev",
        help="Use local brainkm binary (editable install) instead of uvx",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing .brain/config.json and brainkm.mdc rule",
    ),
    no_graph: bool = typer.Option(
        False,
        "--no-graph",
        help="Skip initial graphify extract/sync during install",
    ),
    client: str = typer.Option(
        "cursor",
        "--client",
        help="Target agent client: cursor | claude | antigravity | codex | generic",
    ),
    http: bool = typer.Option(
        False,
        "--http",
        help="Configure shared HTTP MCP transport (enables auto_observe)",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="HTTP bind host when --http"),
    port: int = typer.Option(8765, "--port", help="HTTP port when --http"),
) -> None:
    """Install MCP config, hooks, rule, and .brain scaffolding."""
    from brainkm.services.install import run_install

    result = run_install(
        project_dir=project_dir,
        dev=dev,
        force=force,
        no_graph=no_graph,
        client=client,
        http=http,
        host=host,
        port=port,
    )

    typer.echo(f"Installed brainkm into {result.project_dir} (client={client})")
    for path in result.files_written:
        typer.echo(f"  wrote {path.relative_to(result.project_dir)}")
    for path in result.files_skipped:
        typer.echo(f"  skip {path.relative_to(result.project_dir)}")
    for warning in result.warnings:
        typer.echo(f"  warning: {warning}", err=True)


def _run_stdin_hook(
    handler_name: str,
    handler,
    *,
    event: str | None = None,
    client: str = "cursor",
) -> None:
    import sys

    from brainkm.services.hooks import (
        build_antigravity_hook_stdout,
        build_claude_hook_stdout,
        build_cursor_hook_stdout,
        normalize_antigravity_stdin,
    )

    kind = (client or "cursor").strip().lower()
    # All hook hosts are fail-soft so a broken hook never blocks the agent.
    fail_soft = kind in ("cursor", "claude", "antigravity")

    try:
        payload = sys.stdin.read()
        if kind == "antigravity" and payload.strip():
            try:
                data = json.loads(payload)
                if isinstance(data, dict):
                    payload = json.dumps(normalize_antigravity_stdin(data, event=event))
            except json.JSONDecodeError:
                pass
        result = handler(payload)
    except Exception as exc:
        logger.error("%s failed: %s", handler_name, exc)
        if fail_soft:
            if kind == "antigravity" and event:
                from brainkm.services.hooks import HookRunResult

                typer.echo(
                    json.dumps(
                        build_antigravity_hook_stdout(
                            HookRunResult(
                                hook=handler_name,
                                session_id=None,
                                skipped=True,
                                reason=str(exc),
                            ),
                            event,
                        )
                    )
                )
            raise typer.Exit(code=0) from exc
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if event is not None:
        if result.skipped:
            logger.info("%s skipped: %s", handler_name, result.reason)
        else:
            logger.info("%s ok session_id=%s", handler_name, result.session_id)
        if kind == "claude":
            payload_out = build_claude_hook_stdout(result, event)
            if payload_out is not None:
                typer.echo(json.dumps(payload_out))
            return
        if kind == "antigravity":
            typer.echo(json.dumps(build_antigravity_hook_stdout(result, event)))
            return
        # Cursor: emit JSON for inject events; capture-only events print nothing.
        try:
            typer.echo(json.dumps(build_cursor_hook_stdout(result, event)))
        except ValueError:
            if result.skipped:
                logger.info("%s (no stdout) skipped: %s", handler_name, result.reason)
            else:
                logger.info("%s (no stdout) ok session_id=%s", handler_name, result.session_id)
        return

    # Capture-only hooks (no event): keep stdout empty for every host (JSON-clean).
    if result.skipped:
        logger.info("%s skipped: %s", handler_name, result.reason)
    else:
        logger.info("%s ok session_id=%s", handler_name, result.session_id)


@app.command("session-start")
def session_start_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
) -> None:
    """SessionStart hook — migrate brain.db and prepare session."""
    from brainkm.services.hooks import run_session_start

    if not stdin:
        typer.echo("--stdin is required for session-start hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "SessionStart",
        lambda raw: run_session_start(raw, project_dir=project_dir),
        event="sessionStart",
        client=client,
    )


@app.command("session-end")
def session_end_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
) -> None:
    """SessionEnd hook — capture transcript into neurons."""
    from brainkm.services.hooks import run_session_end

    if not stdin:
        typer.echo("--stdin is required for session-end hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "SessionEnd",
        lambda raw: run_session_end(raw, project_dir=project_dir),
        client=client,
    )


@app.command("pre-tool")
def pre_tool_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
    event: str = typer.Option(
        "preToolUse",
        "--event",
        help="Host event name (Antigravity: PreToolUse)",
    ),
) -> None:
    """PreToolUse hook — inject bounded context_pack for matched write/edit/shell tools."""
    from brainkm.services.hooks import run_pre_tool_use

    if not stdin:
        typer.echo("--stdin is required for pre-tool hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "PreToolUse",
        lambda raw: run_pre_tool_use(raw, project_dir=project_dir),
        event=event,
        client=client,
    )


bench_app = typer.Typer(help="Benchmark and calibration utilities")
app.add_typer(bench_app, name="bench")


@bench_app.command("run")
def bench_run_cmd(
    suite: str = typer.Argument(
        ...,
        help=(
            "Suite: eval|retrieval|task|abstention|token|dmr|longmem|budget|"
            "compaction|latency|compare|scorecard|cma|longmemeval|staleness|scale|cost"
        ),
    ),
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    live: bool = typer.Option(
        False,
        "--live",
        help="Token suite only: measure against project brain.db (graph + neurons)",
    ),
    profile: str = typer.Option(
        "both",
        "--profile",
        help="Latency (and eval) profile: smoke|loaded|both",
    ),
    fixture_only: bool = typer.Option(
        False,
        "--fixture-only",
        help="Task/eval: seed ephemeral neurons instead of live brain.db",
    ),
    judge: bool = typer.Option(
        False,
        "--judge",
        help="Task/eval: optional Ollama LLM judge (soft metric; skips if unreachable)",
    ),
    write_scorecard: Path | None = typer.Option(
        None,
        "--write-scorecard",
        help="CMA only: write dated markdown scorecard to this path",
    ),
    stratify: int | None = typer.Option(
        None,
        "--stratify",
        help="LongMemEval-S: sample N per question_type (default 10; 0 = full set)",
    ),
    dataset: Path | None = typer.Option(
        None,
        "--dataset",
        help="LongMemEval-S: path to cleaned JSON (else LONGMEMEVAL_PATH / cache)",
    ),
    semantic: bool = typer.Option(
        False,
        "--semantic",
        help="LongMemEval-S: enable MiniLM hybrid retrieval (requires [semantic] extra)",
    ),
    adapters: bool = typer.Option(
        False,
        "--adapters",
        help="LongMemEval-S: also score naive/bm25/brainkm side-by-side arms",
    ),
    seed: int = typer.Option(
        42,
        "--seed",
        help="LongMemEval-S: RNG seed for stratified sampling",
    ),
    write_ndjson: Path | None = typer.Option(
        None,
        "--write-ndjson",
        help="LongMemEval-S with --adapters: write per-query arm scores as NDJSON",
    ),
) -> None:
    """Run a bench suite."""
    from brainkm.db.paths import brain_db_path
    from brainkm.services.bench_runner import format_suite_result, run_bench_suite

    if live and suite != "token":
        typer.echo("--live is only supported for the token suite", err=True)
        raise typer.Exit(code=2)

    db_path = brain_db_path(project_dir)
    if suite == "longmemeval":
        from brainkm.services.longmemeval_bench import run_longmemeval_suite

        result = run_longmemeval_suite(
            db_path,
            dataset=dataset,
            stratify=stratify,
            semantic=semantic,
            seed=seed,
            adapters=adapters,
            write_ndjson=write_ndjson,
        )
    else:
        result = run_bench_suite(
            suite,
            db_path,
            live=live,
            profile=profile,
            fixture_only=fixture_only,
            judge=judge,
        )
    typer.echo(format_suite_result(result))
    if suite == "cma" and write_scorecard is not None:
        import platform

        from brainkm import __version__
        from brainkm.services.cma_bench import render_cma_scorecard_markdown

        commit = None
        try:
            import subprocess

            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                text=True,
                cwd=str(project_dir or Path.cwd()),
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            commit = None
        md = render_cma_scorecard_markdown(
            result,
            version=__version__,
            commit=commit,
            machine=platform.platform(),
            semantic=False,
            command="brainkm bench run cma",
        )
        write_scorecard.parent.mkdir(parents=True, exist_ok=True)
        write_scorecard.write_text(md, encoding="utf-8")
        typer.echo(f"Wrote scorecard: {write_scorecard}")
    if result.passed < result.total:
        raise typer.Exit(code=1)


@bench_app.command("probe")
def bench_probe_cmd(
    query: str = typer.Argument(..., help="Task query to compile via context_pack"),
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    baseline: list[str] | None = typer.Option(
        None,
        "--baseline",
        help="Repo-relative file paths for naive read comparison (repeatable)",
    ),
) -> None:
    """Probe live context_pack size for one query against project brain.db."""
    from brainkm.db.paths import brain_db_path
    from brainkm.services.token_bench import probe_context_pack

    db_path = brain_db_path(project_dir)
    result = probe_context_pack(db_path, query, baseline_files=baseline)
    status = "PASS" if result.passed else "FAIL"
    typer.echo(f"[{status}] {result.name}: {result.detail}")
    if not result.passed:
        raise typer.Exit(code=1)


@bench_app.command("calibrate")
def bench_calibrate_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    reference: bool = typer.Option(
        False,
        "--reference",
        help="Calibrate from packaged fixture only (does not seed project brain)",
    ),
    seed_reference_corpus: bool = typer.Option(
        False,
        "--seed-reference-corpus",
        help="Insert packaged reference neurons into project brain before calibrating",
    ),
) -> None:
    """Calibrate recall abstention thresholds from bench fixtures."""
    from brainkm.services.abstention_calibrate import calibrate_project, calibrate_reference

    if reference:
        calibration = calibrate_reference(project_dir=project_dir)
    else:
        calibration = calibrate_project(
            project_dir=project_dir,
            seed_reference_corpus=seed_reference_corpus,
        )

    typer.echo(
        f"Calibrated abstention fixture={calibration.fixture_id} "
        f"percentile={calibration.abstain_percentile:.2f} "
        f"threshold={calibration.corpus_bm25_threshold} "
        f"min_recall_score={calibration.min_recall_score} "
        f"pass_rate={calibration.query_pass_rate:.0%}"
    )


@app.command("post-compact")
def post_compact_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
) -> None:
    """PostCompact hook — refresh frozen injection snapshot after compaction."""
    from brainkm.services.hooks import run_post_compact

    if not stdin:
        typer.echo("--stdin is required for post-compact hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "PostCompact",
        lambda raw: run_post_compact(raw, project_dir=project_dir),
        event="postCompact",
        client=client,
    )


@app.command("post-tool")
def post_tool_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
    event: str = typer.Option(
        "postToolUse",
        "--event",
        help="Host event name (Antigravity: PostToolUse)",
    ),
) -> None:
    """PostToolUse hook — observations, graph sync, co-activation learning."""
    from brainkm.services.hooks import run_post_tool_use

    if not stdin:
        typer.echo("--stdin is required for post-tool hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "PostToolUse",
        lambda raw: run_post_tool_use(raw, project_dir=project_dir, failed=False),
        event=event,
        client=client,
    )


@app.command("post-tool-failure")
def post_tool_failure_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
) -> None:
    """PostToolUseFailure hook — record failure observation."""
    from brainkm.services.hooks import run_post_tool_use

    if not stdin:
        typer.echo("--stdin is required for post-tool-failure hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "PostToolUseFailure",
        lambda raw: run_post_tool_use(raw, project_dir=project_dir, failed=True),
        client=client,
    )


@app.command("user-prompt")
def user_prompt_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
) -> None:
    """UserPromptSubmit hook — capped prompt gist observation."""
    from brainkm.services.hooks import run_user_prompt_submit

    if not stdin:
        typer.echo("--stdin is required for user-prompt hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "UserPromptSubmit",
        lambda raw: run_user_prompt_submit(raw, project_dir=project_dir),
        client=client,
    )


@app.command("subagent-start")
def subagent_start_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
) -> None:
    """SubagentStart hook — inject frozen pack for Claude subagents."""
    from brainkm.services.hooks import run_subagent_start

    if not stdin:
        typer.echo("--stdin is required for subagent-start hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "SubagentStart",
        lambda raw: run_subagent_start(raw, project_dir=project_dir),
        event="subagentStart",
        client=client,
    )


@app.command("subagent-stop")
def subagent_stop_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
) -> None:
    """SubagentStop hook — promote observations for the subagent session (Claude)."""
    from brainkm.services.hooks import run_subagent_stop

    if not stdin:
        typer.echo("--stdin is required for subagent-stop hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "SubagentStop",
        lambda raw: run_subagent_stop(raw, project_dir=project_dir),
        client=client,
    )


@app.command("agent-stop")
def agent_stop_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
    event: str = typer.Option(
        "Stop",
        "--event",
        help="Host event name (Antigravity often omits it from stdin)",
    ),
) -> None:
    """Stop hook — flush use counts; Antigravity idle Stop distills with debounce."""
    from brainkm.services.hooks import run_agent_stop

    if not stdin:
        typer.echo("--stdin is required for agent-stop hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "Stop",
        lambda raw: run_agent_stop(raw, project_dir=project_dir, client=client),
        event=event if (client or "").strip().lower() == "antigravity" else None,
        client=client,
    )


@app.command("pre-invocation")
def pre_invocation_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    stdin: bool = typer.Option(True, "--stdin", help="Read hook payload JSON from stdin"),
    client: str = _hook_client_option(),
    event: str = typer.Option(
        "PreInvocation",
        "--event",
        help="Host event name (PreInvocation or SessionStart)",
    ),
) -> None:
    """Antigravity PreInvocation / SessionStart — inject throttled pack + synthetic precompact."""
    from brainkm.services.hooks import run_pre_invocation

    if not stdin:
        typer.echo("--stdin is required for pre-invocation hook", err=True)
        raise typer.Exit(code=1)

    _run_stdin_hook(
        "PreInvocation",
        lambda raw: run_pre_invocation(raw, project_dir=project_dir, event=event),
        event=event,
        client=client,
    )


review_app = typer.Typer(help="Review auto-captured neurons (V2)")
app.add_typer(review_app, name="review")

ollama_app = typer.Typer(help="Ollama hardware advisor and diagnostics")
app.add_typer(ollama_app, name="ollama")

groq_app = typer.Typer(help="Groq cloud distill diagnostics")
app.add_typer(groq_app, name="groq")

cursor_app = typer.Typer(help="Cursor agent CLI distill diagnostics")
app.add_typer(cursor_app, name="cursor")

semantic_app = typer.Typer(help="Local semantic retrieval (MiniLM / rerank) diagnostics")
app.add_typer(semantic_app, name="semantic")


@semantic_app.command("doctor")
def semantic_doctor_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
) -> None:
    """Report hardware recommendation and ONNX MiniLM / cross-encoder readiness."""
    from brainkm.services.semantic import semantic_ready
    from brainkm.services.semantic_advisor import (
        format_semantic_recommend,
        recommend_semantic_profile,
    )

    rec = recommend_semantic_profile()
    typer.echo(format_semantic_recommend(rec))
    ready = semantic_ready(project_dir)
    typer.echo("Status:")
    for key, value in ready.items():
        typer.echo(f"  {key}: {value}")


@ollama_app.command("doctor")
def ollama_doctor_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write recommended model into .brain/config.json",
    ),
) -> None:
    """Report hardware profile, recommended Ollama model, and daemon status."""
    from brainkm.services.config_loader import config_path
    from brainkm.services.ollama_advisor import (
        apply_recommended_model,
        build_doctor_report,
        format_doctor_report,
    )

    cfg_path = config_path(project_dir)
    if not cfg_path.is_file():
        typer.echo(f"Config not found: {cfg_path}", err=True)
        raise typer.Exit(code=1)

    report = build_doctor_report(project_dir=project_dir)
    typer.echo(format_doctor_report(report))

    if apply:
        updated = apply_recommended_model(
            project_dir=project_dir,
            recommendation=report.recommendation,
        )
        typer.echo(f"Updated {updated} ollama.model -> {report.recommendation.model}")


@groq_app.command("doctor")
def groq_doctor_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
) -> None:
    """Report Groq API key presence, reachability, and configured model."""
    from brainkm.services.config_loader import config_path
    from brainkm.services.groq_advisor import build_groq_report, format_groq_report

    cfg_path = config_path(project_dir)
    if not cfg_path.is_file():
        typer.echo(f"Config not found: {cfg_path}", err=True)
        raise typer.Exit(code=1)

    report = build_groq_report(project_dir=project_dir)
    typer.echo(format_groq_report(report))
    if not report.api_key_present or not report.status.reachable:
        raise typer.Exit(code=1)


@cursor_app.command("doctor")
def cursor_doctor_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
) -> None:
    """Report Cursor agent CLI presence and distill_mode readiness."""
    from brainkm.services.config_loader import config_path
    from brainkm.services.cursor_advisor import (
        build_cursor_doctor_report,
        format_cursor_report,
    )

    cfg_path = config_path(project_dir)
    if not cfg_path.is_file():
        typer.echo(f"Config not found: {cfg_path}", err=True)
        raise typer.Exit(code=1)

    report = build_cursor_doctor_report(project_dir=project_dir)
    typer.echo(format_cursor_report(report))


@cursor_app.command("install")
def cursor_install_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
) -> None:
    """Install the Cursor agent CLI (official curl | bash), then re-run doctor."""
    from brainkm.services.cursor_advisor import (
        build_cursor_doctor_report,
        format_cursor_report,
        install_cursor_agent_cli,
    )

    typer.echo("Installing Cursor agent CLI (curl https://cursor.com/install | bash)…")
    result = install_cursor_agent_cli()
    if result.stdout_tail and result.stdout_tail != "already installed":
        typer.echo(result.stdout_tail)
    if result.error:
        typer.echo(f"Install issue: {result.error}", err=True)
    if result.found:
        typer.echo(f"Agent found: {result.bin_path}")
    else:
        typer.echo(
            "Agent not found after install — heuristic distill still works. "
            "Add ~/.local/bin to PATH and retry.",
            err=True,
        )

    report = build_cursor_doctor_report(project_dir=project_dir)
    typer.echo(format_cursor_report(report))
    if not result.found:
        raise typer.Exit(code=1)


@review_app.command("list")
def review_list_cmd(project_dir: Path | None = typer.Option(None, "--project-dir")) -> None:
    from brainkm.services.review import list_pending

    items = list_pending(project_dir)
    if not items:
        typer.echo("No pending review items.")
        return
    for item in items:
        typer.echo(f"{item.node_id}\t{item.subtype}\t{item.title}")


@review_app.command("approve")
def review_approve_cmd(
    node_id: str = typer.Argument(...),
    project_dir: Path | None = typer.Option(None, "--project-dir"),
) -> None:
    from brainkm.db.connection import connect
    from brainkm.db.paths import brain_db_path
    from brainkm.services.review import approve_pending
    from brainkm.services.write_queue import run_blocking

    def _approve() -> bool:
        conn = connect(brain_db_path(project_dir))
        try:
            return approve_pending(node_id, conn=conn, project_dir=project_dir)
        finally:
            conn.close()

    if run_blocking(_approve):
        typer.echo(f"Approved {node_id}")
    else:
        typer.echo(f"No pending item for {node_id}", err=True)
        raise typer.Exit(code=1)


@review_app.command("reject")
def review_reject_cmd(
    node_id: str = typer.Argument(...),
    project_dir: Path | None = typer.Option(None, "--project-dir"),
) -> None:
    from brainkm.db.connection import connect
    from brainkm.db.paths import brain_db_path
    from brainkm.services.review import reject_pending
    from brainkm.services.write_queue import run_blocking

    def _reject() -> bool:
        conn = connect(brain_db_path(project_dir))
        try:
            return reject_pending(node_id, conn=conn, project_dir=project_dir)
        finally:
            conn.close()

    if run_blocking(_reject):
        typer.echo(f"Rejected {node_id}")
    else:
        typer.echo(f"No pending item for {node_id}", err=True)
        raise typer.Exit(code=1)


@app.command("hygiene")
def hygiene_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report noisy neurons without soft-archiving them",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Max neurons to scan (default: all)",
    ),
    decay: bool = typer.Option(
        False,
        "--decay",
        help="Also soft-archive unused neurons past the decay horizon",
    ),
    unused_days: int = typer.Option(
        90,
        "--unused-days",
        help="Unused horizon for --decay (days)",
    ),
) -> None:
    """Soft-archive memory neurons that fail the quality gate (noise/chrome/boilerplate)."""
    from brainkm.db.connection import connect
    from brainkm.db.migrate import migrate
    from brainkm.db.paths import brain_db_path
    from brainkm.services.hygiene import purge_noisy_neurons
    from brainkm.services.write_queue import run_blocking

    migrate(project_dir=project_dir, run_integrity_check=False)
    db = brain_db_path(project_dir)
    from brainkm.services.config_loader import load_brain_config

    cfg = load_brain_config(project_dir)

    def _purge():
        conn = connect(db)
        try:
            return purge_noisy_neurons(
                conn,
                dry_run=dry_run,
                limit=limit,
                decay=decay,
                unused_days=unused_days,
                config=cfg,
            )
        finally:
            conn.close()

    result = run_blocking(_purge)
    action = "would archive" if dry_run else "archived"
    typer.echo(
        f"scanned={result.scanned} kept={result.kept} {action}={result.archived}"
    )
    if dry_run and result.archived_ids:
        for node_id in result.archived_ids[:50]:
            typer.echo(node_id)
        if len(result.archived_ids) > 50:
            typer.echo(f"... and {len(result.archived_ids) - 50} more")


@app.command("consolidate")
def consolidate_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    limit: int = typer.Option(200, "--limit"),
    llm: bool = typer.Option(
        False,
        "--llm",
        help="Concept-cluster consolidate via configured distill provider",
    ),
) -> None:
    """Merge near-duplicate neurons (sleep-time consolidation)."""
    from brainkm.db.connection import connect
    from brainkm.db.migrate import migrate
    from brainkm.db.paths import brain_db_path
    from brainkm.services.config_loader import load_brain_config
    from brainkm.services.consolidate import (
        consolidate_concept_clusters_llm,
        consolidate_neurons,
    )
    from brainkm.services.write_queue import run_blocking

    migrate(project_dir=project_dir, run_integrity_check=False)
    cfg = load_brain_config(project_dir)

    def _consolidate():
        conn = connect(brain_db_path(project_dir))
        try:
            if llm:
                result = consolidate_concept_clusters_llm(
                    conn,
                    config=cfg,
                    project_dir=project_dir,
                    dry_run=dry_run,
                )
            else:
                result = consolidate_neurons(conn, dry_run=dry_run, limit=limit)
            if not dry_run:
                conn.commit()
            return result
        finally:
            conn.close()

    result = run_blocking(_consolidate)
    typer.echo(
        f"scanned={result.scanned} merged={result.merged} archived={result.archived}"
    )


@app.command("provenance")
def provenance_cmd(
    node_id: str = typer.Argument(..., help="Neuron / node id"),
    project_dir: Path | None = typer.Option(None, "--project-dir"),
) -> None:
    """Print provenance chain (distilled_from, chunks, spawned)."""
    from brainkm.db.connection import connect
    from brainkm.db.migrate import migrate
    from brainkm.db.paths import brain_db_path
    from brainkm.services.provenance import format_provenance_report

    migrate(project_dir=project_dir, run_integrity_check=False)
    conn = connect(brain_db_path(project_dir))
    try:
        typer.echo(format_provenance_report(conn, node_id))
    finally:
        conn.close()


@app.command("file-history")
def file_history_cmd(
    path: str = typer.Argument(..., help="Source file path"),
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """List memories/episodes linked to a code file via about_file / about_symbol."""
    from brainkm.db.connection import connect
    from brainkm.db.migrate import migrate
    from brainkm.db.paths import brain_db_path
    from brainkm.services.file_history import file_history

    migrate(project_dir=project_dir, run_integrity_check=False)
    conn = connect(brain_db_path(project_dir))
    try:
        code_id, items = file_history(conn, path, limit=limit)
        if code_id is None:
            typer.echo(f"No code node for path={path}")
            raise typer.Exit(code=1)
        typer.echo(f"code_node={code_id} links={len(items)}")
        for item in items:
            typer.echo(
                f"  [{item.kind}/{item.subtype or '-'}] {item.title} "
                f"via={item.relationship} use={item.use_count} id={item.node_id}"
            )
    finally:
        conn.close()


@app.command("demo")
def demo_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    port: int = typer.Option(5757, "--port"),
    no_open: bool = typer.Option(False, "--no-open"),
) -> None:
    """Alias for ``brainkm viz --demo`` — seed synthetic neurons and open Neural Cosmos."""
    from brainkm.services.viz import run_viz_server

    run_viz_server(
        project_dir=project_dir,
        port=port,
        open_browser=not no_open,
        demo=True,
    )


@app.command("import")
def import_cmd(
    source: Path = typer.Argument(..., help="JSON neuron export to merge"),
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    replace: bool = typer.Option(
        False,
        "--replace",
        help="Soft-archive existing memory neurons then import (destructive)",
    ),
) -> None:
    """Import neurons from JSON export (merge or replace)."""
    if replace:
        from brainkm.services.import_merge import import_json_replace

        result = import_json_replace(source, project_dir=project_dir)
    else:
        from brainkm.services.import_merge import import_json_merge

        result = import_json_merge(source, project_dir=project_dir)
    typer.echo(
        f"Imported {result.imported}, skipped {result.skipped}, conflicts {result.conflicts}"
    )


@app.command("export")
def export_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    full: bool = typer.Option(False, "--full", help="Include archived neurons"),
    output: Path | None = typer.Option(None, "--output", help="Output markdown path"),
) -> None:
    """Export active neurons to markdown under .brain/exports/."""
    from brainkm.services.export import export_markdown

    result = export_markdown(project_dir=project_dir, full=full, output=output)
    typer.echo(f"Exported {result.neuron_count} neurons to {result.path}")


@app.command("repair")
def repair_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
) -> None:
    """Rebuild FTS5 index, re-scan for leaked secrets, and run integrity check."""
    from brainkm.services.repair import repair_brain

    result = repair_brain(project_dir=project_dir)
    typer.echo(
        f"Rebuilt FTS5 ({result.fts_rows_rebuilt} rows), "
        f"secrets_archived={result.secrets_archived}, "
        f"integrity_ok={result.integrity_ok}"
    )
    if not result.integrity_ok:
        raise typer.Exit(code=1)


@app.command("viz")
def viz_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root containing .brain/brain.db (defaults to cwd)",
    ),
    port: int = typer.Option(5757, "--port", help="HTTP port to serve visualization on"),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open browser"),
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Seed synthetic demo neurons (no brain.db required)",
    ),
) -> None:
    """Launch 3D neuron graph visualization in the browser."""
    from brainkm.services.viz import run_viz_server

    run_viz_server(
        project_dir=project_dir,
        port=port,
        open_browser=not no_open,
        demo=demo,
    )


@app.command("team-export")
def team_export_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
) -> None:
    """Export pinned / high-confidence neurons to ``.brain/team/neurons.json``."""
    from brainkm.services.team import export_team_neurons

    path = export_team_neurons(project_dir or Path.cwd())
    typer.echo(f"Wrote {path}")


@app.command("team-import")
def team_import_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
) -> None:
    """Import ``.brain/team/neurons.json`` via confidence-based merge."""
    from brainkm.services.team import import_team_neurons

    count = import_team_neurons(project_dir or Path.cwd())
    typer.echo(f"Imported {count} team neuron(s)")


@app.command("serve")
def serve_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    allow_remote: bool = typer.Option(
        False,
        "--allow-remote",
        help="Permit binding outside loopback (dangerous; also mcp.allow_remote)",
    ),
) -> None:
    """Run shared HTTP MCP server (alias of ``mcp --http``)."""
    from brainkm.server import main as run_mcp_server

    run_mcp_server(
        project_dir=project_dir,
        http=True,
        host=host,
        port=port,
        allow_remote=allow_remote,
    )


@app.command("connect")
def connect_cmd(
    client: str = typer.Argument(
        ...,
        help="cursor | claude | antigravity | codex | generic",
    ),
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    http: bool = typer.Option(True, "--http/--stdio", help="Shared HTTP (default) or stdio"),
    hooks: bool = typer.Option(True, "--hooks/--no-hooks"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    dev: bool = typer.Option(False, "--dev"),
    mirror_global: bool = typer.Option(
        False,
        "--mirror-global",
        help="Antigravity: also merge MCP into ~/.gemini/config/mcp_config.json",
    ),
) -> None:
    """Wire one agent client to this project's brain (stdio or shared HTTP)."""
    from brainkm.services.connect import run_connect

    transport = "http" if http else "stdio"
    try:
        result = run_connect(
            client,
            project_dir,
            transport=transport,
            hooks=hooks,
            host=host,
            port=port,
            dev=dev,
            mirror_global=mirror_global,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Connected {result.client} via {result.transport}"
        + (f" ({result.mcp_url})" if result.mcp_url else "")
    )
    for path in result.files_written:
        typer.echo(f"  wrote {path}")
    for warning in result.warnings:
        typer.echo(f"  warning: {warning}", err=True)
    if transport == "http":
        typer.echo("Ensure the shared server is running: brainkm serve --project-dir .")


@app.command("doctor")
def doctor_cmd(
    project_dir: Path | None = typer.Option(None, "--project-dir"),
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port"),
) -> None:
    """Check shared MCP health, client wiring, and auto_observe."""
    from brainkm.services.mcp_doctor import build_mcp_doctor_report, format_mcp_doctor_report

    report = build_mcp_doctor_report(project_dir, host=host, port=port)
    typer.echo(format_mcp_doctor_report(report))
    if report.config_transport == "http" and not report.health_ok:
        raise typer.Exit(code=1)
    if report.dual_writer_warning:
        raise typer.Exit(code=1)
    if report.missing_auth_warning:
        raise typer.Exit(code=1)


@app.command("mcp")
def mcp_cmd(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        help="Target project root (defaults to cwd)",
    ),
    http: bool = typer.Option(
        False,
        "--http",
        help="Serve streamable HTTP instead of stdio (local multi-editor)",
    ),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    allow_remote: bool = typer.Option(
        False,
        "--allow-remote",
        help="Permit binding outside loopback when using --http",
    ),
) -> None:
    """Run brainkm MCP server (stdio by default, or --http)."""
    from brainkm.server import main as run_mcp_server

    run_mcp_server(
        project_dir=project_dir,
        http=http,
        host=host,
        port=port,
        allow_remote=allow_remote,
    )


if __name__ == "__main__":
    app()
