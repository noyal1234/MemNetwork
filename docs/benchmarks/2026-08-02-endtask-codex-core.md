# End-task A/B scorecard (uniform protocol)

## Run manifest

- **protocol_version:** `endtask_protocol/1.2`
- **fixture_id / version:** `endtask_v1` / `1`
- **tier:** `core`
- **host:** `codex`
- **host_cli_version:** `codex-cli 0.146.0-alpha.9.2`
- **model:** `gpt-5.6-luna/effort=low`
- **brainkm_version:** `0.9.0`
- **repo_git_sha:** `2e1a094`
- **harness_git_sha:** `2e1a094`
- **run_id:** `2026-08-02-codex-core-2e1a094`
- **tokens_supported:** `True`
- **started_at / finished_at:** `2026-08-02T17:29:13.745351+00:00` / `2026-08-02T17:44:31.786760+00:00`
- **MCP integrity:** ok
- **runs recorded:** 36

## Headline

| Arm | Pass | Mean tools | Mean MCP_db | mcp_ok | Mean rounds | Cumulative prompt tokens | Tokens / round |
|-----|------|------------|-------------|--------|-------------|--------------------------|----------------|
| **with brainkm** | 16/18 | 3.1 | 1.5 | 18/18 | 4.1 | 91433 (2.1× vs without) | 22003 (1.4× vs without) |
| without | 17/18 | 1.5 | 0.0 | 18/18 | 2.5 | 42905 | 16277 |

> **Reading the token columns.** Hosts bill `input_tokens` cumulatively across model round-trips — every tool result re-sends the whole conversation. **Cumulative prompt tokens** is therefore the real $ cost but scales with round count, so it cannot be read as "this arm sends more context". **Tokens / round** (cumulative ÷ rounds) is the like-for-like context-size comparison. When the two columns disagree in sign, the difference is tool-call count, not pack size.

## Per-run

