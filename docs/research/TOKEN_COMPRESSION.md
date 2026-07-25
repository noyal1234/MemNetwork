# Token compression research (brainkm)

Status: shipped in brainkm **0.8.5** (core pipeline). This note records composition modes, metrics, and quality gates.

## Axes

| Axis | Owner | Mechanism |
|------|--------|-----------|
| Mode A append (PreTool, MCP tool_result) | brainkm + host cache | Cold on write; warm reads TTL-decayed |
| Mode S frozen SessionStart | brainkm | Stable bytes until PostCompact refresh |
| Mode R early rewrite | **Forbidden** for SessionStart | Would bust prefix cache |
| Host shell stdout | Optional RTK binary | Companion tip via `brainkm doctor` |
| Agent output brevity | Optional terse skill | Net-session metric; not meme caveman |

## Durable edges vs OmniRoute

1. Subtype/class known at write from the object model.
2. Persistent cross-session graph (PPR / neuron lifecycle).

## Core pipeline

```text
classify (+ sub-blocks) → protect → rtk_lite / prose / error_trim
  → session dedup → per-stage inflation_guard → budget
```

- Decision/rule **store**: no lossy rewrite.
- Decision/rule **egress**: optional lite only if polarity rubric ≥95%.
- rtk_lite: **mandatory tee** on failure-shaped tool logs (`.brain/tee/`).
- Metadata: **out-of-band only** (SQLite `compression_*` tables).
- Canary: sticky per `session_id` at SessionStart.

## Metrics

- `brain_stats.compression` — rollups by surface, engine_version, cache TTL.
- Mode A write-only $ gate (conservative) + TTL-decayed lifetime report.
- Context-rot: `unique_neuron_token_density`, `redundant_reinject_rate`.
- Tokenizers: label family when publishing % (tiktoken for OpenAI-family proxy; Anthropic `count_tokens` when available).

## Config (`.brain/config.json` → `compression`)

See `CompressionConfig` in `brainkm/models/brain_config.py`. Defaults enable the pipeline; `llmlingua_enabled` stays false (optional `brainkm[compression]`).

## Hakim et al. 2026

Brevity constraints can help on math/STEM overthinking for large models — **A/B hypothesis** for coding agents, not doctrine. Terse skill uses net-session tokens, not vanity output %.

## MCP tool-definition cost

Prefer **deferred / tool-search** loading where the host supports it (e.g. Claude Code). Cursor and many IDE paths still eager-load tools — brainkm keeps a 6-tool surface; do not rely on lossy description shrinking as the primary lever. Optional host RTK: `brainkm doctor` soft tip.

## Optional install

```bash
pip install "brainkm[compression]"   # LLMLingua-2; fail-open if unused
```

Enable only via `compression.llmlingua_enabled` after fidelity checks.
