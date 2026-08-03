# End-task A/B scorecard (uniform protocol)

## Run manifest

- **protocol_version:** `endtask_protocol/1.2`
- **fixture_id / version:** `endtask_memory_v1` / `1`
- **tier:** `core`
- **host:** `codex`
- **host_cli_version:** `codex-cli 0.146.0-alpha.9.2`
- **model:** `gpt-5.6-luna/effort=low`
- **brainkm_version:** `0.9.0`
- **repo_git_sha:** `2e1a094`
- **harness_git_sha:** `2e1a094`
- **run_id:** `2026-08-03-codex-core-2e1a094`
- **tokens_supported:** `True`
- **started_at / finished_at:** `2026-08-03T05:21:05.812991+00:00` / `2026-08-03T05:49:02.776910+00:00`
- **MCP integrity:** ok
- **runs recorded:** 36

## Headline

| Arm | Pass | Mean tools | Mean MCP_db | mcp_ok | Mean rounds | Cumulative prompt tokens | Tokens / round |
|-----|------|------------|-------------|--------|-------------|--------------------------|----------------|
| **with brainkm** | 18/18 | 5.6 | 1.9 | 18/18 | 6.6 | 170128 (−17% vs without) | 25323 (−10% vs without) |
| without | 2/18 | 5.8 | 0.0 | 18/18 | 6.8 | 204602 | 28192 |

> **Reading the token columns.** Hosts bill `input_tokens` cumulatively across model round-trips — every tool result re-sends the whole conversation. **Cumulative prompt tokens** is therefore the real $ cost but scales with round count, so it cannot be read as "this arm sends more context". **Tokens / round** (cumulative ÷ rounds) is the like-for-like context-size comparison. When the two columns disagree in sign, the difference is tool-call count, not pack size.

## Per-run

