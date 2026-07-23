#!/usr/bin/env python3
"""Measure brainkm serve RSS/CPU: cold start, idle, health load, MCP tool load.

Writes a markdown report suitable for README marketing claims.

Usage (from repo root, venv active):

    python brainkm/scripts/footprint_harness.py
    python brainkm/scripts/footprint_harness.py --out docs/benchmarks/footprint.md
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Sample:
    t: float
    rss_mb: float
    cpu_pct: float


def _ps(pid: int) -> tuple[float, float] | None:
    """Return (rss_mb, cpu_pct) or None if process gone."""
    try:
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "rss=,pcpu="],
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    if not out:
        return None
    parts = out.split()
    if len(parts) < 2:
        return None
    rss_kb = float(parts[0])
    cpu = float(parts[1])
    return rss_kb / 1024.0, cpu


def _sample_window(pid: int, seconds: float, interval: float = 0.25) -> list[Sample]:
    samples: list[Sample] = []
    end = time.monotonic() + seconds
    t0 = time.monotonic()
    while time.monotonic() < end:
        got = _ps(pid)
        if got is None:
            break
        rss, cpu = got
        samples.append(Sample(time.monotonic() - t0, rss, cpu))
        time.sleep(interval)
    return samples


def _summarize(samples: list[Sample]) -> dict[str, float]:
    if not samples:
        return {"n": 0}
    rss = [s.rss_mb for s in samples]
    cpu = [s.cpu_pct for s in samples]
    return {
        "n": float(len(samples)),
        "rss_min_mb": min(rss),
        "rss_median_mb": statistics.median(rss),
        "rss_p95_mb": sorted(rss)[max(0, int(len(rss) * 0.95) - 1)],
        "rss_max_mb": max(rss),
        "cpu_median_pct": statistics.median(cpu),
        "cpu_p95_pct": sorted(cpu)[max(0, int(len(cpu) * 0.95) - 1)],
        "cpu_max_pct": max(cpu),
        "cpu_mean_pct": statistics.mean(cpu),
    }


def _wait_health(base: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_err = ""
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base}/health", timeout=1.0)
            if r.status_code == 200:
                return
            last_err = f"status={r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
        time.sleep(0.15)
    raise RuntimeError(f"health not ready: {last_err}")


async def _mcp_tool_load(url: str, token: str, rounds: int) -> dict[str, object]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {token}"}
    calls = 0
    errors = 0
    t0 = time.monotonic()
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [
                ("brain_stats", {}),
                ("recall", {"query": "token budget greedy_truncate", "limit": 5}),
                (
                    "context_pack",
                    {
                        "query": "observe promote review detail truncation",
                        "seed_refs": ["brainkm/brainkm/services/observe.py"],
                    },
                ),
                (
                    "traverse",
                    {"from_ref": "remember_neuron", "max_hops": 1},
                ),
            ]
            for _ in range(rounds):
                for name, args in tools:
                    try:
                        await session.call_tool(name, args)
                        calls += 1
                    except Exception:  # noqa: BLE001
                        errors += 1
    return {
        "calls": calls,
        "errors": errors,
        "elapsed_s": round(time.monotonic() - t0, 3),
    }


def _fmt(summary: dict[str, float]) -> str:
    if not summary.get("n"):
        return "_no samples_"
    return (
        f"RSS median **{summary['rss_median_mb']:.1f} MB** "
        f"(min {summary['rss_min_mb']:.1f} / p95 {summary['rss_p95_mb']:.1f} / "
        f"max {summary['rss_max_mb']:.1f}); "
        f"CPU mean **{summary['cpu_mean_pct']:.2f}%** "
        f"(median {summary['cpu_median_pct']:.2f} / p95 {summary['cpu_p95_pct']:.2f} / "
        f"max {summary['cpu_max_pct']:.2f})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=REPO_ROOT,
        help="Project with .brain/ (default: repo root)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765, help="Ephemeral serve port")
    parser.add_argument("--idle-seconds", type=float, default=8.0)
    parser.add_argument("--health-seconds", type=float, default=6.0)
    parser.add_argument("--load-rounds", type=int, default=4)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "docs" / "benchmarks" / "footprint.md",
    )
    args = parser.parse_args()

    # Same per-project bearer as real clients (.brain/mcp_http_token).
    sys.path.insert(0, str(REPO_ROOT / "brainkm"))
    from brainkm.services.mcp_http_auth import ensure_mcp_http_token

    token = ensure_mcp_http_token(args.project_dir)
    env = os.environ.copy()
    # Prefer project venv brainkm if present
    brainkm_bin = args.project_dir / ".venv" / "bin" / "brainkm"
    cmd_bin = str(brainkm_bin) if brainkm_bin.is_file() else "brainkm"

    proc = subprocess.Popen(
        [
            cmd_bin,
            "serve",
            "--project-dir",
            str(args.project_dir),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    base = f"http://{args.host}:{args.port}"
    mcp_url = f"{base}/mcp"
    results: dict[str, object] = {
        "measured_at": datetime.now(UTC).isoformat(),
        "host": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
        },
        "serve": {
            "port": args.port,
            "pid": proc.pid,
        },
    }

    try:
        cold_samples: list[Sample] = []
        t_boot = time.monotonic()
        while time.monotonic() - t_boot < 25:
            got = _ps(proc.pid)
            if got:
                cold_samples.append(Sample(time.monotonic() - t_boot, got[0], got[1]))
            try:
                r = httpx.get(f"{base}/health", timeout=0.5)
                if r.status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.1)
        else:
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"serve failed to start: {err[:500]}")

        results["cold_start_s"] = round(time.monotonic() - t_boot, 3)
        results["cold_start"] = _summarize(cold_samples)

        # Settle briefly, then idle window
        time.sleep(1.0)
        idle = _sample_window(proc.pid, args.idle_seconds)
        results["idle"] = _summarize(idle)

        # Health-check load (concurrent-ish via rapid sequential)
        stop_at = time.monotonic() + args.health_seconds
        health_ok = 0
        health_err = 0

        def _health_spam() -> None:
            nonlocal health_ok, health_err
            while time.monotonic() < stop_at:
                try:
                    r = httpx.get(f"{base}/health", timeout=1.0)
                    if r.status_code == 200:
                        health_ok += 1
                    else:
                        health_err += 1
                except Exception:  # noqa: BLE001
                    health_err += 1

        import threading

        threads = [threading.Thread(target=_health_spam, daemon=True) for _ in range(4)]
        for th in threads:
            th.start()
        health_samples = _sample_window(proc.pid, args.health_seconds)
        for th in threads:
            th.join(timeout=2.0)
        results["health_load"] = _summarize(health_samples)
        results["health_requests"] = {"ok": health_ok, "err": health_err}

        # MCP tool load
        import asyncio

        load_meta = asyncio.run(_mcp_tool_load(mcp_url, token, args.load_rounds))
        # Sample during a second load pass for RSS/CPU under tools
        load_samples: list[Sample] = []

        async def _load_and_sample() -> dict[str, object]:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            headers = {"Authorization": f"Bearer {token}"}
            calls = 0
            errors = 0
            t0 = time.monotonic()
            async with streamablehttp_client(mcp_url, headers=headers) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    for _ in range(args.load_rounds):
                        for name, tool_args in (
                            ("brain_stats", {}),
                            (
                                "recall",
                                {"query": "architecture decisions token budget", "limit": 8},
                            ),
                            (
                                "context_pack",
                                {
                                    "query": "MCP dispatch WriteQueue remember_neuron",
                                    "seed_refs": ["brainkm/brainkm/tools/dispatch.py"],
                                },
                            ),
                            ("traverse", {"from_ref": "ReviewDetailModal", "max_hops": 1}),
                        ):
                            try:
                                await session.call_tool(name, tool_args)
                                calls += 1
                            except Exception:  # noqa: BLE001
                                errors += 1
                            got = _ps(proc.pid)
                            if got:
                                load_samples.append(Sample(time.monotonic() - t0, got[0], got[1]))
            return {
                "calls": calls,
                "errors": errors,
                "elapsed_s": round(time.monotonic() - t0, 3),
            }

        load_meta2 = asyncio.run(_load_and_sample())
        results["mcp_warmup"] = load_meta
        results["mcp_tool_load"] = {**load_meta2, **_summarize(load_samples)}

        # Post-load idle (memory retained?)
        time.sleep(1.0)
        post = _sample_window(proc.pid, 4.0)
        results["post_load_idle"] = _summarize(post)

        # Host facts
        try:
            mem = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
            ncpu = int(subprocess.check_output(["sysctl", "-n", "hw.ncpu"], text=True).strip())
            results["host"]["ram_gb"] = round(mem / (1024**3), 1)
            results["host"]["logical_cpus"] = ncpu
        except Exception:  # noqa: BLE001
            pass

        # Brain size
        db = args.project_dir / ".brain" / "brain.db"
        if db.is_file():
            results["brain_db_mb"] = round(db.stat().st_size / (1024 * 1024), 1)

        # Version
        try:
            ver = subprocess.check_output([cmd_bin, "version"], text=True).strip()
            results["brainkm_version"] = ver
        except Exception:  # noqa: BLE001
            results["brainkm_version"] = "unknown"

    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    idle = results.get("idle", {})
    load = results.get("mcp_tool_load", {})
    claim_rss = idle.get("rss_median_mb") if isinstance(idle, dict) else None
    claim_cpu = idle.get("cpu_mean_pct") if isinstance(idle, dict) else None
    load_rss_max = load.get("rss_max_mb") if isinstance(load, dict) else None

    md_lines = [
        "# brainkm footprint",
        "",
        f"Measured: `{results.get('measured_at')}`  ",
        f"Version: `{results.get('brainkm_version')}`  ",
        f"Host: {results.get('host')}  ",
        f"Brain DB: {results.get('brain_db_mb')} MB  ",
        f"Cold start: {results.get('cold_start_s')} s",
        "",
        "## Method",
        "",
        "1. Start a fresh `brainkm serve` on an ephemeral port (not the long-lived dogfood process).",  # noqa: E501
        "2. Sample RSS/`%CPU` via `ps` every ~250 ms.",
        "3. Phases: cold start → idle → concurrent `/health` spam → MCP tool rounds "
        "(`brain_stats`, `recall`, `context_pack`, `traverse`) → post-load idle.",
        "4. Optional TUI (`brainkm configure`) is **not** included — measure separately if open.",
        "",
        "## Results",
        "",
        "| Phase | Footprint |",
        "|-------|-----------|",
        f"| Cold start | {_fmt(results.get('cold_start', {}))} |",  # type: ignore[arg-type]
        f"| Idle | {_fmt(results.get('idle', {}))} |",  # type: ignore[arg-type]
        f"| Health load | {_fmt(results.get('health_load', {}))} |",  # type: ignore[arg-type]
        f"| MCP tool load | {_fmt(results.get('mcp_tool_load', {}))} |",  # type: ignore[arg-type]
        f"| Post-load idle | {_fmt(results.get('post_load_idle', {}))} |",  # type: ignore[arg-type]
        "",
        "## Marketing-safe claim",
        "",
    ]
    if claim_rss is not None and claim_cpu is not None:
        md_lines.extend(
            [
                f"- Idle shared server: about **{claim_rss:.0f} MB RAM** and "
                f"**~{claim_cpu:.1f}% CPU** (mean) on this host.",
                f"- Under MCP tool load, RSS peaked around **{load_rss_max:.0f} MB** "
                f"in this run (still a single local process).",
                "- Spikes from distill / graph sync are short-lived and out of band of idle `serve`.",  # noqa: E501
                "",
            ]
        )
    md_lines.extend(
        [
            "## Reproduce",
            "",
            "```bash",
            "python brainkm/scripts/footprint_harness.py \\",
            f"  --out {args.out.as_posix()}",
            "```",
            "",
            "## Raw data",
            "",
            f"Companion JSON: `{args.out.with_suffix('.json').name}`",
            "",
        ]
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    raw_path = args.out.with_suffix(".json")
    raw_path.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"wrote {raw_path}")
    if claim_rss is not None:
        print(
            f"idle_median_rss_mb={claim_rss:.1f} idle_mean_cpu_pct={claim_cpu:.2f} "
            f"load_max_rss_mb={load_rss_max}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
