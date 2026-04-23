"""M5+ foundation: file index DB avoids re-indexing unchanged files."""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryagent.llm_client import FakeLlm
from memoryagent.rag_service import RagService
from memoryagent.vector_store import VectorStore


class CountingEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        # deterministic tiny embedding
        base = float(len(text) % 17) / 17.0
        return [base, 1.0 - base, 0.5]


@pytest.mark.asyncio
async def test_ingest_file_path_skips_unchanged(data_dir: Path) -> None:
    f = data_dir / "skip_test.md"
    f.write_text("M5 index DB test line.\n", encoding="utf-8")

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    emb = CountingEmbedder()
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=emb,  # type: ignore[arg-type]
        llm=FakeLlm(reply="ok"),
    )

    await rag.ingest_file_path(f)
    first_calls = emb.calls
    assert first_calls >= 1

    # unchanged => should skip re-embed
    await rag.ingest_file_path(f)
    assert emb.calls == first_calls


@pytest.mark.asyncio
async def test_ingest_file_path_reindexes_when_changed(data_dir: Path) -> None:
    f = data_dir / "change_test.md"
    f.write_text("Before change.\n", encoding="utf-8")

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    emb = CountingEmbedder()
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=emb,  # type: ignore[arg-type]
        llm=FakeLlm(reply="ok"),
    )

    await rag.ingest_file_path(f)
    first_calls = emb.calls
    f.write_text("After change with extra content.\n", encoding="utf-8")
    await rag.ingest_file_path(f)
    assert emb.calls > first_calls
