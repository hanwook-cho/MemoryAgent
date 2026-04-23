"""MP1 backend contracts: local delegates wrap ``RagService`` / ``LlmClient`` (PR-1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from memoryagent.llm_client import LlmClient
from memoryagent.rag_service import RagService, SearchFilters
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


def build_local_backends(rag: RagService) -> RuntimeBackends:
    """PR-1: standalone wiring — all adapters delegate to the existing ``RagService``."""
    return RuntimeBackends(
        retrieval=LocalRagRetrievalBackend(rag),
        ingest=LocalRagIngestBackend(rag),
        llm=LocalLlmBackendAdapter(rag.llm_client),
    )