| Task | Class | Arm | Rep | Pass | Tools | MCP_db | mcp_ok | rounds | prompt_tok | tok/round | Status | Detail |
|------|-------|-----|-----|------|-------|--------|--------|--------|------------|-----------|--------|--------|
| `k_budget_cap` | knowledge | with_brainkm | 1 | Y | 4 | 2 | Y | 5 | 116472 | 23294 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 2 | Y | 4 | 1 | Y | 5 | 119597 | 23919 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | with_brainkm | 3 | Y | 3 | 2 | Y | 4 | 73994 | 18498 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 1 | Y | 3 | 0 | Y | 4 | 103484 | 25871 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 2 | Y | 2 | 0 | Y | 3 | 60279 | 20093 | `finished` | all_patterns |
| `k_budget_cap` | knowledge | without | 3 | Y | 2 | 0 | Y | 3 | 59956 | 19985 | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 1 | N | 1 | 1 | Y | 2 | 49135 | 24568 | `finished` | missing=['(?i)pin'] |
| `k_remember_role` | knowledge | with_brainkm | 2 | Y | 1 | 1 | Y | 2 | 49217 | 24608 | `finished` | all_patterns |
| `k_remember_role` | knowledge | with_brainkm | 3 | N | 1 | 1 | Y | 2 | 43352 | 21676 | `finished` | missing=['(?i)pin'] |
| `k_remember_role` | knowledge | without | 1 | N | 0 | 0 | Y | 1 | 11524 | 11524 | `finished` | missing=['(?i)pin'] |
| `k_remember_role` | knowledge | without | 2 | Y | 1 | 0 | Y | 2 | 27765 | 13882 | `finished` | all_patterns |
| `k_remember_role` | knowledge | without | 3 | Y | 1 | 0 | Y | 2 | 25745 | 12872 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 1 | Y | 3 | 2 | Y | 4 | 66649 | 16662 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 2 | Y | 3 | 1 | Y | 4 | 100807 | 25202 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | with_brainkm | 3 | Y | 4 | 2 | Y | 5 | 101912 | 20382 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 1 | Y | 2 | 0 | Y | 3 | 60806 | 20269 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 2 | Y | 2 | 0 | Y | 3 | 59835 | 19945 | `finished` | all_patterns |
| `k_fusion_mode` | knowledge | without | 3 | Y | 2 | 0 | Y | 3 | 61107 | 20369 | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 1 | Y | 6 | 3 | Y | 7 | 172406 | 24629 | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 2 | Y | 6 | 2 | Y | 7 | 194340 | 27763 | `finished` | all_patterns |
| `k_layers` | knowledge | with_brainkm | 3 | Y | 4 | 2 | Y | 5 | 104747 | 20949 | `finished` | all_patterns |
| `k_layers` | knowledge | without | 1 | Y | 2 | 0 | Y | 3 | 59151 | 19717 | `finished` | all_patterns |
| `k_layers` | knowledge | without | 2 | Y | 1 | 0 | Y | 2 | 35224 | 17612 | `finished` | all_patterns |
| `k_layers` | knowledge | without | 3 | Y | 1 | 0 | Y | 2 | 34594 | 17297 | `finished` | all_patterns |
| `c_budget_default` | change | with_brainkm | 1 | Y | 2 | 1 | Y | 3 | 59437 | 19812 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | with_brainkm | 2 | Y | 3 | 2 | Y | 4 | 68666 | 17166 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | with_brainkm | 3 | Y | 2 | 1 | Y | 3 | 67812 | 22604 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 1 | Y | 2 | 0 | Y | 3 | 40047 | 13349 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 2 | Y | 1 | 0 | Y | 2 | 23532 | 11766 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_budget_default` | change | without | 3 | Y | 1 | 0 | Y | 2 | 23491 | 11746 | `finished` | 32:    total_tokens: int = Field(default=1500, ge=100, le=8000) |
| `c_endtask_fixture_present` | change | with_brainkm | 1 | Y | 3 | 1 | Y | 4 | 89369 | 22342 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | with_brainkm | 2 | Y | 3 | 1 | Y | 4 | 88887 | 22222 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | with_brainkm | 3 | Y | 3 | 1 | Y | 4 | 78995 | 19749 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 1 | Y | 1 | 0 | Y | 2 | 24298 | 12149 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 2 | Y | 2 | 0 | Y | 3 | 37170 | 12390 | `finished` | 2:  "id": "endtask_v1", |
| `c_endtask_fixture_present` | change | without | 3 | Y | 1 | 0 | Y | 2 | 24283 | 12142 | `finished` | 2:  "id": "endtask_v1", |

## Notes

- protocol=endtask_protocol/1.1
- tier=core
- host=codex; tokens_supported=true (codex exec --json turn.completed.usage)
- isolation: temp CODEX_HOME (auth only) + --ignore-rules --ephemeral; AGENTS.md neutralized
- with-arm: temp CODEX_HOME [mcp_servers.brainkm] + WITH_ARM_MCP_PREFIX
- auth: ChatGPT login / CODEX_API_KEY (API key not required when logged in)
- model=gpt-5.6-luna
- model_reasoning_effort=low
- timeout=600s
- require-mcp enabled
- re-rendered under endtask_protocol/1.2 (per-round token normalization); raw runs unchanged from the 1.1 execution

---

## Analysis — read this before quoting the headline

### 1. The pass-rate gap is a grader artifact, not a capability gap

All three `k_remember_role` failures (both arms) miss exactly one regex, `(?i)pin`.
The failing answers are semantically complete:

> with_brainkm r1 (FAIL): *"Call `remember` when you need to explicitly preserve durable
> project truth, correct a bad auto-capture, or archive noise"*
>
> without r2 (PASS): *"Call `remember` only to explicitly pin durable…"*

Same content; one used the fixture's magic word. **16/18 vs 17/18 is a one-word vocabulary
lottery.** Do not read a capability difference into it. Fixing the pattern requires a fixture
version bump and a re-run of both arms — it must not be retro-applied to these numbers, and it
would also invalidate the published Cursor/AGY `k_remember_role` cells.

### 2. The token cost decomposes — and it inverts on longer tasks

Codex bills `input_tokens` cumulatively across model round-trips, so cumulative cost is
`a*R + b*R(R-1)/2` for `R` rounds: `a` = fixed context re-sent every round, `b` = tokens each
tool result adds to all later rounds. Least-squares fit over the 36 runs:

| Arm | `a` — fixed per round | `b` — per tool result |
|-----|----------------------|-----------------------|
| with brainkm | **16,914** | **2,864** |
| without | 7,603 | 11,235 |

brainkm makes an explicit trade: **+9,311 fixed tokens per round, −8,371 tokens per tool
result.** The ≤1500-token pack cap is doing exactly its job — a `recall`/`context_pack` result
costs ~2.9k where the without-arm's grep/read dumps ~11.2k.

That trade has a crossover:

| Rounds | Tools | with brainkm | without | Winner |
|--------|-------|--------------|---------|--------|
| 2 | 1 | 36,692 | 26,441 | without |
| 3 | 2 | 59,334 | 56,514 | without |
| **4** | **3** | **84,840** | **97,822** | **brainkm** |
| 6 | 5 | 144,444 | 214,143 | brainkm |
| 8 | 7 | 215,504 | 375,404 | brainkm |

**brainkm loses on tasks under ~3 tool calls and wins — increasingly — above that.**
`endtask_v1` core has a 1.5-tool mean in the without arm, which is squarely in brainkm's
worst region. The headline "2.1×" is the fixture selecting short tasks, not a context-bloat
defect. (Fit RMSE is 10.5k / 7.3k on n=18 per arm — the direction is solid, the crossover
point is ±1 round.)

### 3. Why brainkm doesn't displace exploration here

Substitution is zero on this fixture: brainkm adds 1.50 MCP calls while non-MCP exploration
goes 1.50 → 1.61 (up, not down). The cause is **headroom, not routing**. `endtask_v1` asks about
brainkm's own configuration inside the brainkm repo — `total_tokens` is one `rg` away in
`brain_config.py`. Memory cannot beat grep at reading a literal from a file that is right there.

The Codex routing rules are near-identical to Cursor's in every substitution-relevant line
(`diff brainkm/hooks/cursor/brainkm.mdc brainkm/hooks/codex/rules/brainkm.md`), so this is not
a Codex rules defect.

### 4. What this card does and does not support

**Supported:** on short, grep-answerable tasks, brainkm's fixed overhead (~9.3k/round:
~2.7k MCP tool schemas + ~1.6k rules file + SessionStart injection + MCP prefix) is not repaid.

**Not supported:** "brainkm costs 2.1× context on Codex." Per-round context is 1.4×, and total
cost inverts in brainkm's favour above ~3 tool calls.

**Unresolved:** `endtask_v1` core cannot discriminate on this host. A headroom-positive fixture —
tasks whose answers exist only in memory (superseded decisions, cross-session rationale, why a
pivot happened) and are *not* recoverable by grepping the repo — is required before any
Codex Core claim is published.
