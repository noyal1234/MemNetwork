# brainkm footprint

Measured: `2026-07-21T10:55:58+00:00`  
Version: `0.8.1`  
Host: macOS / Python 3.12.13 / 16 GB RAM / 12 logical CPUs  
Brain DB: 11.3 MB  
Cold start: 1.4 s

## Method

1. Start a fresh `brainkm serve` on an ephemeral port (not the long-lived dogfood process).
2. Sample RSS / `%CPU` via `ps` every ~250 ms.
3. Phases: cold start → idle → concurrent `/health` spam → MCP tool rounds
   (`brain_stats`, `recall`, `context_pack`, `traverse`) → post-load idle.
4. Optional TUI (`brainkm configure`) is measured separately — not part of the always-on claim.

Harness: [`brainkm/scripts/footprint_harness.py`](../../brainkm/scripts/footprint_harness.py).

## Results (fresh serve)

| Phase | RSS median | RSS max | CPU mean |
|-------|------------|---------|----------|
| Cold start | 41.8 MB | 57.2 MB | high (boot) |
| Idle (~10 s) | **57.2 MB** | 57.2 MB | **0.17%** |
| Health spam (~8 s, 1156 ok) | 57.7 MB | 57.7 MB | 19.4% |
| MCP tool load (20 calls) | **112.1 MB** | **112.8 MB** | 64.3% (busy) |
| Post-load idle | 112.8 MB | 112.8 MB | **0.21%** |

## Additional samples (same host, same day)

| Process / phase | RSS median | RSS max | CPU mean |
|-----------------|------------|---------|----------|
| Long-lived dogfood `serve :8765` (8 s idle) | **66.1 MB** | 66.1 MB | **0.11%** |
| `graph sync --skip-extract` (one-shot) | 60.9 MB | 90.7 MB | high while running |
| Ephemeral `brainkm version` | 20.1 MB | 29.0 MB | brief (~0.5 s) |
| Optional `brainkm configure` TUI (idle) | **162.7 MB** | 162.7 MB | ~0% |

## README claim (grounded)

- Always-on shared brain: **~55–70 MB idle RSS**, **≪1% CPU**
- Active MCP retrieval: peaks around **~110 MB**, then CPU returns near zero (RSS may stay elevated until process recycle)
- Optional configure TUI: ~**160 MB** — not required for the product footprint claim
- One-shot graph sync / hooks: short-lived spikes, not steady-state

## Reproduce

```bash
source .venv/bin/activate
python brainkm/scripts/footprint_harness.py \
  --out docs/benchmarks/YYYY-MM-DD-footprint.md
```

## Raw data

- [`2026-07-21-footprint.json`](2026-07-21-footprint.json)
- [`2026-07-21-footprint-extra.json`](2026-07-21-footprint-extra.json)
