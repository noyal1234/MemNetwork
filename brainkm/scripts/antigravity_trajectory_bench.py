#!/usr/bin/env python3
"""Antigravity-themed pack-vs-dump LLM proxy (NOT an IDE tool-loop bench).

What this measures
------------------
Arm A — naive multi-file **dump** of scenario ``target_files`` into an LLM prompt.
Arm B — ``compile_context_pack`` text injected into the same LLM prompt shape.

What this does **not** measure
------------------------------
- Live Google Antigravity IDE agent turns
- Native tools (``grep_search``, ``view_file``, …)
- Turn counts / tool hops (those require a real agent transcript)

That full-tool A/B is deferred until Cursor and Antigravity can be measured the
same way (see Cursor ``endtask_harness.py``). This script is the same *metric
class* as ``brainkm bench run compare`` + Groq endtask knowledge A/B, using
Antigravity-shaped questions.

Drivers
-------
- ``--mode tokens-only`` — local dump vs pack token counts (no LLM API).
- ``--mode llm`` — Groq or Gemini chat; records real usage when the call finishes.
  Failed dump arms (413 / rate limit) are reported as failures, not as
  "0% decision recovery from a 5-turn search".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / "brainkm"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from brainkm import __version__ as _BRAINKM_VERSION  # noqa: E402
from brainkm.db.connection import connect  # noqa: E402
from brainkm.db.paths import brain_db_path  # noqa: E402
from brainkm.services.config_loader import load_brain_config  # noqa: E402
from brainkm.services.context_pack import compile_context_pack  # noqa: E402
from brainkm.services.endtask_bench import gemini_chat, groq_chat  # noqa: E402
from brainkm.services.memory import token_count  # noqa: E402

ANTIGRAVITY_SCENARIOS = [
    {
        "id": "agy_arch_pivot",
        "title": "Antigravity Distill Architecture Pivot & Rules Fallback",
        "prompt": (
            "Explain why we chose agy -p CLI print mode for AntigravityDistillAdapter, "
            "where the rules fallback is defined, and how Groq fallback is configured."
        ),
        "target_files": [
            "brainkm/brainkm/adapters/antigravity_distill.py",
            "brainkm/brainkm/adapters/distill_rules.py",
            "docs/AI_PROJECT_BRIEF.md",
        ],
        "decision_keywords": ["agy", "rules", "groq"],
    },
    {
        "id": "agy_ast_refactor",
        "title": "Antigravity AST Call-Graph Refactor & Blast Radius",
        "prompt": (
            "We need to add a UserPromptSubmit hook for Antigravity. "
            "What files, functions, and adapters in brainkm will be impacted?"
        ),
        "target_files": [
            "brainkm/brainkm/services/hooks.py",
            "brainkm/brainkm/hooks/antigravity/hooks.json",
            "brainkm/brainkm/services/install.py",
            "brainkm/brainkm/adapters/transcript_v1.py",
        ],
        "decision_keywords": ["hooks", "antigravity", "preinvocation"],
    },
    {
        "id": "agy_git_join",
        "title": "Antigravity Session Trace & Git Commit Join",
        "prompt": (
            "What changed recently in brainkm/brainkm/services/antigravity_session.py, "
            "why were those changes made, and what decision neurons are linked to them?"
        ),
        "target_files": [
            "brainkm/brainkm/services/antigravity_session.py",
            "brainkm/brainkm/services/hooks.py",
        ],
        "decision_keywords": ["antigravity", "shadow", "session"],
    },
]


@dataclass
class PackVsDumpRecord:
    scenario_id: str
    scenario_title: str
    arm: str  # "dump" | "pack"
    dump_or_pack_tokens: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    wall_ms: float
    status: str
    decision_hit: bool | None  # None when arm did not finish (incomparable)
    response_preview: str
    mode: str  # "tokens-only" | "llm"


@dataclass
class PackVsDumpScorecard:
    records: list[PackVsDumpRecord] = field(default_factory=list)
    driver: str = "none"
    mode: str = "tokens-only"
    project_dir: Path = _REPO

    def pairs(self) -> list[tuple[PackVsDumpRecord, PackVsDumpRecord]]:
        by_id: dict[str, dict[str, PackVsDumpRecord]] = {}
        for r in self.records:
            by_id.setdefault(r.scenario_id, {})[r.arm] = r
        out: list[tuple[PackVsDumpRecord, PackVsDumpRecord]] = []
        for sid in (s["id"] for s in ANTIGRAVITY_SCENARIOS):
            arms = by_id.get(sid) or {}
            if "dump" in arms and "pack" in arms:
                out.append((arms["dump"], arms["pack"]))
        return out


def _load_dump_text(scenario: dict, repo: Path) -> tuple[str, int]:
    chunks: list[str] = []
    for rel_path in scenario["target_files"]:
        abs_path = repo / rel_path
        if abs_path.is_file():
            chunks.append(
                f"=== FILE: {rel_path} ===\n{abs_path.read_text(encoding='utf-8')}\n"
            )
    body = "\n".join(chunks)
    return body, token_count(body)


def _dump_prompt(scenario: dict, dump_body: str) -> str:
    return (
        "You are an expert developer inspecting the codebase.\n"
        "Use the SOURCE FILES below to answer the question.\n\n"
        f"{dump_body}\n\n"
        f"Question: {scenario['prompt']}"
    )


def _pack_prompt(scenario: dict, pack_text: str) -> str:
    return (
        "You are an expert developer inspecting the codebase.\n"
        "Use the CONTEXT PACK below to answer the question.\n\n"
        f"=== CONTEXT PACK ===\n{pack_text}\n=== END PACK ===\n\n"
        f"Question: {scenario['prompt']}"
    )


def _compile_pack(scenario: dict, repo: Path) -> tuple[str, int]:
    conn = connect(brain_db_path(repo))
    cfg = load_brain_config(repo)
    try:
        pack = compile_context_pack(
            conn, scenario["prompt"], config=cfg, project_dir=repo
        )
        text = pack.pack_text
    finally:
        conn.close()
    return text, token_count(text)


def _call_llm(
    prompt: str, *, driver: str
) -> tuple[str, dict[str, int | None], str]:
    use_gemini = driver == "gemini" or (
        driver == "auto"
        and (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    )
    if use_gemini:
        return gemini_chat(prompt, model="gemini-2.5-flash")
    return groq_chat(prompt, model="llama-3.3-70b-versatile")


def _resolved_driver(driver: str) -> str:
    if driver == "gemini":
        return "gemini"
    if driver == "groq":
        return "groq"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return "groq"


def _decision_hit(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


def run_scenario(
    scenario: dict,
    repo: Path,
    *,
    mode: str,
    driver: str,
) -> tuple[PackVsDumpRecord, PackVsDumpRecord]:
    dump_body, dump_tok = _load_dump_text(scenario, repo)
    pack_text, pack_tok = _compile_pack(scenario, repo)
    keywords = list(scenario["decision_keywords"])

    if mode == "tokens-only":
        dump_rec = PackVsDumpRecord(
            scenario_id=scenario["id"],
            scenario_title=scenario["title"],
            arm="dump",
            dump_or_pack_tokens=dump_tok,
            prompt_tokens=dump_tok,
            completion_tokens=None,
            total_tokens=dump_tok,
            wall_ms=0.0,
            status="tokens_only",
            decision_hit=None,
            response_preview="",
            mode=mode,
        )
        pack_rec = PackVsDumpRecord(
            scenario_id=scenario["id"],
            scenario_title=scenario["title"],
            arm="pack",
            dump_or_pack_tokens=pack_tok,
            prompt_tokens=pack_tok,
            completion_tokens=None,
            total_tokens=pack_tok,
            wall_ms=0.0,
            status="tokens_only",
            decision_hit=None,
            response_preview="",
            mode=mode,
        )
        return dump_rec, pack_rec

    # --- LLM mode ---
    dump_prompt = _dump_prompt(scenario, dump_body)
    pack_prompt = _pack_prompt(scenario, pack_text)

    t0 = time.perf_counter()
    dump_text, dump_usage, dump_status = _call_llm(dump_prompt, driver=driver)
    dump_wall = (time.perf_counter() - t0) * 1000.0
    dump_prompt_tok = dump_usage.get("input_tokens") or token_count(dump_prompt)
    dump_completion = dump_usage.get("output_tokens")
    dump_finished = dump_status == "finished"
    dump_rec = PackVsDumpRecord(
        scenario_id=scenario["id"],
        scenario_title=scenario["title"],
        arm="dump",
        dump_or_pack_tokens=dump_tok,
        prompt_tokens=int(dump_prompt_tok) if dump_prompt_tok is not None else dump_tok,
        completion_tokens=int(dump_completion) if dump_completion is not None else (
            token_count(dump_text) if dump_finished else 0
        ),
        total_tokens=None,
        wall_ms=dump_wall,
        status=dump_status,
        decision_hit=(
            _decision_hit(dump_text, keywords) if dump_finished else None
        ),
        response_preview=(dump_text or "")[:160].replace("\n", " "),
        mode=mode,
    )
    if dump_finished:
        dump_rec.total_tokens = (dump_rec.prompt_tokens or 0) + (
            dump_rec.completion_tokens or 0
        )
    else:
        # Economics still known from dump size; API did not complete.
        dump_rec.total_tokens = dump_tok

    time.sleep(1.0)

    t1 = time.perf_counter()
    pack_text_out, pack_usage, pack_status = _call_llm(pack_prompt, driver=driver)
    pack_wall = (time.perf_counter() - t1) * 1000.0
    pack_prompt_tok = pack_usage.get("input_tokens") or token_count(pack_prompt)
    pack_completion = pack_usage.get("output_tokens")
    pack_finished = pack_status == "finished"
    pack_rec = PackVsDumpRecord(
        scenario_id=scenario["id"],
        scenario_title=scenario["title"],
        arm="pack",
        dump_or_pack_tokens=pack_tok,
        prompt_tokens=int(pack_prompt_tok) if pack_prompt_tok is not None else pack_tok,
        completion_tokens=int(pack_completion) if pack_completion is not None else (
            token_count(pack_text_out) if pack_finished else 0
        ),
        total_tokens=None,
        wall_ms=pack_wall,
        status=pack_status,
        decision_hit=(
            _decision_hit(pack_text_out, keywords) if pack_finished else None
        ),
        response_preview=(pack_text_out or "")[:160].replace("\n", " "),
        mode=mode,
    )
    if pack_finished:
        pack_rec.total_tokens = (pack_rec.prompt_tokens or 0) + (
            pack_rec.completion_tokens or 0
        )
    else:
        pack_rec.total_tokens = pack_tok

    return dump_rec, pack_rec


def generate_markdown(scorecard: PackVsDumpScorecard) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    pairs = scorecard.pairs()

    dump_sizes = [d.dump_or_pack_tokens for d, _ in pairs]
    pack_sizes = [p.dump_or_pack_tokens for _, p in pairs]
    avg_dump = sum(dump_sizes) / max(1, len(dump_sizes))
    avg_pack = sum(pack_sizes) / max(1, len(pack_sizes))
    reduction = (1.0 - (avg_pack / avg_dump)) * 100.0 if avg_dump else 0.0
    factor = (avg_dump / avg_pack) if avg_pack else 0.0

    dump_ok = [d for d, _ in pairs if d.status == "finished"]
    pack_ok = [p for _, p in pairs if p.status == "finished"]
    dump_fail = [d for d, _ in pairs if d.status not in ("finished", "tokens_only")]

    # Decision hits only when both arms finished (fair), or pack-only finished rate
    both_finished = [
        (d, p)
        for d, p in pairs
        if d.status == "finished" and p.status == "finished"
    ]
    if both_finished:
        dec_dump = sum(1 for d, _ in both_finished if d.decision_hit)
        dec_pack = sum(1 for _, p in both_finished if p.decision_hit)
        dec_n = len(both_finished)
        dec_line = (
            f"- **Keyword hit rate (both arms finished only, n={dec_n}):** "
            f"pack **{dec_pack}/{dec_n}** vs dump **{dec_dump}/{dec_n}**."
        )
    elif pack_ok:
        dec_pack = sum(1 for p in pack_ok if p.decision_hit)
        dec_line = (
            f"- **Keyword hit rate (pack finished only):** "
            f"**{dec_pack}/{len(pack_ok)}** — dump arm not comparable "
            f"({len(dump_fail)} dump failure(s): "
            f"{', '.join(sorted({d.status.split(':')[0] for d in dump_fail})) or 'n/a'})."
        )
    else:
        dec_line = (
            "- **Keyword hit rate:** not scored "
            "(``tokens-only`` mode or no finished LLM runs)."
        )

    latency_line = (
        "- **Latency:** omitted as a savings claim — only compare wall times when "
        "**both** arms finish; failed dump arms return quickly with 0 completion tokens."
    )
    if both_finished:
        mean_dump_ms = sum(d.wall_ms for d, _ in both_finished) / len(both_finished)
        mean_pack_ms = sum(p.wall_ms for _, p in both_finished) / len(both_finished)
        latency_line = (
            f"- **Mean wall time (both finished, n={len(both_finished)}):** "
            f"dump {mean_dump_ms/1000:.2f}s vs pack {mean_pack_ms/1000:.2f}s."
        )

    lines = [
        "# Pack-vs-dump proxy (Antigravity-themed scenarios)",
        "",
        f"> **Generated:** {now}  ",
        f"> **Mode:** `{scorecard.mode}`  ",
        f"> **LLM driver:** "
        f"{'`none` (local sizes only)' if scorecard.mode == 'tokens-only' else f'`{scorecard.driver}` (live API)'}  ",
        f"> **brainkm:** {_BRAINKM_VERSION} · live `.brain/brain.db`",
        "",
        "## Method (read this first)",
        "",
        "This is a **pack-vs-dump** proxy:",
        "",
        "- **Dump arm:** concatenate scenario `target_files` into the prompt.",
        "- **Pack arm:** inject `compile_context_pack` text (≤1500-token product cap on pack body).",
        "",
        "It does **not** drive Google Antigravity IDE, does **not** count "
        "`grep_search` / `view_file` hops, and does **not** measure multi-turn "
        "agent trajectories. Full-tool A/B (Cursor SDK / live AGY) is deferred.",
        "",
        "Same metric class as `brainkm bench run compare` and the Antigravity live "
        "pack-vs-dump report.",
        "",
        "## Headline (context size)",
        "",
        f"- **Dump → pack size reduction:** **{reduction:.1f}%** "
        f"({avg_dump:,.0f} → {avg_pack:,.0f} tokens, ~{factor:.1f}×).",
        dec_line,
        latency_line,
        "",
        "## Scenario matrix",
        "",
        "| Scenario | Arm | Context body tok | Prompt tok | Completion | Total | Status | Keyword hit | Wall |",
        "|----------|-----|------------------|------------|------------|-------|--------|-------------|------|",
    ]

    for r in scorecard.records:
        arm = "dump (files)" if r.arm == "dump" else "**pack (brainkm)**"
        hit = (
            "—"
            if r.decision_hit is None
            else ("yes" if r.decision_hit else "no")
        )
        comp = "—" if r.completion_tokens is None else f"{r.completion_tokens:,}"
        prompt = "—" if r.prompt_tokens is None else f"{r.prompt_tokens:,}"
        total = "—" if r.total_tokens is None else f"**{r.total_tokens:,}**"
        wall = "—" if r.mode == "tokens-only" else f"{r.wall_ms/1000:.2f}s"
        lines.append(
            f"| `{r.scenario_id}` | {arm} | {r.dump_or_pack_tokens:,} | {prompt} | "
            f"{comp} | {total} | `{r.status}` | {hit} | {wall} |"
        )

    lines.extend(
        [
            "",
            "## Previews (LLM mode only)",
            "",
        ]
    )
    if scorecard.mode == "tokens-only":
        lines.append("_No LLM responses in `tokens-only` mode._")
        lines.append("")
    else:
        for r in scorecard.records:
            if not r.response_preview and r.status != "finished":
                lines.append(
                    f"### `{r.scenario_id}` / {r.arm} — `{r.status}` (no completion text)"
                )
                lines.append("")
                continue
            lines.append(f"### `{r.scenario_id}` / {r.arm}")
            lines.append(f"- Status: `{r.status}`")
            if r.response_preview:
                lines.append(f"- Preview: *\"{r.response_preview}…\"*")
            lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Reproduce",
            "",
            "```bash",
            "# Local economics only (no API key)",
            "PYTHONPATH=brainkm .venv/bin/python brainkm/scripts/antigravity_trajectory_bench.py \\",
            "  --mode tokens-only",
            "",
            "# Optional live LLM (Groq or Gemini)",
            "PYTHONPATH=brainkm .venv/bin/python brainkm/scripts/antigravity_trajectory_bench.py \\",
            "  --mode llm --driver auto",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=_REPO)
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO
        / "docs"
        / "benchmarks"
        / "2026-07-22-antigravity-trajectory-live.md",
    )
    parser.add_argument(
        "--mode",
        choices=("tokens-only", "llm"),
        default="tokens-only",
        help="tokens-only = local dump vs pack sizes; llm = call Groq/Gemini",
    )
    parser.add_argument(
        "--driver",
        choices=("auto", "gemini", "groq"),
        default="auto",
        help="LLM backend when --mode llm (default: gemini if key else groq)",
    )
    parser.add_argument(
        "--write-ndjson",
        type=Path,
        default=None,
        help="Optional NDJSON path (default: alongside --out)",
    )
    args = parser.parse_args(argv)

    # Load .env if present (GROQ_API_KEY / GEMINI_API_KEY) without printing secrets.
    env_path = args.repo / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = val

    driver = (
        "none" if args.mode == "tokens-only" else _resolved_driver(args.driver)
    )
    records: list[PackVsDumpRecord] = []

    for scenario in ANTIGRAVITY_SCENARIOS:
        print(f"Scenario {scenario['id']} ({args.mode})…")
        dump_rec, pack_rec = run_scenario(
            scenario, args.repo.resolve(), mode=args.mode, driver=args.driver
        )
        print(
            f"  dump={dump_rec.dump_or_pack_tokens} tok status={dump_rec.status} | "
            f"pack={pack_rec.dump_or_pack_tokens} tok status={pack_rec.status}"
        )
        records.extend([dump_rec, pack_rec])

    scorecard = PackVsDumpScorecard(
        records=records,
        driver=driver,
        mode=args.mode,
        project_dir=args.repo.resolve(),
    )
    md = generate_markdown(scorecard)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(f"Wrote {args.out}")

    ndjson_path = args.write_ndjson or args.out.with_suffix(".ndjson")
    with ndjson_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    print(f"Wrote {ndjson_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
