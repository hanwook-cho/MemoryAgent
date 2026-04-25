"""Registered chat tools (M4): same behaviors as manual HTTP actions where applicable."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from memoryagent.calendar_bridge import (
    CalendarPermissionDenied,
    run_create_event,
    run_list_events,
    run_search_past_events,
)
from memoryagent.config_store import load_config
from memoryagent.file_access import path_is_allowlisted_for_read
from memoryagent.google_calendar import (
    GoogleCalendarApiError,
    create_google_calendar_event,
    list_google_calendar_events,
    search_google_calendar_past_events,
)
from memoryagent.rag_service import RagService

ToolHandler = Callable[[RagService, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    """OS capability from permissions-matrix (e.g. calendars); None = no prompt."""
    required_capability: str | None


# Stable tool names (agent-actions.md §2)
TOOL_MEMORY_SAVE = "memory.save"
TOOL_FILE_READ = "file.read"
TOOL_CALENDAR_LIST_EVENTS = "calendar.list_events"
TOOL_CALENDAR_SEARCH_PAST_EVENTS = "calendar.search_past_events"
TOOL_CALENDAR_CREATE_EVENT = "calendar.create_event"

# Max bytes for file.read (avoid loading huge files into the process)
MAX_FILE_READ_BYTES = 512_000


class ToolRegistry:
    def __init__(self) -> None:
        self._defs: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self._defs[definition.name] = definition
        self._handlers[definition.name] = handler

    def definitions(self) -> list[ToolDefinition]:
        return list(self._defs.values())

    def get(self, name: str) -> tuple[ToolDefinition, ToolHandler] | None:
        if name not in self._defs:
            return None
        return self._defs[name], self._handlers[name]

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        rag: RagService,
        granted_capabilities: set[str] | None = None,
    ) -> dict[str, Any]:
        entry = self.get(name)
        if entry is None:
            raise KeyError(name)
        definition, handler = entry
        cap = definition.required_capability
        if cap is not None:
            granted = granted_capabilities or set()
            if cap not in granted:
                return {
                    "ok": False,
                    "error": {
                        "code": "PERMISSION_DENIED",
                        "message": f'Capability "{cap}" not granted.',
                    },
                }
        try:
            result = await handler(rag, arguments)
        except CalendarPermissionDenied as e:
            return {
                "ok": False,
                "error": {"code": "PERMISSION_DENIED", "message": str(e)},
            }
        except ValueError as e:
            return {
                "ok": False,
                "error": {"code": "VALIDATION", "message": str(e)},
            }
        return {"ok": True, "result": result}


def _make_file_read_handler(data_dir: Path) -> ToolHandler:
    async def _file_read(rag: RagService, args: dict[str, Any]) -> dict[str, Any]:
        _ = rag
        raw = args.get("path") or args.get("file_path")
        if not raw or not isinstance(raw, str):
            raise ValueError("path is required (string)")
        p = Path(raw).expanduser()
        try:
            p = p.resolve()
        except OSError as e:
            raise ValueError(f"invalid path: {e}") from e
        cfg = load_config(data_dir)
        if not path_is_allowlisted_for_read(
            p, data_dir=data_dir, watched_roots=list(cfg.watched_roots)
        ):
            raise ValueError(
                "path not allowed: must be under the app data directory or a configured watched root",
            )
        if not p.is_file():
            raise ValueError("path is not a file or does not exist")
        suf = p.suffix.lower()
        if suf not in (".md", ".txt"):
            raise ValueError("only .md and .txt files are supported")
        size = p.stat().st_size
        if size > MAX_FILE_READ_BYTES:
            raise ValueError(
                f"file too large ({size} bytes; max {MAX_FILE_READ_BYTES})",
            )
        content = p.read_text(encoding="utf-8")
        return {
            "path": str(p),
            "content": content,
            "size_bytes": size,
        }

    return _file_read


def _calendar_sort_key(event: dict[str, Any]) -> str:
    value = event.get("starts_at")
    return value if isinstance(value, str) else ""


def _label_calendar_events(
    events: list[Any],
    *,
    source: str,
    source_label: str,
) -> list[dict[str, Any]]:
    labeled: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        item = dict(event)
        item.setdefault("source", source)
        item.setdefault("source_label", source_label)
        labeled.append(item)
    return labeled


def _make_calendar_list_events_handler(data_dir: Path) -> ToolHandler:
    async def _calendar_list_events(rag: RagService, args: dict[str, Any]) -> dict[str, Any]:
        """List local events, plus Google Calendar when Include is on."""
        _ = rag
        local = await run_list_events(args)
        local_events = _label_calendar_events(
            local.get("events") if isinstance(local, dict) else [],
            source="local",
            source_label="Local Calendar",
        )
        cfg = load_config(data_dir)
        if not cfg.google_calendar_include:
            return {"events": local_events, "count": len(local_events)}

        google_degraded = False
        google_degraded_reason = None
        google_events: list[dict[str, Any]] = []
        try:
            google = await list_google_calendar_events(data_dir, cfg, args)
            google_events = _label_calendar_events(
                google.get("events") if isinstance(google, dict) else [],
                source="google",
                source_label="Google Calendar",
            )
        except GoogleCalendarApiError as e:
            google_degraded = True
            google_degraded_reason = str(e)

        events = sorted([*local_events, *google_events], key=_calendar_sort_key)
        return {
            "events": events,
            "count": len(events),
            "sources": {
                "local": {"count": len(local_events), "degraded": False},
                "google": {
                    "count": len(google_events),
                    "degraded": google_degraded,
                    "degraded_reason": google_degraded_reason,
                },
            },
        }

    return _calendar_list_events


def _make_calendar_search_past_events_handler(data_dir: Path) -> ToolHandler:
    async def _calendar_search_past_events(
        rag: RagService, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Search local past events, plus Google Calendar when Include is on."""
        _ = rag
        local = await run_search_past_events(args)
        local_events = _label_calendar_events(
            local.get("events") if isinstance(local, dict) else [],
            source="local",
            source_label="Local Calendar",
        )
        cfg = load_config(data_dir)
        if not cfg.google_calendar_include:
            return {"events": local_events, "count": len(local_events)}

        google_degraded = False
        google_degraded_reason = None
        google_events: list[dict[str, Any]] = []
        try:
            google = await search_google_calendar_past_events(data_dir, cfg, args)
            google_events = _label_calendar_events(
                google.get("events") if isinstance(google, dict) else [],
                source="google",
                source_label="Google Calendar",
            )
        except GoogleCalendarApiError as e:
            google_degraded = True
            google_degraded_reason = str(e)

        events = sorted([*local_events, *google_events], key=_calendar_sort_key, reverse=True)
        return {
            "events": events,
            "count": len(events),
            "sources": {
                "local": {"count": len(local_events), "degraded": False},
                "google": {
                    "count": len(google_events),
                    "degraded": google_degraded,
                    "degraded_reason": google_degraded_reason,
                },
            },
        }

    return _calendar_search_past_events


