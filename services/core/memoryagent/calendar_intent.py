"""Detect calendar intents and parse structured/natural fields from chat."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

_CREATE_PREFIX = re.compile(
    r"^\s*(?:create|add|schedule)\s+(?:a\s+)?(?:calendar\s+)?event\s*:\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)

_KV = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*?)\s*$")
_SPLIT = re.compile(r"\s*;\s*")
_CREATE_NATURAL = re.compile(
    r"^\s*(?:please\s+)?(?:create|add|schedule)\s+(?:(?:a\s+)?(?:calendar\s+)?event\s+)?(.+?)\s+"
    r"(?:at|on)\s+([0-9T:\-\.Z\+]+)"
    r"(?:\s+(?:to|until)\s+([0-9T:\-\.Z\+]+))?"
    r"(?:\s+(?:in|at)\s+(.+))?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_MONTH_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_LOOKUP_HINTS = ("appointment", "calendar", "date", "time", "when", "schedule")
_MONTH_TO_NUM = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class CalendarCreateIntent:
    title: str
    starts_at: str
    ends_at: str | None = None
    all_day: bool = False
    notes: str | None = None
    location: str | None = None
    calendar_id: str | None = None


@dataclass(frozen=True)
class CalendarLookupIntent:
    keywords: list[str]
    month_start_iso: str | None = None
    month_end_iso: str | None = None


def parse_calendar_create_intent(message: str) -> CalendarCreateIntent | None:
    """
    Parse create intent from chat:
    - Structured: `create calendar event: title=...; starts_at=...; ends_at=...; location=...`
    - Natural: `schedule dentist checkup at 2026-07-01T14:00:00Z [to ...] [in ...]`
    """
    text = (message or "").strip()
    if not text:
        return None
    m = _CREATE_PREFIX.match(text)
    if m:
        body = (m.group(1) or "").strip()
        if not body:
            return None

        fields: dict[str, str] = {}
        for part in _SPLIT.split(body):
            if not part:
                continue
            km = _KV.match(part)
            if not km:
                continue
            k = km.group(1).lower()
            v = km.group(2).strip()
            if v:
                fields[k] = v

        title = fields.get("title", "").strip()
        starts_at = fields.get("starts_at", "").strip()
        if not title or not starts_at:
            return None

        all_day_raw = fields.get("all_day", "false").strip().lower()
        all_day = all_day_raw in ("1", "true", "yes", "y")

        return CalendarCreateIntent(
            title=title,
            starts_at=_normalize_iso(starts_at),
            ends_at=_normalize_iso(fields.get("ends_at", "")) if fields.get("ends_at") else None,
            all_day=all_day,
            notes=fields.get("notes"),
            location=fields.get("location"),
            calendar_id=fields.get("calendar_id"),
        )

    n = _CREATE_NATURAL.match(text)
    if not n:
        return None
    title = (n.group(1) or "").strip(" .")
    starts_at = (n.group(2) or "").strip()
    ends_at = (n.group(3) or "").strip()
    location = (n.group(4) or "").strip(" .")
    if not title or not starts_at:
        return None
    return CalendarCreateIntent(
        title=title,
        starts_at=_normalize_iso(starts_at),
        ends_at=_normalize_iso(ends_at) if ends_at else None,
        location=location or None,
    )


def parse_calendar_lookup_intent(message: str) -> CalendarLookupIntent | None:
    """
    Detect free-form lookup intent (date/time of appointments) and extract
    optional month window plus search keywords.
    """
    text = (message or "").strip()
    if not text:
        return None
    lower = text.lower()
    if not any(h in lower for h in _LOOKUP_HINTS):
        return None

    keys = title_keywords(text, max_keywords=8)
    if not keys:
        return None

    month_m = _MONTH_RE.search(text)
    if not month_m:
        return CalendarLookupIntent(keywords=keys)

    month_name = month_m.group(1).lower()
    month = _MONTH_TO_NUM[month_name]
    year_m = _YEAR_RE.search(text)
    year = int(year_m.group(1)) if year_m else datetime.now(UTC).year
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return CalendarLookupIntent(
        keywords=keys,
        month_start_iso=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        month_end_iso=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _normalize_iso(s: str) -> str:
    """
    Keep valid ISO-ish strings as-is when they include timezone; if naive, assume local timezone.
    """
    raw = s.strip()
    if not raw:
        return raw
    if raw.endswith("Z") or "+" in raw[10:] or "-" in raw[10:]:
        return raw
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat()


def title_keywords(title: str, *, max_keywords: int = 5) -> list[str]:
    """Extract simple reusable keywords from an event title."""
    words = re.findall(r"[A-Za-z0-9]+", (title or "").lower())
    stop = {
        "the",
        "a",
        "an",
        "for",
        "to",
        "and",
        "with",
        "at",
        "on",
        "of",
        "get",
        "let",
        "me",
        "my",
        "appointment",
        "appointments",
        "calendar",
        "date",
        "time",
        "when",
        "schedule",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
    out: list[str] = []
    for w in words:
        if len(w) < 3 or w in stop:
            continue
        if w not in out:
            out.append(w)
        if len(out) >= max_keywords:
            break
    return out
