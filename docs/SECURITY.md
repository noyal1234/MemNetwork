# Security posture

brainkm is a **local-first** project brain. All durable writes go through SQLite under `.brain/`.

## Capture / remember (inbound)

Every neuron write funnels through `remember_neuron` → `adapters/redaction.py`:

- Secret patterns are blocked or stripped (API keys, tokens, private keys).
- Prompt-injection patterns are scanned before persistence.
- Never store credentials in neurons or `.brain/config.json`. Groq keys live in env / `.env` only.

## Injection pack (outbound)

Neurons are attacker-influenceable because they are distilled from chat transcripts.
`context_pack` / PreToolUse injection therefore re-runs the same redaction scan before
a neuron body is included in an agent-facing pack (outbound injection gate).

## Soft delete + audit trail

- `forget` sets `valid_until` via `audit_log` (no hard delete on the agent path).
- Hygiene / decay soft-archives noisy or unused neurons; consolidation supersedes duplicates.

## Network

- Default distill mode is offline (`rules`) or local (`ollama` / hashing embeddings).
- Optional Groq / MCP sampling require explicit config.
- MCP HTTP transport binds to `127.0.0.1` by default.

## Supply chain

- Optional `[semantic]` extra pulls `onnxruntime`, `sqlite-vec`, `huggingface_hub`, `tokenizers`, `numpy`.
- ONNX MiniLM / cross-encoder weights download only after wizard or doctor consent into `~/.cache/brainkm/onnx/` (not the project tree).
- Graphify extract stays offline (`code_only`) when configured.
