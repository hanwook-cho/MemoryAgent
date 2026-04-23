"""MP1: Node ``POST /retrieve`` fan-out via retrieval backends (host_edge / hybrid)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.backends import (
    HostEdgeRetrievalBackend,
    HybridRetrievalBackend,
    LocalRagRetrievalBackend,
    build_runtime_backends,
)
from memoryagent.config_store import AppConfig
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.llm_client import FakeLlm
from memoryagent.rag_service import RagService, SearchFilters
from memoryagent.schemas import SearchResultItem
from memoryagent.secrets import bearer_token_path
from memoryagent.vector_store import VectorStore
from memoryagent.watcher import NullFileWatcher


@pytest.fixture()
def client(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_ollama(_: str) -> bool:
        return False

    import memoryagent.app as app_mod

    monkeypatch.setattr(app_mod, "ollama_reachable", fake_ollama)

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="ok"),
    )
    empty = data_dir / "no_web"
    empty.mkdir()
    app = create_app(
        data_dir=data_dir,
        static_dir=empty,
        rag_service=rag,
        file_watcher=NullFileWatcher(),
    )
    return TestClient(app)


def _auth(data_dir: Path) -> dict[str, str]:
    token = bearer_token_path(data_dir).read_text().strip()
    return {"Authorization": f"Bearer {token}"}


async def test_host_edge_retrieval_uses_remote_results(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="x"),
    )
    tok = "test-token"
    be = HostEdgeRetrievalBackend(rag, "http://127.0.0.1:9", tok)

    async def fake_try(
        edge_base_url: str,
        bearer_token: str,
        query: str,
        *,
        limit: int = 20,
        filters: SearchFilters | None = None,
    ) -> list[SearchResultItem] | None:
        _ = edge_base_url, bearer_token, limit, filters
        assert query == "hello-remote"
        return [
            SearchResultItem(
                chunk_id="edge:0",
                snippet="from-edge",
                score=0.99,
                document_id="edge-doc",
            )
        ]

    import memoryagent.backends as backends_mod

    monkeypatch.setattr(backends_mod, "try_node_retrieve", fake_try)
    hits = await be.search("hello-remote", limit=8)
    assert len(hits) == 1
    assert hits[0].snippet == "from-edge"
    assert hits[0].chunk_id == "edge:0"


async def test_host_edge_falls_back_when_remote_returns_none(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="x"),
    )
    await rag.ingest_memory("local-fallback-unique-aa", tags=[], source="pytest")
    be = HostEdgeRetrievalBackend(rag, "http://127.0.0.1:9", "tok")

    async def no_remote(*_a, **_k) -> list[SearchResultItem] | None:
        return None

    import memoryagent.backends as backends_mod

    monkeypatch.setattr(backends_mod, "try_node_retrieve", no_remote)
    hits = await be.search("fallback-unique-aa", limit=8)
    assert any("local-fallback" in h.snippet for h in hits)


async def test_hybrid_merges_local_and_remote(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="x"),
    )
    await rag.ingest_memory("hybrid-local-bb", tags=[], source="pytest")
    be = HybridRetrievalBackend(rag, "http://127.0.0.1:9", "tok")

    async def remote_one(*_a, **_k) -> list[SearchResultItem] | None:
        return [
            SearchResultItem(
                chunk_id="shared-id",
                snippet="remote-win",
                score=0.95,
                document_id="r1",
            ),
            SearchResultItem(
                chunk_id="remote-only",
                snippet="only-remote",
                score=0.5,
                document_id="r2",
            ),
        ]

    import memoryagent.backends as backends_mod

    monkeypatch.setattr(backends_mod, "try_node_retrieve", remote_one)
    hits = await be.search("hybrid-local-bb", limit=10)
    ids = {h.chunk_id for h in hits}
    assert "remote-only" in ids
    shared = next(h for h in hits if h.chunk_id == "shared-id")
    assert shared.snippet == "remote-win"
    assert shared.score == 0.95


def test_memory_search_host_edge_remote_hit(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import memoryagent.app as app_mod

    async def fake_ollama(_: str) -> bool:
        return False

    monkeypatch.setattr(app_mod, "ollama_reachable", fake_ollama)

    async def fake_try(*_a, **_k) -> list[SearchResultItem] | None:
        return [
            SearchResultItem(
                chunk_id="n:1",
                snippet="edge-snippet-xyz",
                score=0.88,
                document_id="ndoc",
            )
        ]

    import memoryagent.backends as backends_mod

    monkeypatch.setattr(backends_mod, "try_node_retrieve", fake_try)

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="ok"),
    )
    empty = data_dir / "no_web_edge"
    empty.mkdir()
    app = create_app(
        data_dir=data_dir,
        static_dir=empty,
        rag_service=rag,
        file_watcher=NullFileWatcher(),
    )
    client = TestClient(app)
    h = _auth(data_dir)
    client.patch(
        "/api/v1/config",
        headers=h,
        json={
            "deployment_mode": "host_edge",
            "edge_base_url": "https://mock-edge.local",
        },
    )
    r = client.get(
        "/api/v1/memory/search",
        headers=h,
        params={"q": "anything"},
    )
    assert r.status_code == 200
    hits = r.json()["results"]
    assert len(hits) == 1
    assert hits[0]["snippet"] == "edge-snippet-xyz"


def test_build_runtime_backends_host_edge_class(data_dir: Path) -> None:
    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="x"),
    )
    cfg = replace(AppConfig(), deployment_mode="host_edge", edge_base_url="http://127.0.0.1:1")
    b = build_runtime_backends(rag, cfg, bearer_token="abc")
    assert isinstance(b.retrieval, HostEdgeRetrievalBackend)


def test_build_runtime_backends_hybrid_class(data_dir: Path) -> None:
    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="x"),
    )
    cfg = replace(AppConfig(), deployment_mode="hybrid", edge_base_url="http://127.0.0.1:1")
    b = build_runtime_backends(rag, cfg, bearer_token="abc")
    assert isinstance(b.retrieval, HybridRetrievalBackend)


def test_build_runtime_backends_standalone_is_local(data_dir: Path) -> None:
    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="x"),
    )
    cfg = replace(
        AppConfig(),
        deployment_mode="standalone",
        edge_base_url="http://127.0.0.1:1",
    )
    b = build_runtime_backends(rag, cfg, bearer_token="abc")
    assert isinstance(b.retrieval, LocalRagRetrievalBackend)
