"""EventKit calendar access via the native `memoryagent-calendar` helper (macOS)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memoryagent.paths import repo_root


class CalendarPermissionDenied(Exception):
    """User or system denied Calendar access (TCC)."""

    def __init__(self, message: str = "Calendar access denied") -> None:
        super().__init__(message)


def _calendar_host_app_hint() -> str:
    """
    TCC is per *host* process. Approving Calendar for Terminal does not apply when the bridge
    runs as a child of Python (uvicorn) or Cursor.
    """
    py = sys.executable
    return (
        "macOS grants Calendar access per app. If you approved it in Terminal but the API still fails, "
        "start the server from standalone Terminal.app (run ./scripts/run.sh there) so the same “Terminal” "
        "trust applies, or enable Calendar for “Python”, “Cursor”, and Full Access for the interpreter: "
        f"{py}. "
        "System Settings → Privacy & Security → Calendars."
    )


def resolve_calendar_bridge_binary() -> Path | None:
    """Return path to `memoryagent-calendar` executable, or None."""
    env = os.environ.get("MEMORYAGENT_CALENDAR_BRIDGE")
    if env:
        p = Path(env).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p.resolve()
    root = repo_root()
    pkg = root / "native-bridge" / "macos-calendar"
    for arch in ("arm64-apple-macosx", "x86_64-apple-macosx"):
        cand = pkg / ".build" / arch / "release" / "memoryagent-calendar"
        if cand.is_file():
            return cand.resolve()
    matches = sorted(pkg.glob(".build/*/release/memoryagent-calendar"), key=lambda x: str(x))
    for p in matches:
        if p.is_file():
            return p.resolve()
    return None


def _require_bridge() -> Path:
    binary = resolve_calendar_bridge_binary()
    if not binary:
        raise ValueError(
            "Calendar bridge is not available. On macOS, build native-bridge/macos-calendar "
            "(swift build -c release) or set MEMORYAGENT_CALENDAR_BRIDGE to the binary path."
        )
    return binary


async def _invoke_bridge(payload: dict[str, Any]) -> dict[str, Any]:
    binary = _require_bridge()
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    proc = await asyncio.create_subprocess_exec(
        str(binary),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(raw)
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[:800]
        raise RuntimeError(f"calendar bridge failed (exit {proc.returncode}): {err}")
    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid JSON from calendar bridge: {e}") from e
    if not data.get("ok"):
        err = data.get("error") or {}
        code = err.get("code")
        msg = str(err.get("message", "calendar error"))
        stderr_text = stderr.decode(errors="replace").strip()
        if code == "PERMISSION_DENIED":
            parts = [msg]
            if stderr_text:
                parts.append(stderr_text)
            parts.append(_calendar_host_app_hint())
            raise CalendarPermissionDenied("\n".join(parts))
        raise ValueError(msg)
    return data


async def run_list_events(args: dict[str, Any]) -> dict[str, Any]:
    """
    Call the native bridge with ``list_events``: ISO-8601 ``start`` and ``end``.
    Returns ``{"events": [...], "count": n}`` on success.
    """
    start = args.get("start")
    end = args.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("start and end are required (ISO-8601 strings)")
    if not start.strip() or not end.strip():
        raise ValueError("start and end must be non-empty")
    data = await _invoke_bridge(
        {
            "action": "list_events",
            "start": start.strip(),
            "end": end.strip(),
        }
    )
    events = data.get("events")
    if not isinstance(events, list):
        events = []
    return {"events": events, "count": len(events)}


async def run_search_past_events(args: dict[str, Any]) -> dict[str, Any]:
    """
    Search past calendar events in a lookback window from ``before``, matching ``keywords``.
    See agent-actions.md §3.4. If ``before`` is omitted, uses current UTC time.
    """
    before = args.get("before")
    if not isinstance(before, str) or not before.strip():
        before = default_before_iso()
    else:
        before = before.strip()
    raw_kw = args.get("keywords")
    if not isinstance(raw_kw, list) or not raw_kw:
        raise ValueError("keywords is required (non-empty array of strings)")
    keywords: list[str] = []
    for x in raw_kw:
        if isinstance(x, str) and x.strip():
            keywords.append(x.strip())
    if not keywords:
        raise ValueError("keywords must contain at least one non-empty string")

    lookback = args.get("lookback_days", 730)
    if not isinstance(lookback, int):
        try:
            lookback = int(lookback)
        except (TypeError, ValueError) as e:
            raise ValueError("lookback_days must be an integer") from e
    lookback = max(1, min(lookback, 3650))

    limit = args.get("limit", 20)
    if not isinstance(limit, int):
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise ValueError("limit must be an integer") from e
    limit = max(1, min(limit, 100))

    data = await _invoke_bridge(
        {
            "action": "search_past_events",
            "before": before.strip(),
            "keywords": keywords,
            "lookback_days": lookback,
            "limit": limit,
        }
    )
    events = data.get("events")
    if not isinstance(events, list):
        events = []
    return {"events": events, "count": len(events)}


def default_before_iso() -> str:
    """UTC ISO-8601 instant for search_past_events default ``before``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def run_create_event(args: dict[str, Any]) -> dict[str, Any]:
    """
    Create a calendar event via EventKit (native bridge). Same fields as agent-actions.md §3.1.
    """
    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    starts_at = args.get("starts_at")
    if not isinstance(starts_at, str) or not starts_at.strip():
        raise ValueError("starts_at is required (ISO-8601)")

    payload: dict[str, Any] = {
        "action": "create_event",
        "title": title.strip(),
        "starts_at": starts_at.strip(),
    }
    ends_at = args.get("ends_at")
    if isinstance(ends_at, str) and ends_at.strip():
        payload["ends_at"] = ends_at.strip()
    if "all_day" in args and args["all_day"] is not None:
        payload["all_day"] = bool(args["all_day"])
    notes = args.get("notes")
    if isinstance(notes, str) and notes:
        payload["notes"] = notes
    loc = args.get("location")
    if isinstance(loc, str) and loc:
        payload["location"] = loc
    cal_id = args.get("calendar_id")
    if isinstance(cal_id, str) and cal_id.strip():
        payload["calendar_id"] = cal_id.strip()

    data = await _invoke_bridge(payload)
    return {
        "event_id": str(data.get("event_id") or ""),
        "title": str(data.get("title") or title.strip()),
        "starts_at": str(data.get("starts_at") or ""),
        "ends_at": str(data.get("ends_at") or ""),
    }
