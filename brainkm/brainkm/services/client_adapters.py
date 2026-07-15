"""Client adapter abstraction for hooks / transcripts / install snippets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ClientKind = Literal["cursor", "claude", "generic"]


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

Use the **brainkm** MCP tools for project memory:

| Question | Tool |
|----------|------|
| Why did we choose X? | `recall` |
| What calls / imports X? | `traverse` or `context_pack` |
| Bounded task context | `context_pack` (include a symbol or path) |
| Store a decision | `remember` |

Packs are hints — always verify in source before editing.
Prefer `context_pack` over dumping many files. Expand truncated ids via
`recall` with `truncation_followup: true` instead of re-reading modules.
"""


class CursorClientAdapter:
    kind: ClientKind = "cursor"

    def hook_events(self) -> list[str]:
        return ["sessionStart", "sessionEnd", "preCompact", "preToolUse", "postToolUse"]

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
        ]

    def transcript_style(self) -> str:
        return "claude_jsonl"

    def agents_snippet(self) -> str:
        return AGENTS_SNIPPET + "\nInstalled for Claude Code via `brainkm install --client claude`.\n"

    def config_dir_name(self) -> str:
        return ".claude"


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
        )

    def config_dir_name(self) -> str:
        return ".brain"


def get_client_adapter(kind: ClientKind | str) -> ClientAdapter:
    mapping: dict[str, ClientAdapter] = {
        "cursor": CursorClientAdapter(),
        "claude": ClaudeClientAdapter(),
        "generic": GenericClientAdapter(),
    }
    adapter = mapping.get(str(kind).lower())
    if adapter is None:
        msg = f"unknown client: {kind}"
        raise ValueError(msg)
    return adapter
