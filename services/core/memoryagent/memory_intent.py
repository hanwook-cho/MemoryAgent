"""Detect user intent to save long-term memory from chat text (agent-actions.md §2)."""

from __future__ import annotations

import re

# Last user message must match: optional "please", then one of the phrases, then body.
_MEMORY_SAVE = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?:remember\s+that|remember:|note\s+that|note:|save\s+to\s+memory:|memorize:)"
    r"\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def extract_memory_save_text(message: str) -> str | None:
    """If the message is a save request, return the text to store; else None."""
    text = (message or "").strip()
    if not text:
        return None
    m = _MEMORY_SAVE.match(text)
    if not m:
        return None
    body = (m.group(1) or "").strip()
    return body if body else None