def _calendar_target(args: dict[str, Any]) -> str | None:
    raw = args.get("calendar_target") or args.get("target_calendar") or args.get("provider")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("calendar_target must be 'local' or 'google'")
    target = raw.strip().lower()
    if target not in {"local", "google"}:
        raise ValueError("calendar_target must be 'local' or 'google'")
    return target


def _make_calendar_create_event_handler(data_dir: Path) -> ToolHandler:
    async def _calendar_create_event(rag: RagService, args: dict[str, Any]) -> dict[str, Any]:
        """Create a Calendar event via local EventKit or Google Calendar."""
        _ = rag
        cfg = load_config(data_dir)
        target = _calendar_target(args)
        if cfg.google_calendar_include and target is None:
            raise ValueError(
                "calendar_target is required when Google Calendar is included; "
                "use 'local' or 'google'"
            )
        if target == "google":
            if not cfg.google_calendar_include:
                raise ValueError("Google Calendar is not included; choose local or connect Google")
            try:
                return await create_google_calendar_event(data_dir, cfg, args)
            except GoogleCalendarApiError as e:
                raise ValueError(str(e)) from e
        out = await run_create_event(args)
        out["calendar_target"] = "local"
        return out

    return _calendar_create_event


async def _memory_save(rag: RagService, args: dict[str, Any]) -> dict[str, Any]:
    """Ingest like POST /memory/entries (agent-actions.md §2)."""
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    raw_tags = args.get("tags")
    tags: list[str] = list(raw_tags) if isinstance(raw_tags, list) else []
    source = str(args.get("source") or "chat").strip() or "chat"
    document_id, job_id = await rag.ingest_memory(text, tags=tags, source=source)
    return {
        "document_id": document_id,
        "job_id": job_id,
        "saved": True,
    }


def build_default_registry(data_dir: Path) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name=TOOL_MEMORY_SAVE,
            description="Save text to long-term memory (same pipeline as manual memory entry).",
            required_capability=None,
        ),
        _memory_save,
    )
    reg.register(
        ToolDefinition(
            name=TOOL_FILE_READ,
            description=(
                "Read UTF-8 text from a .md or .txt file under the data directory "
                "or a configured watched root."
            ),
            required_capability=None,
        ),
        _make_file_read_handler(data_dir),
    )
    reg.register(
        ToolDefinition(
            name=TOOL_CALENDAR_LIST_EVENTS,
            description=(
                "List macOS Calendar events between two ISO-8601 instants (requires Calendars "
                "permission; native bridge on macOS only)."
            ),
            required_capability=None,
        ),
        _make_calendar_list_events_handler(data_dir),
    )
    reg.register(
        ToolDefinition(
            name=TOOL_CALENDAR_SEARCH_PAST_EVENTS,
            description=(
                "Search past macOS Calendar events before a reference time, filtered by keywords "
                "(title/notes/location), for reuse e.g. dentist location. Optional: before, "
                "lookback_days (default 730), limit (default 20)."
            ),
            required_capability=None,
        ),
        _make_calendar_search_past_events_handler(data_dir),
    )
    reg.register(
        ToolDefinition(
            name=TOOL_CALENDAR_CREATE_EVENT,
            description=(
                "Create a macOS Calendar event (title, starts_at, optional ends_at, all_day, "
                "notes, location, calendar_id). Requires Calendars permission."
            ),
            required_capability=None,
        ),
        _make_calendar_create_event_handler(data_dir),
    )
    return reg
