"""Shared distill prompts and context helpers for LLM adapters."""

from __future__ import annotations

import json
import re
import sqlite3

VALID_SUBTYPES = frozenset({"decision", "fact", "rule", "error"})

SYSTEM_PROMPT = """You are a memory-extraction assistant for a software project's local knowledge base.
Extract atomic project memory neurons from a chat round between a developer and a coding assistant.

Return ONLY a JSON object of the form:
{"neurons":[{"subtype":"decision|fact|rule|error","title":"...","body":"...","tags":["..."]}]}

Guidelines:
- One atomic fact per item — do not combine multiple ideas into one item.
- Do not produce summaries; each body must be independently verifiable.
- Keep body under 400 characters.
- title is a short noun phrase (max ~8 words), never a full sentence, and never starts with I'll / Let me / Confirming / Sure.
- body must be understandable without the conversation — name the file, symbol, feature, or config it refers to.
- Skip greetings, acknowledgements, tool-call noise, and small talk — extract nothing if the round has no durable fact.
- Use "decision" for choices between alternatives, "rule" for conventions/constraints, \
"error" for bugs/pitfalls, "fact" for everything else.
- tags should be 2-6 lowercase concept keywords, not filler words.
- If nothing durable is present, return {"neurons":[]}.

Example input round:
USER: We decided to use JWT instead of session cookies for API auth.

ASSISTANT: Never store API keys in neurons. Access tokens expire after 15 minutes.

Example output:
{"neurons":[
  {"subtype":"decision","title":"Use JWT for API auth","body":"Chose JWT over session cookies for API authentication.","tags":["jwt","auth","api"]},
  {"subtype":"rule","title":"Never store API keys in neurons","body":"API keys must not be persisted in project memory.","tags":["security","secrets"]}
]}
"""


def normalize_subtype(value: object, *, default: str = "fact") -> str | None:
    """Return a valid subtype or None when the value cannot be coerced."""
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in VALID_SUBTYPES:
        return text
    return None


def build_context_block(conn: sqlite3.Connection | None, *, limit: int = 5) -> str:
    """Format recent non-ephemeral neurons to ground the model and avoid duplicates."""
    if conn is None:
        return ""

    from brainkm.services.memory import recent_neuron_context

    recent = recent_neuron_context(conn, limit=limit)
    if not recent:
        return ""

    lines = ["Recent project memory (avoid duplicating these; reuse existing tags where relevant):"]
    for item in recent:
        tag_str = ", ".join(item.tags) if item.tags else "none"
        lines.append(f"- [{item.subtype}] {item.title} (tags: {tag_str})")
    return "\n".join(lines) + "\n\n"


def parse_json_array(raw: str) -> list[object]:
    """Parse a JSON array from model output, including wrapped {neurons: [...]} forms."""
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("neurons"), list):
            return data["neurons"]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
