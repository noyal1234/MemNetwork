"""Lightweight quality guards for auto-captured neurons."""

from __future__ import annotations

import hashlib
import re
import sqlite3

from brainkm.adapters.cursor_clean import is_distill_noise
from brainkm.models.distill import DistilledNeuron

MIN_TITLE_LEN = 4
MIN_BODY_LEN = 12
MAX_TITLE_LEN = 200
MAX_TITLE_WORDS = 14
BOILERPLATE = re.compile(
    r"^(thanks|thank you|ok|okay|sure|done|yes|no|hello|hi)\.?$",
    re.IGNORECASE,
)
BOILERPLATE_LEAD = re.compile(
    r"^(?:i(?:'|’)?ll|i will|let me|i can|sure[,.]?|okay[,.]?|got it[,.]?|confirming)\b",
    re.IGNORECASE,
)
MARKDOWN_TITLE = re.compile(r"^(?:#{1,6}\s|```|\|\s|- )")
TRANSCRIPT_CHROME = re.compile(
    r"(?is)(?:^|\n)\s*(?:user|assistant|system)\s*:|"
    r"<user_query>|"
    r"</user_query>|"
    r"<timestamp>|"
    r"\[tool_use:",
)
# Raw user questions are not durable project memory.
INTERROGATIVE_LEAD = re.compile(
    r"^(?:can you|could you|would you|will you|what|where|when|why|how|"
    r"is there|are there|do we|does|did|should we|should i|please)\b",
    re.IGNORECASE,
)


def normalize_fingerprint(title: str, body: str) -> str:
    """Stable fingerprint for capture-time dedup."""
    text = re.sub(r"\s+", " ", f"{title.strip().lower()}\n{body.strip().lower()}").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def passes_quality_gate(item: DistilledNeuron) -> bool:
    title = item.title.strip()
    body = (item.body or "").strip()
    if len(title) < MIN_TITLE_LEN or len(title) > MAX_TITLE_LEN:
        return False
    if len(body) < MIN_BODY_LEN:
        return False
    if BOILERPLATE.match(title):
        return False
    if BOILERPLATE_LEAD.match(title) or BOILERPLATE_LEAD.match(body):
        return False
    if MARKDOWN_TITLE.match(title) or title.startswith("##"):
        return False
    if TRANSCRIPT_CHROME.search(title) or TRANSCRIPT_CHROME.search(body):
        return False
    if INTERROGATIVE_LEAD.match(title) or (
        title.rstrip().endswith("?") and INTERROGATIVE_LEAD.match(body[:80])
    ):
        return False
    if body.rstrip().endswith("?") and INTERROGATIVE_LEAD.match(body):
        return False
    # Use noise heuristics for chrome/boilerplate, but skip the length check (already handled).
    if len(title) >= 20 and is_distill_noise(title):
        return False
    if len(body) >= 20 and is_distill_noise(body):
        return False
    if len(title.split()) > MAX_TITLE_WORDS and title.rstrip().endswith((".", "!", "?")):
        # Full-sentence titles are almost always heuristic noise.
        return False
    if not item.is_atomic():
        return False
    return True


def passes_noise_gate(*, title: str, content: str | None) -> bool:
    """Stricter chrome/tool-spam check for injection & hygiene (does not reject long titles)."""
    t = (title or "").strip()
    body = (content or "").strip() or t
    if not t or not body:
        return False
    if BOILERPLATE.match(t):
        return False
    if BOILERPLATE_LEAD.match(t):
        return False
    if MARKDOWN_TITLE.match(t) or t.startswith("##"):
        return False
    if TRANSCRIPT_CHROME.search(t) or TRANSCRIPT_CHROME.search(body):
        return False
    if INTERROGATIVE_LEAD.match(t) or (
        (t.rstrip().endswith("?") or body.rstrip().endswith("?"))
        and INTERROGATIVE_LEAD.match(body)
    ):
        return False
    if "[tool_use:" in t.lower() or "[tool_use:" in body.lower():
        return False
    if "<user_query>" in body.lower() or "<timestamp>" in body.lower():
        return False
    if body.lstrip().upper().startswith("USER:") or body.lstrip().upper().startswith("ASSISTANT:"):
        return False
    return True


def passes_stored_neuron_gate(*, title: str, content: str | None) -> bool:
    """Quality gate for already-stored neurons (injection / hygiene)."""
    return passes_noise_gate(title=title, content=content)


def filter_distilled(
    items: list[DistilledNeuron],
    *,
    max_count: int,
    seen_fingerprints: set[str] | None = None,
) -> list[DistilledNeuron]:
    accepted: list[DistilledNeuron] = []
    fingerprints = seen_fingerprints if seen_fingerprints is not None else set()
    for item in items:
        if len(accepted) >= max_count:
            break
        if not passes_quality_gate(item):
            continue
        fp = normalize_fingerprint(item.title, item.body)
        if fp in fingerprints:
            continue
        fingerprints.add(fp)
        accepted.append(item)
    return accepted


def existing_neuron_fingerprints(
    conn: sqlite3.Connection,
    *,
    limit: int = 500,
) -> set[str]:
    """Fingerprints of recent active memory neurons for capture-time dedup."""
    rows = conn.execute(
        """
        SELECT title, content
        FROM nodes
        WHERE valid_until IS NULL AND kind = 'memory'
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out: set[str] = set()
    for row in rows:
        out.add(normalize_fingerprint(row["title"] or "", row["content"] or ""))
    return out
