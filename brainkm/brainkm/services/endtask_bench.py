"""End-task A/B helpers: fixture load, brain seeder, grading, scorecard render.

The Cursor SDK harness lives in ``brainkm/scripts/endtask_harness.py`` (costs
real API tokens). This module stays importable for unit tests and dry-runs.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from brainkm.db.connection import connect
from brainkm.db.migrate import migrate
from brainkm.services.bench_db import ensure_fixture_neuron
from brainkm.services.memory import new_ulid

ArmName = Literal["with_brainkm", "without"]


@dataclass
class EndTaskGradeResult:
    passed: bool
    detail: str
    method: str


@dataclass
class EndTaskRunRecord:
    task_id: str
    task_class: str
    arm: ArmName
    repeat: int
    passed: bool
    grade_detail: str
    grade_method: str
    context_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    tokens_proxy: int | None
    wall_ms: float
    tool_calls: int
    status: str
    error: str | None = None
    final_text_preview: str = ""
    dry_run: bool = False


@dataclass
class EndTaskPlan:
    tasks: list[dict[str, Any]]
    arms: list[ArmName]
    repeats: int
    model: str
    estimated_runs: int
    estimated_usd: float


@dataclass
class EndTaskReport:
    records: list[EndTaskRunRecord] = field(default_factory=list)
    model: str = "composer-2.5"
    dry_run: bool = False
    fixture_id: str = "endtask_v1"
    notes: list[str] = field(default_factory=list)


def load_endtask_fixture(path: Path | None = None) -> dict[str, Any]:
    """Load endtask fixture JSON from path or package data."""
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    fixtures = resources.files("brainkm.bench.fixtures")
    candidate = fixtures.joinpath("endtask_v1.json")
    return json.loads(candidate.read_text(encoding="utf-8"))


def select_tasks(
    fixture: dict[str, Any],
    *,
    task_ids: list[str] | None = None,
    smoke_only: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    tasks = list(fixture.get("tasks") or [])
    if smoke_only:
        tasks = [t for t in tasks if t.get("smoke")]
    if task_ids:
        wanted = set(task_ids)
        tasks = [t for t in tasks if t.get("id") in wanted]
    if limit is not None:
        tasks = tasks[: max(0, limit)]
    return tasks


def plan_runs(
    fixture: dict[str, Any],
    *,
    tasks: list[dict[str, Any]],
    repeats: int = 1,
    model: str = "composer-2.5",
    arms: list[ArmName] | None = None,
) -> EndTaskPlan:
    arm_list: list[ArmName] = arms or ["with_brainkm", "without"]
    n = len(tasks) * len(arm_list) * max(1, repeats)
    per = float((fixture.get("cost_estimate") or {}).get("usd_per_run_rough") or 0.05)
    return EndTaskPlan(
        tasks=tasks,
        arms=arm_list,
        repeats=max(1, repeats),
        model=model,
        estimated_runs=n,
        estimated_usd=round(n * per, 2),
    )


def seed_endtask_brain(
    project_dir: Path,
    fixture: dict[str, Any],
    *,
    run_graph_sync: bool = True,
) -> dict[str, Any]:
    """Create ``.brain/brain.db`` and seed deterministic prior-session neurons.

    Optionally runs ``brainkm graph sync --skip-extract`` so traverse can use an
    existing graph.json when present; memory neurons alone power knowledge tasks.
    """
    project_dir = project_dir.resolve()
    brain_dir = project_dir / ".brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    db_path = brain_dir / "brain.db"
    migrate(db_path=db_path, run_integrity_check=False)
    conn = connect(db_path)
    seeded = 0
    try:
        for node in fixture.get("seed_neurons") or []:
            ensure_fixture_neuron(
                conn,
                node_id=str(node["id"]),
                title=str(node["title"]),
                content=node.get("content"),
                kind=str(node.get("kind") or "memory"),
                subtype=node.get("subtype"),
            )
            path = node.get("path")
            if path:
                conn.execute(
                    "UPDATE nodes SET path = ? WHERE id = ?",
                    (path, node["id"]),
                )
            seeded += 1
        now = "2026-07-19T00:00:00"
        edges = 0
        for edge in fixture.get("seed_edges") or []:
            conn.execute(
                """
                INSERT OR IGNORE INTO edges
                  (id, from_id, to_id, relationship, weight, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1.0, ?, ?)
                """,
                (
                    new_ulid(),
                    edge["from_id"],
                    edge["to_id"],
                    edge.get("relationship", "related"),
                    now,
                    now,
                ),
            )
            edges += 1
        conn.commit()
    finally:
        conn.close()

    graph_status = "skipped"
    if run_graph_sync:
        graph_status = _try_graph_sync(project_dir)
    return {"neurons": seeded, "edges": len(fixture.get("seed_edges") or []), "graph": graph_status}


def _try_graph_sync(project_dir: Path) -> str:
    try:
        proc = subprocess.run(
            [
                "brainkm",
                "graph",
                "sync",
                "--skip-extract",
                "--project-dir",
                str(project_dir),
            ],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode == 0:
            return "ok"
        return f"exit={proc.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"error:{exc}"


def install_brainkm_rule(project_dir: Path) -> Path:
    """Copy packaged brainkm.mdc into the worktree ``.cursor/rules/``."""
    rules = project_dir / ".cursor" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    dest = rules / "brainkm.mdc"
    src = (
        Path(__file__).resolve().parent.parent / "hooks" / "cursor" / "brainkm.mdc"
    )
    if src.is_file():
        shutil.copy2(src, dest)
    else:
        dest.write_text(
            "# brainkm\nPrefer MCP recall / context_pack / traverse for project memory.\n",
            encoding="utf-8",
        )
    return dest


def grade_regex(final_text: str, patterns: list[str]) -> EndTaskGradeResult:
    """Pass if every regex pattern matches the assistant text (case-aware per pattern)."""
    missing: list[str] = []
    for pat in patterns:
        try:
            if re.search(pat, final_text or "") is None:
                missing.append(pat)
        except re.error:
            missing.append(f"invalid:{pat}")
    if missing:
        return EndTaskGradeResult(
            passed=False,
            detail=f"missing={missing}",
            method="regex",
        )
    return EndTaskGradeResult(passed=True, detail="all_patterns", method="regex")


def grade_checker(worktree: Path, command: str, *, timeout: float = 60.0) -> EndTaskGradeResult:
    """Run a shell checker in the worktree; exit 0 = pass."""
    proc = subprocess.run(
        command,
        shell=True,
        cwd=str(worktree),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    detail = (proc.stdout or proc.stderr or "").strip().replace("\n", " | ")[:400]
    return EndTaskGradeResult(
        passed=proc.returncode == 0,
        detail=detail or f"exit={proc.returncode}",
        method="checker",
    )


def grade_task(
    task: dict[str, Any],
    *,
    final_text: str,
    worktree: Path,
    use_ollama_tiebreak: bool = False,
) -> EndTaskGradeResult:
    """Grade a finished run. Ollama judge is optional tiebreak for knowledge only."""
    grade = task.get("grade") or {}
    gtype = str(grade.get("type") or "regex")
    if gtype == "checker":
        return grade_checker(worktree, str(grade.get("command") or "false"))

    patterns = list(grade.get("patterns") or [])
    result = grade_regex(final_text, patterns)
    if result.passed or not use_ollama_tiebreak:
        return result

    # Soft tiebreak: never sole grader; only flip fail→pass when judge says with wins.
    # Here we only have one answer — skip unless reference exists and Ollama is up.
    reference = str(task.get("reference") or "")
    if not reference:
        return result
    try:
        from brainkm.models.brain_config import BrainConfig
        from brainkm.services.task_bench import judge_task_answers

        judged = judge_task_answers(
            query=str(task.get("prompt") or ""),
            reference=reference,
            with_context=final_text,
            without_context="",
            config=BrainConfig(),
        )
    except Exception:  # noqa: BLE001
        return result
    if judged is None:
        return result
    if judged.get("winner") == "with" and float(judged.get("with_score") or 0) >= 0.7:
        return EndTaskGradeResult(
            passed=True,
            detail=f"regex_miss_ollama_tiebreak={judged}",
            method="regex+ollama",
        )
    return result


def estimate_tokens_proxy(text: str) -> int:
    """Char/4 proxy when SDK usage is unavailable."""
    return max(0, len(text or "") // 4)


def write_ndjson(path: Path, records: list[EndTaskRunRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")


def _arm_stats(records: list[EndTaskRunRecord], arm: ArmName) -> dict[str, Any]:
    subset = [r for r in records if r.arm == arm and not r.dry_run]
    if not subset:
        dry = [r for r in records if r.arm == arm]
        return {
            "n": len(dry),
            "passed": 0,
            "rate": None,
            "mean_context_tokens": None,
            "dry_run_only": True,
        }
    tokens = [
        r.context_tokens
        if r.context_tokens is not None
        else r.tokens_proxy
        for r in subset
    ]
    tokens_f = [float(t) for t in tokens if t is not None]
    passed = sum(1 for r in subset if r.passed)
    return {
        "n": len(subset),
        "passed": passed,
        "rate": passed / len(subset),
        "mean_context_tokens": (
            sum(tokens_f) / len(tokens_f) if tokens_f else None
        ),
        "dry_run_only": False,
    }


def render_endtask_markdown(report: EndTaskReport) -> str:
    """Render dated publishable end-task scorecard."""
    with_s = _arm_stats(report.records, "with_brainkm")
    without_s = _arm_stats(report.records, "without")
    by_class: dict[str, dict[str, list[EndTaskRunRecord]]] = {}
    for rec in report.records:
        by_class.setdefault(rec.task_class, {}).setdefault(rec.arm, []).append(rec)

    def _fmt_rate(stats: dict[str, Any]) -> str:
        if stats.get("dry_run_only"):
            return f"dry-run planned n={stats['n']}"
        rate = stats["rate"]
        return f"{stats['passed']}/{stats['n']} ({rate:.0%})"

    def _fmt_tok(stats: dict[str, Any]) -> str:
        t = stats.get("mean_context_tokens")
        return "—" if t is None else f"{t:.0f}"

    token_note = ""
    if (
        with_s.get("mean_context_tokens") is not None
        and without_s.get("mean_context_tokens") is not None
        and without_s["mean_context_tokens"] > 0
    ):
        w = float(with_s["mean_context_tokens"])
        wo = float(without_s["mean_context_tokens"])
        if w <= wo:
            pct = (1.0 - w / wo) * 100.0
            token_note = f" ({pct:.0f}% fewer prompt tokens vs without)"
        else:
            ratio = w / wo
            token_note = (
                f" ({ratio:.1f}× prompt tokens vs without — pack injection)"
            )

    lines = [
        "# End-task A/B scorecard (agent with brainkm vs without)",
        "",
        f"- **fixture:** {report.fixture_id}",
        f"- **model:** {report.model}",
        f"- **dry_run:** {report.dry_run}",
        f"- **runs recorded:** {len(report.records)}",
        "",
        "## Headline",
        "",
        f"| Arm | Success | Mean prompt tokens |",
        f"|-----|---------|---------------------|",
        f"| **with brainkm** | {_fmt_rate(with_s)} | {_fmt_tok(with_s)}{token_note} |",
        f"| without | {_fmt_rate(without_s)} | {_fmt_tok(without_s)} |",
        "",
    ]

    if with_s.get("rate") is not None and without_s.get("rate") is not None:
        claim = (
            f"> Agent with brainkm solved **{with_s['passed']}/{with_s['n']}** "
            f"vs **{without_s['passed']}/{without_s['n']}** without"
        )
        if token_note:
            claim += f" ({token_note.strip(' ()')})."
        else:
            claim += "."
        lines.extend([claim, ""])

    lines.extend(["## By class", ""])
    for cls in sorted(by_class):
        lines.append(f"### {cls}")
        lines.append("")
        for arm in ("with_brainkm", "without"):
            subset = by_class[cls].get(arm, [])
            live = [r for r in subset if not r.dry_run]
            if not live:
                lines.append(f"- `{arm}`: dry-run n={len(subset)}")
                continue
            p = sum(1 for r in live if r.passed)
            lines.append(f"- `{arm}`: {p}/{len(live)}")
        lines.append("")

    lines.extend(
        [
            "## Per-run table",
            "",
            "| Task | Class | Arm | Rep | Pass | Tokens | Wall ms | Status | Detail |",
            "|------|-------|-----|-----|------|--------|---------|--------|--------|",
        ]
    )
    for r in report.records:
        tok = (
            r.context_tokens
            if r.context_tokens is not None
            else r.tokens_proxy
        )
        tok_s = "—" if tok is None else str(tok)
        detail = (r.grade_detail or r.error or "").replace("|", "\\|")[:120]
        lines.append(
            f"| `{r.task_id}` | {r.task_class} | {r.arm} | {r.repeat} | "
            f"{'Y' if r.passed else 'N'} | {tok_s} | {r.wall_ms:.0f} | "
            f"{r.status} | {detail} |"
        )

    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- Nondeterministic LLM runs; publish with **repeats ≥ 3**.",
            "- Costs real Cursor API tokens (`CURSOR_API_KEY` required for live runs).",
            "- Knowledge tasks graded by regex; change tasks by shell checkers.",
            "- Ollama judge is optional tiebreak only — never sole grader.",
            "- Dry-run plans costs without calling the API.",
            "",
        ]
    )
    for note in report.notes:
        lines.append(f"- {note}")
    if report.notes:
        lines.append("")
    return "\n".join(lines)


def create_worktree(repo_root: Path, work_root: Path, label: str) -> Path:
    """Create a detached git worktree under ``work_root``."""
    work_root.mkdir(parents=True, exist_ok=True)
    stamp = f"{label}-{int(time.time() * 1000)}"
    dest = work_root / stamp
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    proc = subprocess.run(
        ["git", "worktree", "add", "--detach", str(dest), "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "git worktree failed"
        raise RuntimeError(msg)
    return dest


def remove_worktree(repo_root: Path, worktree: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    shutil.rmtree(worktree, ignore_errors=True)


def brain_conn(project_dir: Path) -> sqlite3.Connection:
    """Open the seeded brain DB (read/write)."""
    return connect(project_dir / ".brain" / "brain.db")


def build_groq_user_prompt(question: str, *, pack_text: str | None) -> str:
    """Build the user message for the Groq knowledge A/B arm."""
    if pack_text:
        return (
            "You are answering a question about the MemNetwork/brainkm project.\n"
            "Use the PROJECT MEMORY PACK below as primary evidence. "
            "If the pack does not contain the answer, say you are unsure.\n\n"
            "=== PROJECT MEMORY PACK ===\n"
            f"{pack_text}\n"
            "=== END PACK ===\n\n"
            f"Question: {question}\n\n"
            "Answer briefly and concretely (2-6 sentences)."
        )
    return (
        "You are answering a question about the MemNetwork/brainkm project.\n"
        "You have NO project memory pack — answer only from general knowledge "
        "of similar tools if you must, but prefer admitting uncertainty over inventing "
        "project-specific numbers or policy.\n\n"
        f"Question: {question}\n\n"
        "Answer briefly and concretely (2-6 sentences)."
    )


def groq_chat(
    prompt: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 60.0,
) -> tuple[str, dict[str, int | None], str]:
    """Call Groq chat/completions. Returns (text, token_fields, status)."""
    import httpx

    from brainkm.config import get_settings
    from brainkm.models.brain_config import BrainConfig

    settings = get_settings()
    cfg = BrainConfig()
    key = (api_key if api_key is not None else settings.groq_api_key) or ""
    key = key.strip()
    if not key:
        return "", {
            "context_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
        }, "startup_error:GROQ_API_KEY not set"

    resolved_model = (model or cfg.groq.model).strip() or cfg.groq.model
    url_base = (base_url or cfg.groq.base_url).rstrip("/")
    url = f"{url_base}/chat/completions"
    payload = {
        "model": resolved_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You answer questions about a coding-agent memory project. "
                    "Be precise; prefer pack evidence over guesses."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 400,
    }
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        return "", {
            "context_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
        }, f"error:{exc}"

    if response.status_code == 401:
        return "", {
            "context_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
        }, "startup_error:unauthorized (check GROQ_API_KEY)"
    if response.status_code == 429:
        return "", {
            "context_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
        }, "error:rate_limited"
    if response.status_code >= 400:
        detail = (response.text or "")[:200]
        return "", {
            "context_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
        }, f"error:http_{response.status_code}:{detail}"

    body = response.json()
    choices = body.get("choices") or []
    text = ""
    if choices:
        text = choices[0].get("message", {}).get("content", "") or ""
    usage = body.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    tokens = {
        "input_tokens": int(prompt_tokens) if prompt_tokens is not None else None,
        "output_tokens": (
            int(completion_tokens) if completion_tokens is not None else None
        ),
        "context_tokens": int(prompt_tokens) if prompt_tokens is not None else None,
    }
    return text, tokens, "finished"


def run_groq_knowledge_arm(
    task: dict[str, Any],
    *,
    arm: ArmName,
    fixture: dict[str, Any],
    work_dir: Path,
    model: str | None = None,
) -> tuple[str, dict[str, int | None], str, int]:
    """Knowledge A/B via Groq: with-arm gets a seeded context_pack; without gets none.

    Returns (final_text, tokens, status, tool_calls). ``tool_calls`` is 0 for Groq.
    """
    from brainkm.models.brain_config import BrainConfig
    from brainkm.services.context_pack import compile_context_pack

    pack_text: str | None = None
    if arm == "with_brainkm":
        seed_endtask_brain(work_dir, fixture, run_graph_sync=False)
        conn = brain_conn(work_dir)
        try:
            pack = compile_context_pack(
                conn,
                str(task.get("prompt") or ""),
                config=BrainConfig(),
                project_dir=work_dir,
            )
            pack_text = pack.pack_text or ""
        finally:
            conn.close()

    user_prompt = build_groq_user_prompt(str(task.get("prompt") or ""), pack_text=pack_text)
    text, tokens, status = groq_chat(user_prompt, model=model)
    return text, tokens, status, 0
