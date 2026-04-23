"""Ingest, retrieve, and chat over the vector store."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
import asyncio

if TYPE_CHECKING:
    from memoryagent.backends import RetrievalBackend

from memoryagent.calendar_bridge import (
    CalendarPermissionDenied,
    run_create_event,
    run_list_events,
    run_search_past_events,
)
from memoryagent.calendar_intent import (
    parse_calendar_create_intent,
    parse_calendar_lookup_intent,
    title_keywords,
)
from memoryagent.chunking import chunk_text
from memoryagent.document_extractors import extract_text_from_path
from memoryagent.embeddings import Embedder
from memoryagent.file_index_db import FileIndexDB, PARSER_VERSION
from memoryagent.memory_intent import extract_memory_save_text
from memoryagent.mirror import parse_mirror_file
from memoryagent.llm_client import LlmClient
from memoryagent.schemas import ChatMessage, ChatResponse, Citation, SearchResultItem
from memoryagent.vector_store import VectorStore

logger = logging.getLogger(__name__)


class RagService:
    def __init__(
        self,
        *,
        data_dir: Path,
        store: VectorStore,
        embedder: Embedder,
        llm: LlmClient,
        extract_timeout_seconds: float = 8.0,
    ) -> None:
        self._data_dir = data_dir
        self._store = store
        self._embedder = embedder
        self._llm = llm
        self._extract_timeout_seconds = extract_timeout_seconds
        self._stats_path = data_dir / "store" / "ingest_stats.json"
        self._file_index = FileIndexDB(data_dir / "store" / "file_index.db")
        self._retrieval_for_chat: RetrievalBackend | None = None

    def bind_retrieval_for_chat(self, backend: "RetrievalBackend") -> None:
        """MP1: use the same ``RetrievalBackend`` as HTTP ``/memory/search`` for RAG chat retrieval."""
        self._retrieval_for_chat = backend

    @property
    def llm_client(self) -> LlmClient:
        """Injectable LLM (MP1 ``LlmBackend`` / local adapter wiring)."""
        return self._llm

    def _load_stats(self) -> dict[str, Any]:
        default: dict[str, Any] = {"memory_documents": 0, "indexed_file_uris": []}
        if not self._stats_path.is_file():
            return default
        try:
            data = json.loads(self._stats_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError):
            return default
        if "memory_documents" in data:
            uris = data.get("indexed_file_uris", [])
            return {
                "memory_documents": int(data.get("memory_documents", 0)),
                "indexed_file_uris": list(uris) if isinstance(uris, list) else [],
            }
        # Migrate legacy { "documents": N }
        old = int(data.get("documents", 0))
        return {"memory_documents": old, "indexed_file_uris": []}

    def _save_stats(self, stats: dict[str, Any]) -> None:
        self._stats_path.parent.mkdir(parents=True, exist_ok=True)
        self._stats_path.write_text(
            json.dumps(stats, indent=2) + "\n",
            encoding="utf-8",
        )

    def _bump_memory_documents(self, n: int = 1) -> None:
        s = self._load_stats()
        s["memory_documents"] = int(s["memory_documents"]) + n
        self._save_stats(s)

    def _ensure_file_uri(self, uri: str) -> None:
        s = self._load_stats()
        uris: list[str] = list(s.get("indexed_file_uris", []))
        if uri not in uris:
            uris.append(uri)
            s["indexed_file_uris"] = uris
            self._save_stats(s)

    def index_stats(self) -> dict[str, int]:
        s = self._load_stats()
        mem = int(s.get("memory_documents", 0))
        files = len(s.get("indexed_file_uris", []))
        return {
            "documents": mem + files,
            "memory_documents": mem,
            "indexed_files": files,
            "chunks": self._store.count(),
        }

    def reset_search_index(self) -> None:
        """Clear vector chunks, file index rows, and ingest counters (admin ``reset-index``)."""
        self._store.clear_all()
        self._file_index.clear_all()
        self._save_stats({"memory_documents": 0, "indexed_file_uris": []})

    async def ingest_memory(
        self,
        text: str,
        *,
        tags: list[str],
        source: str,
    ) -> tuple[str, str]:
        document_id = str(uuid.uuid4())
        chunks = chunk_text(text)
        if not chunks:
            return document_id, document_id

        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        now_iso = datetime.now().astimezone().isoformat()
        for i, chunk in enumerate(chunks):
            cid = f"{document_id}:{i}"
            emb = await self._embedder.embed(chunk)
            ids.append(cid)
            embeddings.append(emb)
            documents.append(chunk)
            metadatas.append(
                {
                    "document_id": document_id,
                    "chunk_index": i,
                    "source": source,
                    "tags": ",".join(tags),
                    "source_kind": "memory",
                    "indexed_at": now_iso,
                }
            )

        self._store.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        self._bump_memory_documents(1)
        return document_id, document_id

    async def ingest_file_path(self, path: Path) -> str:
        """Extract text from supported file, replace prior chunks, embed, upsert."""
        p = path.expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(str(p))
        try:
            text, source_kind = await asyncio.wait_for(
                asyncio.to_thread(extract_text_from_path, p),
                timeout=self._extract_timeout_seconds,
            )
        except TimeoutError as e:
            logger.error(
                "extract_failed reason=timeout path=%s timeout_seconds=%.2f",
                str(p),
                self._extract_timeout_seconds,
            )
            raise ValueError(
                f"extraction timed out after {self._extract_timeout_seconds:.2f}s"
            ) from e
        except Exception:
            logger.exception("extract_failed reason=error path=%s", str(p))
            raise
        uri = p.as_uri()
        document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, uri))
        st = p.stat()
        if not self._file_index.should_reindex(
            uri=uri,
            size_bytes=int(st.st_size),
            mtime_ns=int(st.st_mtime_ns),
            parser_version=PARSER_VERSION,
        ):
            # Unchanged file: skip parse/embed/upsert.
            self._ensure_file_uri(uri)
            return document_id

        self._store.delete_by_document_id(document_id)
        chunks = chunk_text(text)
        if not chunks:
            self._ensure_file_uri(uri)
            self._file_index.upsert(
                uri=uri,
                path=str(p),
                document_id=document_id,
                size_bytes=int(st.st_size),
                mtime_ns=int(st.st_mtime_ns),
                parser_version=PARSER_VERSION,
                source_kind=source_kind,
                indexed_at=datetime.now().astimezone().isoformat(),
            )
            return document_id

        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        indexed_at = datetime.now().astimezone().isoformat()
        for i, chunk in enumerate(chunks):
            cid = f"{document_id}:{i}"
            emb = await self._embedder.embed(chunk)
            ids.append(cid)
            embeddings.append(emb)
            documents.append(chunk)
            metadatas.append(
                {
                    "document_id": document_id,
                    "chunk_index": i,
                    "source": uri,
                    "tags": "",
                    "source_kind": source_kind,
                    "indexed_at": indexed_at,
                }
            )

        self._store.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        self._ensure_file_uri(uri)
        self._file_index.upsert(
            uri=uri,
            path=str(p),
            document_id=document_id,
            size_bytes=int(st.st_size),
            mtime_ns=int(st.st_mtime_ns),
            parser_version=PARSER_VERSION,
            source_kind=source_kind,
            indexed_at=indexed_at,
        )
        return document_id

    async def ingest_mirror_document(self, path: Path, *, mirror_key: str) -> str:
        """Index only the Markdown body (below front matter); metadata marks `mirror` source."""
        p = path.expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(str(p))
        text = p.read_text(encoding="utf-8")
        try:
            _fm, body = parse_mirror_file(text)
        except ValueError:
            raise
        uri = p.as_uri()
        document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, uri))
        self._store.delete_by_document_id(document_id)
        chunks = chunk_text(body)
        if not chunks:
            self._ensure_file_uri(uri)
            return document_id

        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for i, chunk in enumerate(chunks):
            cid = f"{document_id}:{i}"
            emb = await self._embedder.embed(chunk)
            ids.append(cid)
            embeddings.append(emb)
            documents.append(chunk)
            metadatas.append(
                {
                    "document_id": document_id,
                    "chunk_index": i,
                    "source": uri,
                    "tags": "",
                    "source_kind": "mirror",
                    "mirror_key": mirror_key,
                }
            )

        self._store.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        self._ensure_file_uri(uri)
        return document_id

    async def search(
        self, query: str, *, limit: int = 20, filters: SearchFilters | None = None
    ) -> list[SearchResultItem]:
        if self._store.count() == 0:
            return []
        filters = filters or SearchFilters()
        qemb = await self._embedder.embed(query)
        where: dict[str, Any] | None = None
        if filters.source_kind:
            where = {"source_kind": {"$eq": filters.source_kind}}
        raw = self._store.query_with_filters(
            qemb,
            n_results=min(limit * 4, max(1, self._store.count())),
            where=where,
        )
        out: list[SearchResultItem] = []
        for row in raw:
            meta = row.get("metadata") or {}
            if not _meta_matches_filters(meta, filters):
                continue
            doc_id = str(meta.get("document_id", ""))
            snippet = (row.get("document") or "")[:500]
            out.append(
                SearchResultItem(
                    chunk_id=str(row.get("chunk_id", "")),
                    snippet=snippet,
                    score=float(row.get("score", 0.0)),
                    document_id=doc_id,
                )
            )
            if len(out) >= limit:
                break
        return out

    async def _retrieve_for_chat(
        self, messages: list[ChatMessage]
    ) -> tuple[list[SearchResultItem], list[str], list[Citation]]:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )
        filters = _filters_from_query_text(last_user)
        if self._retrieval_for_chat is not None:
            hits = await self._retrieval_for_chat.search(
                last_user, limit=8, filters=filters
            )
        else:
            hits = await self.search(last_user, limit=8, filters=filters)
        context_blocks = [h.snippet for h in hits if h.snippet]
        citations = [
            Citation(chunk_id=h.chunk_id, snippet=h.snippet, score=h.score)
            for h in hits
        ]
        return hits, context_blocks, citations

    async def chat(self, messages: list[ChatMessage]) -> ChatResponse:
        if not messages:
            raise ValueError("messages required")
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )
        save_text = extract_memory_save_text(last_user)
        if save_text:
            await self.ingest_memory(save_text, tags=[], source="chat")
            reply = await self._llm.chat(
                [
                    ChatMessage(
                        role="user",
                        content=(
                            f"The user saved this to long-term memory: {save_text}\n"
                            "Respond in one or two short sentences confirming you will remember it "
                            "for future questions."
                        ),
                    )
                ],
                context_blocks=[],
            )
            return ChatResponse(
                reply=reply,
                citations=[],
                session_id=str(uuid.uuid4()),
            )
        capabilities_reply = self._try_capabilities_from_chat(last_user)
        if capabilities_reply is not None:
            return ChatResponse(
                reply=capabilities_reply,
                citations=[],
                session_id=str(uuid.uuid4()),
            )
        calendar_reply = await self._try_calendar_create_from_chat(last_user)
        if calendar_reply is not None:
            return ChatResponse(
                reply=calendar_reply,
                citations=[],
                session_id=str(uuid.uuid4()),
            )
        lookup_reply = await self._try_calendar_lookup_from_chat(last_user)
        if lookup_reply is not None:
            return ChatResponse(
                reply=lookup_reply,
                citations=[],
                session_id=str(uuid.uuid4()),
            )
        _hits, context_blocks, citations = await self._retrieve_for_chat(messages)
        reply = await self._llm.chat(messages, context_blocks=context_blocks)
        session_id = str(uuid.uuid4())
        return ChatResponse(
            reply=reply,
            citations=citations[:5],
            session_id=session_id,
        )

    async def chat_stream_sse(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Server-Sent Events lines (http-api §3.3)."""
        if not messages:
            raise ValueError("messages required")
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )
        save_text = extract_memory_save_text(last_user)
        if save_text:
            await self.ingest_memory(save_text, tags=[], source="chat")
            reply = await self._llm.chat(
                [
                    ChatMessage(
                        role="user",
                        content=(
                            f"The user saved this to long-term memory: {save_text}\n"
                            "Respond in one or two short sentences confirming you will remember it "
                            "for future questions."
                        ),
                    )
                ],
                context_blocks=[],
            )
            session_id = str(uuid.uuid4())
            for word in reply.split():
                yield f"event: token\ndata: {json.dumps({'text': word + ' '})}\n\n"
            yield f"event: citation\ndata: {json.dumps({'citations': []})}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': session_id})}\n\n"
            return
        capabilities_reply = self._try_capabilities_from_chat(last_user)
        if capabilities_reply is not None:
            session_id = str(uuid.uuid4())
            for word in capabilities_reply.split():
                yield f"event: token\ndata: {json.dumps({'text': word + ' '})}\n\n"
            yield f"event: citation\ndata: {json.dumps({'citations': []})}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': session_id})}\n\n"
            return
        calendar_reply = await self._try_calendar_create_from_chat(last_user)
        if calendar_reply is not None:
            session_id = str(uuid.uuid4())
            for word in calendar_reply.split():
                yield f"event: token\ndata: {json.dumps({'text': word + ' '})}\n\n"
            yield f"event: citation\ndata: {json.dumps({'citations': []})}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': session_id})}\n\n"
            return
        lookup_reply = await self._try_calendar_lookup_from_chat(last_user)
        if lookup_reply is not None:
            session_id = str(uuid.uuid4())
            for word in lookup_reply.split():
                yield f"event: token\ndata: {json.dumps({'text': word + ' '})}\n\n"
            yield f"event: citation\ndata: {json.dumps({'citations': []})}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': session_id})}\n\n"
            return
        _hits, context_blocks, citations = await self._retrieve_for_chat(messages)
        reply = await self._llm.chat(messages, context_blocks=context_blocks)
        session_id = str(uuid.uuid4())
        for word in reply.split():
            yield f"event: token\ndata: {json.dumps({'text': word + ' '})}\n\n"
        yield (
            "event: citation\n"
            f"data: {json.dumps({'citations': [c.model_dump() for c in citations[:5]]})}\n\n"
        )
        yield f"event: done\ndata: {json.dumps({'session_id': session_id})}\n\n"

    async def _try_calendar_create_from_chat(self, last_user: str) -> str | None:
        """
        Structured chat path for calendar event creation.
        Format:
          create calendar event: title=...; starts_at=...; ends_at=...; location=...
        """
        intent = parse_calendar_create_intent(last_user)
        if intent is None:
            return None

        payload: dict[str, Any] = {
            "title": intent.title,
            "starts_at": intent.starts_at,
            "all_day": intent.all_day,
        }
        if intent.ends_at:
            payload["ends_at"] = intent.ends_at
        if intent.notes:
            payload["notes"] = intent.notes
        if intent.calendar_id:
            payload["calendar_id"] = intent.calendar_id

        location = intent.location
        if not location:
            kws = title_keywords(intent.title)
            if kws:
                try:
                    past = await run_search_past_events({"keywords": kws})
                except (CalendarPermissionDenied, ValueError):
                    past = {"events": []}
                events = past.get("events", []) if isinstance(past, dict) else []
                for ev in events if isinstance(events, list) else []:
                    loc = str((ev or {}).get("location", "")).strip()
                    if loc:
                        location = loc
                        break

        if location:
            payload["location"] = location
        else:
            return (
                "I can create that event, but I could not find a previous location. "
                "Please provide the clinic or address (e.g. location=...)."
            )

        try:
            created = await run_create_event(payload)
        except CalendarPermissionDenied:
            return (
                "I could not access Calendar due to permissions. "
                "Enable Calendar access for the app running the API server, then try again."
            )
        except ValueError as e:
            return f"I could not create the event: {e}"

        title = str(created.get("title") or payload["title"])
        starts = str(created.get("starts_at") or payload["starts_at"])
        ends = str(created.get("ends_at") or payload.get("ends_at") or "")
        loc = str(payload.get("location") or "")
        loc_txt = f" at {loc}" if loc else ""
        return f"Created calendar event '{title}' from {starts} to {ends}{loc_txt}."

    async def _try_calendar_lookup_from_chat(self, last_user: str) -> str | None:
        """
        Free-form calendar lookup path for questions like:
        'what date/time is my Takashi Dental appointment in June?'
        """
        intent = parse_calendar_lookup_intent(last_user)
        if intent is None:
            return None

        try:
            if intent.month_start_iso and intent.month_end_iso:
                data = await run_list_events(
                    {"start": intent.month_start_iso, "end": intent.month_end_iso}
                )
                events = data.get("events", []) if isinstance(data, dict) else []
            else:
                data = await run_search_past_events({"keywords": intent.keywords})
                events = data.get("events", []) if isinstance(data, dict) else []
        except CalendarPermissionDenied:
            return (
                "I could not access Calendar due to permissions. "
                "Enable Calendar access for the app running the API server, then try again."
            )
        except ValueError as e:
            return f"I could not search calendar events: {e}"

        kws = [k.lower() for k in intent.keywords]
        matched: list[dict[str, Any]] = []
        for ev in events if isinstance(events, list) else []:
            title = str((ev or {}).get("title", ""))
            notes = str((ev or {}).get("notes", ""))
            location = str((ev or {}).get("location", ""))
            hay = f"{title}\n{notes}\n{location}".lower()
            if any(re.search(rf"\b{re.escape(k)}\b", hay) for k in kws):
                matched.append(ev)

        if not matched:
            if intent.month_start_iso and intent.month_end_iso:
                return "I could not find matching appointments in that month."
            return "I could not find matching appointments in calendar history."

        top = matched[:3]
        lines = []
        for ev in top:
            title = str(ev.get("title", "")).strip() or "(untitled)"
            starts_raw = str(ev.get("starts_at", "")).strip()
            ends_raw = str(ev.get("ends_at", "")).strip()
            all_day = bool(ev.get("all_day", False))
            if all_day:
                starts = _format_local_datetime(starts_raw)
                lines.append(f"- {title}: all-day on {starts.split(', ', 1)[1] if ', ' in starts else starts}")
            else:
                starts = _format_local_datetime(starts_raw)
                ends = _format_local_datetime(ends_raw)
                lines.append(f"- {title}: {starts} to {ends}")
        return "I found these matching appointments:\n" + "\n".join(lines)

    def _try_capabilities_from_chat(self, last_user: str) -> str | None:
        text = (last_user or "").strip().lower()
        if not text:
            return None
        if text in {
            "what can you do",
            "what can you do?",
            "what can you do for me",
            "what can you do for me?",
            "help",
            "help me",
        } or ("what can you do" in text and "for me" in text):
            return (
                "I am MemoryAgent for this app. I can:\n"
                "- Save facts to long-term memory from chat (e.g., 'remember that ...').\n"
                "- Answer using your saved memories with source snippets.\n"
                "- Read allowed local .md/.txt files via tools.\n"
                "- List/search your Calendar events and create events.\n"
                "- Reuse past appointment locations when scheduling similar events.\n\n"
                "Helpful example prompts:\n"
                "- 'Remember that my dentist is Takashi Dental.'\n"
                "- 'What did I save about benchmark scripts?'\n"
                "- 'Show my Takashi Dental appointments in June.'\n"
                "- 'Create calendar event: title=Dentist checkup; starts_at=2026-07-01T14:00:00Z'\n\n"
                "Tell me one action now (save, search memory, check calendar, or create event)."
            )
        return None