| Task | Class | Arm | Rep | Pass | Tools | MCP_db | mcp_ok | rounds | prompt_tok | tok/round | Status | Detail |
|------|-------|-----|-----|------|-------|--------|--------|--------|------------|-----------|--------|--------|
| `m_rejected_chunking` | knowledge | with_brainkm | 1 | Y | 5 | 2 | Y | 6 | 151472 | 25245 | `finished` | all_patterns |
| `m_rejected_chunking` | knowledge | with_brainkm | 2 | Y | 4 | 2 | Y | 5 | 101192 | 20238 | `finished` | all_patterns |
| `m_rejected_chunking` | knowledge | with_brainkm | 3 | Y | 4 | 2 | Y | 5 | 118137 | 23627 | `finished` | all_patterns |
| `m_rejected_chunking` | knowledge | without | 1 | N | 4 | 0 | Y | 5 | 114826 | 22965 | `finished` | missing=['576', '0\\.71'] |
| `m_rejected_chunking` | knowledge | without | 2 | N | 2 | 0 | Y | 3 | 61747 | 20582 | `finished` | missing=['576', '0\\.71'] |
| `m_rejected_chunking` | knowledge | without | 3 | N | 2 | 0 | Y | 3 | 60367 | 20122 | `finished` | missing=['576', '0\\.71'] |
| `m_superseded_budget` | knowledge | with_brainkm | 1 | Y | 4 | 2 | Y | 5 | 112077 | 22415 | `finished` | all_patterns |
| `m_superseded_budget` | knowledge | with_brainkm | 2 | Y | 6 | 2 | Y | 7 | 192442 | 27492 | `finished` | all_patterns |
| `m_superseded_budget` | knowledge | with_brainkm | 3 | Y | 6 | 2 | Y | 7 | 176083 | 25155 | `finished` | all_patterns |
| `m_superseded_budget` | knowledge | without | 1 | N | 9 | 0 | Y | 10 | 408910 | 40891 | `finished` | missing=['4200', '0\\.87', '(?i)noise'] |
| `m_superseded_budget` | knowledge | without | 2 | N | 10 | 0 | Y | 11 | 422744 | 38431 | `finished` | missing=['4200', '0\\.87', '(?i)noise'] |
| `m_superseded_budget` | knowledge | without | 3 | N | 8 | 0 | Y | 9 | 316382 | 35154 | `finished` | missing=['4200', '0\\.87', '(?i)noise'] |
| `m_incident_shadow_write` | knowledge | with_brainkm | 1 | Y | 8 | 3 | Y | 9 | 247991 | 27555 | `finished` | all_patterns |
| `m_incident_shadow_write` | knowledge | with_brainkm | 2 | Y | 7 | 2 | Y | 8 | 266372 | 33296 | `finished` | all_patterns |
| `m_incident_shadow_write` | knowledge | with_brainkm | 3 | Y | 10 | 3 | Y | 11 | 321247 | 29204 | `finished` | all_patterns |
| `m_incident_shadow_write` | knowledge | without | 1 | N | 7 | 0 | Y | 8 | 226686 | 28336 | `finished` | missing=['(?i)absolute'] |
| `m_incident_shadow_write` | knowledge | without | 2 | Y | 4 | 0 | Y | 5 | 154742 | 30948 | `finished` | all_patterns |
| `m_incident_shadow_write` | knowledge | without | 3 | N | 5 | 0 | Y | 6 | 179762 | 29960 | `finished` | missing=['(?i)absolute'] |
| `m_pivot_semantic` | knowledge | with_brainkm | 1 | Y | 6 | 2 | Y | 7 | 161250 | 23036 | `finished` | all_patterns |
| `m_pivot_semantic` | knowledge | with_brainkm | 2 | Y | 3 | 1 | Y | 4 | 103283 | 25821 | `finished` | all_patterns |
| `m_pivot_semantic` | knowledge | with_brainkm | 3 | Y | 2 | 1 | Y | 3 | 64865 | 21622 | `finished` | all_patterns |
| `m_pivot_semantic` | knowledge | without | 1 | N | 2 | 0 | Y | 3 | 64446 | 21482 | `finished` | missing=['0\\.87', '0\\.73'] |
| `m_pivot_semantic` | knowledge | without | 2 | N | 2 | 0 | Y | 3 | 63234 | 21078 | `finished` | missing=['0\\.87', '0\\.73'] |
| `m_pivot_semantic` | knowledge | without | 3 | N | 3 | 0 | Y | 4 | 114859 | 28715 | `finished` | missing=['0\\.87', '0\\.73'] |
| `c_apply_quorum_floor` | change | with_brainkm | 1 | Y | 6 | 2 | Y | 7 | 144913 | 20702 | `finished` | 34:    retrieval_quorum_floor: int = Field(default=3, ge=1) |
| `c_apply_quorum_floor` | change | with_brainkm | 2 | Y | 6 | 2 | Y | 7 | 182848 | 26121 | `finished` | 33:    quorum_floor: int = Field(default=3, ge=1) |
| `c_apply_quorum_floor` | change | with_brainkm | 3 | Y | 7 | 2 | Y | 8 | 177248 | 22156 | `finished` | 34:    quorum_floor: int = Field(default=3, ge=1) |
| `c_apply_quorum_floor` | change | without | 1 | N | 7 | 0 | Y | 8 | 266028 | 33254 | `finished` | exit=1 |
| `c_apply_quorum_floor` | change | without | 2 | N | 7 | 0 | Y | 8 | 171920 | 21490 | `finished` | exit=1 |
| `c_apply_quorum_floor` | change | without | 3 | Y | 6 | 0 | Y | 7 | 202168 | 28881 | `finished` | 33:    quorum_floor: int = Field(default=3, ge=1) |
| `c_hydration_guard_flag` | change | with_brainkm | 1 | Y | 5 | 1 | Y | 6 | 204428 | 34071 | `finished` | 34:    hydration_guard: bool = False |
| `c_hydration_guard_flag` | change | with_brainkm | 2 | Y | 6 | 2 | Y | 7 | 175281 | 25040 | `finished` | 34:    hydration_guard: bool = False |
| `c_hydration_guard_flag` | change | with_brainkm | 3 | Y | 6 | 2 | Y | 7 | 161173 | 23025 | `finished` | 34:    hydration_guard: bool = False |
| `c_hydration_guard_flag` | change | without | 1 | N | 10 | 0 | Y | 11 | 311965 | 28360 | `finished` | exit=1 |
| `c_hydration_guard_flag` | change | without | 2 | N | 8 | 0 | Y | 9 | 234638 | 26071 | `finished` | exit=1 |
| `c_hydration_guard_flag` | change | without | 3 | N | 9 | 0 | Y | 10 | 307412 | 30741 | `finished` | exit=1 |

## Notes

- protocol=endtask_protocol/1.2
- tier=core
- host=codex; tokens_supported=true (codex exec --json turn.completed.usage)
- isolation: temp CODEX_HOME (auth only) + --ignore-rules --ephemeral; AGENTS.md neutralized
- with-arm: temp CODEX_HOME [mcp_servers.brainkm] + WITH_ARM_MCP_PREFIX
- auth: ChatGPT login / CODEX_API_KEY (API key not required when logged in)
- model=gpt-5.6-luna
- model_reasoning_effort=low
- timeout=600s
- require-mcp enabled
