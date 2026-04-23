"""MP1 Phase 3: edge_base_url, admin routes, chat meta.degraded (see prd-full-product Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.llm_client import FakeLlm
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


def test_admin_status_requires_auth(client: TestClient) -> None:
    r = client.get("/api/v1/admin/status")
    assert r.status_code == 401


def test_admin_status_ok(client: TestClient, data_dir: Path) -> None:
    r = client.get("/api/v1/admin/status", headers=_auth(data_dir))
    assert r.status_code == 200
    body = r.json()
    assert "deployment" in body
    assert body["deployment"]["mode"] == "standalone"
    assert "index" in body and "llm" in body


def test_admin_factory_reset_not_implemented(client: TestClient, data_dir: Path) -> None:
    r = client.post(
        "/api/v1/admin/control/factory-reset",
        headers=_auth(data_dir),
    )
    assert r.status_code == 501
    assert r.json()["detail"]["error"]["code"] == "UNAVAILABLE"


def test_post_chat_includes_meta_standalone(client: TestClient, data_dir: Path) -> None:
    r = client.post(
        "/api/v1/chat",
        headers=_auth(data_dir),
        json={"messages": [{"role": "user", "content": "Say hello in one word."}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert "meta" in body
    assert body["meta"]["degraded"] is False
    assert body["meta"].get("degraded_reason") in (None, "")


def test_post_chat_meta_degraded_when_host_edge_no_edge_url(
    client: TestClient, data_dir: Path
) -> None:
    h = _auth(data_dir)
    client.patch(
        "/api/v1/config",
        headers=h,
        json={"deployment_mode": "host_edge"},
    )
    r = client.post(
        "/api/v1/chat",
        headers=h,
        json={"messages": [{"role": "user", "content": "Say hello in one word."}]},
    )
    assert r.status_code == 200
    meta = r.json()["meta"]
    assert meta["degraded"] is True
    assert meta.get("degraded_reason")


def test_admin_reset_index_clears_vector_store(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    secret = "reset-index-unique-xyz-9911"
    ing = client.post(
        "/api/v1/memory/entries",
        headers=h,
        json={"text": secret, "tags": [], "source": "pytest"},
    )
    assert ing.status_code == 201
    doc_id = ing.json()["document_id"]
    sr = client.get(
        "/api/v1/memory/search",
        headers=h,
        params={"q": "reset-index-unique-xyz"},
    )
    assert sr.status_code == 200
    assert any(r["document_id"] == doc_id for r in sr.json()["results"])

    rs = client.post("/api/v1/admin/control/reset-index", headers=h)
    assert rs.status_code == 200
    assert rs.json().get("ok") is True

    sr2 = client.get(
        "/api/v1/memory/search",
        headers=h,
        params={"q": "reset-index-unique-xyz"},
    )
    assert sr2.status_code == 200
    assert not any(r["document_id"] == doc_id for r in sr2.json()["results"])