def _format_local_datetime(iso: str) -> str:
    """
    Render ISO instant in local timezone as: HH:MM, MM:DD:YYYY
    """
    raw = (iso or "").strip()
    if not raw:
        return raw
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        dt_local = dt.astimezone()
        return dt_local.strftime("%H:%M, %m:%d:%Y")
    except ValueError:
        return raw


@dataclass(slots=True)
class SearchFilters:
    source_kind: str | None = None
    path_prefix: str | None = None
    indexed_after: datetime | None = None
    indexed_before: datetime | None = None


def _meta_matches_filters(meta: dict[str, Any], filters: SearchFilters) -> bool:
    if filters.path_prefix:
        source = str(meta.get("source", ""))
        if not source.startswith(filters.path_prefix):
            return False
    if filters.indexed_after or filters.indexed_before:
        raw = str(meta.get("indexed_at", "")).strip()
        if not raw:
            return False
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        if filters.indexed_after and dt < filters.indexed_after:
            return False
        if filters.indexed_before and dt > filters.indexed_before:
            return False
    return True


def _filters_from_query_text(text: str) -> SearchFilters:
    q = (text or "").lower()
    now = datetime.now().astimezone()
    filters = SearchFilters()
    if "pdf" in q:
        filters.source_kind = "file_pdf"
    elif "docx" in q or "word document" in q or "word file" in q:
        filters.source_kind = "file_docx"
    elif "markdown" in q or ".md" in q:
        filters.source_kind = "file"

    if "last month" in q:
        first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_prev_month = first_this_month - timedelta(microseconds=1)
        first_prev_month = last_prev_month.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        filters.indexed_after = first_prev_month
        filters.indexed_before = last_prev_month
    return filters
