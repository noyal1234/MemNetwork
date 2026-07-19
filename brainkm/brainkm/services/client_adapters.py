"""Client adapter abstraction for hooks / transcripts / install snippets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ClientKind = Literal["cursor", "claude", "codex", "antigravity", "generic"]


@dataclass(frozen=True)
class HookCommand:
    event: str
    command: str
    matcher: str | None = None


class ClientAdapter(Protocol):
    kind: ClientKind

    def hook_events(self) -> list[str]: ...

    def transcript_style(self) -> str: ...

    def agents_snippet(self) -> str: ...

    def config_dir_name(self) -> str: ...


AGENTS_SNIPPET = """# brainkm — project memory routing

Memory accumulates from **hooks** (SessionStart injection, SessionEnd distill,
PostToolUse observations). You do **not** need to call `remember` for ordinary learning.

Use the **brainkm** MCP tools:

| Question | Tool |
|----------|------|
| Why did we choose X? | `recall` |
| What calls / imports X? Impact of changing Y? | `traverse` |
| Bounded multi-file task context | `context_pack` (include a symbol or path) |
| Pin durable truth or correct a wrong auto-capture | `remember` |

Packs are hints — always verify in source before editing.
Prefer `traverse` for blast-radius; `context_pack` before opening 3+ files.
Expand truncated ids via `recall` with `truncation_followup: true`.
"""


class CursorClientAdapter:
    kind: ClientKind = "cursor"

    def hook_events(self) -> list[str]:
        return [
            "sessionStart",
            "sessionEnd",
            "preCompact",
            "preToolUse",
            "postToolUse",
            "userPromptSubmit",
        ]

    def transcript_style(self) -> str:
        return "cursor_jsonl"

    def agents_snippet(self) -> str:
        return AGENTS_SNIPPET

    def config_dir_name(self) -> str:
        return ".cursor"


class ClaudeClientAdapter:
    kind: ClientKind = "claude"

    def hook_events(self) -> list[str]:
        return [
            "sessionStart",
            "sessionEnd",
            "preCompact",
            "postCompact",
            "preToolUse",
            "postToolUse",
            "userPromptSubmit",
            "postToolUseFailure",
            "subagentStart",
            "subagentStop",
            "stop",
        ]

    def transcript_style(self) -> str:
        return "claude_jsonl"

    def agents_snippet(self) -> str:
        return (
            AGENTS_SNIPPET
            + "\nInstalled for Claude Code via `brainkm install --client claude`.\n"
            + "\n## Coexistence with Claude native memory\n\n"
            + "- **CLAUDE.md / `.claude/rules`** = authored project instructions (static).\n"
            + "- **Claude Auto Memory (`MEMORY.md`)** = Claude's private notes — leave alone.\n"
            + "- **brainkm** = searchable project brain (decisions, graph, compaction survival).\n"
            + "Prefs/debug notes stay in Auto Memory; durable team decisions → brainkm MCP.\n"
        )

    def config_dir_name(self) -> str:
        return ".claude"


class CodexClientAdapter:
    kind: ClientKind = "codex"

    def hook_events(self) -> list[str]:
        return [
            "sessionStart",
            "sessionEnd",
            "preCompact",
            "preToolUse",
            "postToolUse",
        ]

    def transcript_style(self) -> str:
        return "generic_jsonl"

    def agents_snippet(self) -> str:
        return (
            AGENTS_SNIPPET
            + "\nInstalled for Codex via `brainkm connect codex`. "
            "Desktop plugin hooks may be silent — mirror hooks with "
            "`brainkm connect codex --hooks` if needed.\n"
        )

    def config_dir_name(self) -> str:
        return ".codex"


class AntigravityClientAdapter:
    kind: ClientKind = "antigravity"

    def hook_events(self) -> list[str]:
        return [
            "preInvocation",
            "preToolUse",
            "postToolUse",
            "stop",
            "sessionStart",  # optional bonus if host accepts
        ]

    def transcript_style(self) -> str:
        return "antigravity_jsonl"

    def agents_snippet(self) -> str:
        return (
            AGENTS_SNIPPET
            + "\nInstalled for Antigravity via `brainkm install --client antigravity`.\n"
            + "\n## Coexistence with Antigravity native config\n\n"
            + "- **`.agents/rules` / `AGENTS.md`** = authored static instructions.\n"
            + "- **brainkm** = searchable project brain (decisions, graph, session survival).\n"
            + "- Grant `mcp(brainkm/*)` so recall/context_pack are not stuck in Ask mode.\n"
            + "- Do not stack Mem0 (or similar) with brainkm on the same project.\n"
        )

    def config_dir_name(self) -> str:
        return ".agents"


class GenericClientAdapter:
    kind: ClientKind = "generic"

    def hook_events(self) -> list[str]:
        return []

    def transcript_style(self) -> str:
        return "generic_jsonl"

    def agents_snippet(self) -> str:
        return (
            AGENTS_SNIPPET
            + "\nNo IDE hooks installed. Use `brainkm capture` / `brainkm handover` manually.\n"
            + "Shared HTTP example: see `.brain/mcp.http.example.json` after "
            "`brainkm connect generic --http`.\n"
        )

    def config_dir_name(self) -> str:
        return ".brain"


def get_client_adapter(kind: ClientKind | str) -> ClientAdapter:
    mapping: dict[str, ClientAdapter] = {
        "cursor": CursorClientAdapter(),
        "claude": ClaudeClientAdapter(),
        "codex": CodexClientAdapter(),
        "antigravity": AntigravityClientAdapter(),
        "generic": GenericClientAdapter(),
    }
    adapter = mapping.get(str(kind).lower())
    if adapter is None:
        msg = f"unknown client: {kind}"
        raise ValueError(msg)
    return adapter
