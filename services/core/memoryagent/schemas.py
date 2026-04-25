"""Pydantic models for API bodies (docs/spec/http-api.md)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: str | None = None


class Citation(BaseModel):
    chunk_id: str
    snippet: str
    score: float = Field(ge=0.0, le=1.0)


class ChatResponse(BaseModel):
    reply: str
    citations: list[Citation]
    session_id: str


class MemoryEntryRequest(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)
    source: str = "web_ui"


class MemoryEntryResponse(BaseModel):
    document_id: str
    job_id: str


class SearchResultItem(BaseModel):
    chunk_id: str
    snippet: str
    score: float
    document_id: str


class SearchResponse(BaseModel):
    results: list[SearchResultItem]


class ConfigPatchRequest(BaseModel):
    watched_roots: list[str] | None = None
    watch_ignore_globs: list[str] | None = None
    watch_debounce_seconds: float | None = Field(default=None, ge=0.1, le=3600.0)
    deployment_mode: str | None = None
    edge_base_url: str | None = None
    edge_tls_ca_bundle: str | None = None
    edge_tls_insecure_skip_verify: bool | None = None
    edge_ingest_path_host_prefix: str | None = None
    edge_ingest_path_edge_prefix: str | None = None
    edge_tls_spki_pins_sha256: list[str] | None = None
    google_calendar_include: bool | None = None
    google_calendar_oauth_client_id: str | None = None
    google_calendar_oauth_redirect_uri: str | None = None


MirrorId = Literal["user", "soul"]


class MirrorListItem(BaseModel):
    id: MirrorId
    filename: str
    title: str


class MirrorListResponse(BaseModel):
    mirrors: list[MirrorListItem]


class MirrorDocumentResponse(BaseModel):
    mirror_id: MirrorId
    filename: str
    path: str
    content: str
    document_id: str


class MirrorPutRequest(BaseModel):
    content: str


class MirrorPutResponse(BaseModel):
    mirror_id: MirrorId
    document_id: str
    reindexed: bool = True


class ToolInvokeRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolListItem(BaseModel):
    name: str
    description: str
    required_capability: str | None = None


class ToolListResponse(BaseModel):
    tools: list[ToolListItem]


class CalendarEventCreateRequest(BaseModel):
    """POST /calendar/events (agent-actions.md §4.2)."""

    title: str
    starts_at: str
    ends_at: str | None = None
    all_day: bool = False
    location: str | None = None
    notes: str | None = None
    calendar_id: str | None = None
    calendar_target: str | None = None
    google_calendar_id: str | None = None


class CalendarEventCreateResponse(BaseModel):
    event_id: str
    title: str
    starts_at: str
    ends_at: str
    calendar_target: str | None = None
    calendar_id: str | None = None
    html_link: str | None = None


class GoogleCalendarStatusResponse(BaseModel):
    include: bool
    connected: bool
    status: str
    account_hint: str | None = None
    message: str | None = None


class GoogleCalendarConnectResponse(BaseModel):
    authorization_url: str
    state: str
    expires_in_seconds: int
