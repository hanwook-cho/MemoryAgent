"""M4 (slice 1): tool registry + memory.save via POST /tools/invoke."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.llm_client import FakeLlm
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.rag_service import RagService
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


def test_list_tools_includes_memory_save(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    r = client.get("/api/v1/tools", headers=h)
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["tools"]}
    assert "memory.save" in names
    mem = next(t for t in r.json()["tools"] if t["name"] == "memory.save")
    assert mem["required_capability"] is None


def test_invoke_memory_save_same_pipeline_as_post_memory(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    secret = "m4-tool-save-unique-882211"
    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={
            "tool": "memory.save",
            "arguments": {
                "text": secret,
                "tags": ["m4"],
                "source": "chat",
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["saved"] is True
    assert len(body["result"]["document_id"]) > 0

    r2 = client.get(
        "/api/v1/memory/search",
        params={"q": "882211"},
        headers=h,
    )
    assert r2.status_code == 200
    assert any(secret in x["snippet"] for x in r2.json()["results"])


def test_invoke_unknown_tool(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={"tool": "nope.not_registered", "arguments": {}},
    )
    assert r.status_code == 404


def test_invoke_memory_save_empty_text(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={"tool": "memory.save", "arguments": {"text": "   "}},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "VALIDATION"
