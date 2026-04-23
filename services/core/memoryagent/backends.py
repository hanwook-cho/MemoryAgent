"""MP1 backend contracts: local delegates wrap ``RagService`` / ``LlmClient`` (PR-1)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from memoryagent.config_store import AppConfig
from memoryagent.llm_client import LlmClient
from memoryagent.rag_service import RagService, SearchFilters
from memoryagent.remote_retrieval import try_node_retrieve
from memoryagent.schemas import ChatMessage, SearchResultItem


@runtime_checkable
class RetrievalBackend(Protocol):
    """Read/search and index stats (orchestrator-facing, MP1)."""

    def index_stats(self) -> dict[str, int]: ...

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: SearchFilters | None = None,
    ) -> list[SearchResultItem]: ...


@runtime_checkable
class IngestBackend(Protocol):
    """Ingest paths used by the HTTP API and watcher (MP1)."""

    async def ingest_memory(
        self, text: str, *, tags: list[str], source: str
    ) -> tuple[str, str]: ...

    async def ingest_file_path(self, path: Path) -> str: ...

    async def ingest_mirror_document(
        self, path: Path, *, mirror_key: str
    ) -> str: ...


# LLM surface matches existing injectable client (see ``llm_client.LlmClient``).
LlmBackend = LlmClient


@dataclass(frozen=True, slots=True)
class RuntimeBackends:
    """Concrete backends for the current process (PR-1: all local)."""

    retrieval: RetrievalBackend
    ingest: IngestBackend
    llm: LlmBackend


class LocalRagRetrievalBackend:
    __slots__ = ("_rag",)

    def __init__(self, rag: RagService) -> None:
        self._rag = rag

    def index_stats(self) -> dict[str, int]:
        return self._rag.index_stats()

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: SearchFilters | None = None,
    ) -> list[SearchResultItem]:
        return await self._rag.search(query, limit=limit, filters=filters)


class HostEdgeRetrievalBackend:
    """``host_edge``: Node ``POST /retrieve`` first, then local Chroma on failure or empty error path."""

    __slots__ = ("_rag", "_edge_base_url", "_bearer_token")

    def __init__(self, rag: RagService, edge_base_url: str, bearer_token: str) -> None:
        self._rag = rag
        self._edge_base_url = edge_base_url.rstrip("/")
        self._bearer_token = bearer_token

    def index_stats(self) -> dict[str, int]:
        return self._rag.index_stats()

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: SearchFilters | None = None,
    ) -> list[SearchResultItem]:
        remote = await try_node_retrieve(
            self._edge_base_url,
            self._bearer_token,
            query,
            limit=limit,
            filters=filters,
        )
        if remote is not None:
            return remote
        return await self._rag.search(query, limit=limit, filters=filters)


def _merge_search_results(
    a: list[SearchResultItem],
    b: list[SearchResultItem],
    *,
    limit: int,
) -> list[SearchResultItem]:
    best: dict[str, SearchResultItem] = {}
    for h in a + b:
        prev = best.get(h.chunk_id)
        if prev is None or h.score > prev.score:
            best[h.chunk_id] = h
    merged = sorted(best.values(), key=lambda x: x.score, reverse=True)
    return merged[:limit]


class HybridRetrievalBackend:
    """``hybrid``: local + remote ``POST /retrieve``, merge by best score per ``chunk_id``."""

    __slots__ = ("_rag", "_edge_base_url", "_bearer_token")

    def __init__(self, rag: RagService, edge_base_url: str, bearer_token: str) -> None:
        self._rag = rag
        self._edge_base_url = edge_base_url.rstrip("/")
        self._bearer_token = bearer_token

    def index_stats(self) -> dict[str, int]:
        return self._rag.index_stats()

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: SearchFilters | None = None,
    ) -> list[SearchResultItem]:
        loc_task = asyncio.create_task(
            self._rag.search(query, limit=limit, filters=filters)
        )

        async def _remote() -> list[SearchResultItem]:
            r = await try_node_retrieve(
                self._edge_base_url,
                self._bearer_token,
                query,
                limit=limit,
                filters=filters,
            )
            return r or []

        rem_task = asyncio.create_task(_remote())
        local_hits, remote_hits = await asyncio.gather(loc_task, rem_task)
        return _merge_search_results(local_hits, remote_hits, limit=limit)


class LocalRagIngestBackend:
    __slots__ = ("_rag",)

    def __init__(self, rag: RagService) -> None:
        self._rag = rag

    async def ingest_memory(
        self, text: str, *, tags: list[str], source: str
    ) -> tuple[str, str]:
        return await self._rag.ingest_memory(text, tags=tags, source=source)

    async def ingest_file_path(self, path: Path) -> str:
        return await self._rag.ingest_file_path(path)

    async def ingest_mirror_document(self, path: Path, *, mirror_key: str) -> str:
        return await self._rag.ingest_mirror_document(path, mirror_key=mirror_key)


class LocalLlmBackendAdapter:
    """Thin delegate so call sites can depend on ``LlmBackend`` without touching ``RagService``."""

    __slots__ = ("_llm",)

    def __init__(self, llm: LlmClient) -> None:
        self._llm = llm

    async def chat(
        self, messages: list[ChatMessage], *, context_blocks: list[str]
    ) -> str:
        return await self._llm.chat(messages, context_blocks=context_blocks)


def build_runtime_backends(
    rag: RagService,
    cfg: AppConfig,
    *,
    bearer_token: str,
) -> RuntimeBackends:
    """
    Wire retrieval: local only, ``host_edge`` (remote-first), or ``hybrid`` (fan-out + merge)
    when ``edge_base_url`` is set.
    """
    local_retrieval: RetrievalBackend = LocalRagRetrievalBackend(rag)
    edge = (cfg.edge_base_url or "").strip()
    mode = cfg.deployment_mode
    if edge and mode == "host_edge":
        retrieval: RetrievalBackend = HostEdgeRetrievalBackend(rag, edge, bearer_token)
    elif edge and mode == "hybrid":
        retrieval = HybridRetrievalBackend(rag, edge, bearer_token)
    elif edge and mode in ("ios_companion",):
        retrieval = HostEdgeRetrievalBackend(rag, edge, bearer_token)
    else:
        retrieval = local_retrieval

    return RuntimeBackends(
        retrieval=retrieval,
        ingest=LocalRagIngestBackend(rag),
        llm=LocalLlmBackendAdapter(rag.llm_client),
    )


def build_local_backends(rag: RagService) -> RuntimeBackends:
    """Backward-compatible: ``standalone`` + no edge URL (same as PR-1 tests)."""
    return build_runtime_backends(rag, AppConfig(), bearer_token="")
