"""M1: ingest, search, chat with deterministic embeddings + fake LLM."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.watcher import NullFileWatcher
from memoryagent.llm_client import FakeLlm
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.rag_service import RagService
from memoryagent.secrets import bearer_token_path
from memoryagent.vector_store import VectorStore


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
        llm=FakeLlm(reply="Your favorite color is teal."),
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


def test_ingest_search_chat(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    r = client.post(
        "/api/v1/memory/entries",
        json={
            "text": "Manual test fact: favorite color is teal for M1.",
            "tags": ["test"],
            "source": "pytest",
        },
        headers=h,
    )
    assert r.status_code == 201
    doc_id = r.json()["document_id"]
    assert len(doc_id) > 0

    r2 = client.get(
        "/api/v1/memory/search",
        params={"q": "favorite color"},
        headers=h,
    )
    assert r2.status_code == 200
    results = r2.json()["results"]
    assert len(results) >= 1
    assert "teal" in results[0]["snippet"].lower()

    r3 = client.post(
        "/api/v1/chat",
        json={
            "messages": [{"role": "user", "content": "What is my favorite color?"}],
        },
        headers=h,
    )
    assert r3.status_code == 200
    body = r3.json()
    assert "teal" in body["reply"].lower()
    assert len(body["citations"]) >= 1
    assert any("teal" in c["snippet"].lower() for c in body["citations"])


def test_chat_stream(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    client.post(
        "/api/v1/memory/entries",
        json={"text": "Stream test: planet is Mars.", "tags": [], "source": "pytest"},
        headers=h,
    )
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"messages": [{"role": "user", "content": "What planet?"}]},
        headers=h,
    ) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
        assert "event: token" in text
        assert "event: done" in text


def test_health_index_counts(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    client.post(
        "/api/v1/memory/entries",
        json={"text": "Health index test.", "tags": [], "source": "pytest"},
        headers=h,
    )
    rh = client.get("/api/v1/health")
    assert rh.status_code == 200
    idx = rh.json()["index"]
    assert idx["documents"] >= 1
    assert idx["chunks"] >= 1
