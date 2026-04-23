"""MP1 PR-1: backend adapters + ``deployment_mode`` (see ``docs/spec/mp1-pr1.md``)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.backends import (
    LocalLlmBackendAdapter,
    LocalRagIngestBackend,
    LocalRagRetrievalBackend,
    RuntimeBackends,
    build_local_backends,
)
from memoryagent.config_store import (
    config_path,
    load_config,
    normalize_deployment_mode,
)
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.llm_client import FakeLlm
from memoryagent.rag_service import RagService
from memoryagent.secrets import bearer_token_path
from memoryagent.vector_store import VectorStore
from memoryagent.watcher import NullFileWatcher


def test_normalize_deployment_mode_defaults_and_unknown(caplog: pytest.LogCaptureFixture) -> None:
    assert normalize_deployment_mode(None) == "standalone"
    assert normalize_deployment_mode("") == "standalone"
    assert normalize_deployment_mode("standalone") == "standalone"
    assert normalize_deployment_mode("host_edge") == "host_edge"
    with caplog.at_level("WARNING"):
        assert normalize_deployment_mode("bogus") == "standalone"
    assert "unknown" in caplog.text.lower() or "bogus" in caplog.text
    with caplog.at_level("WARNING"):
        assert normalize_deployment_mode(123) == "standalone"  # type: ignore[arg-type]


def test_load_config_normalizes_invalid_deployment_mode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    d = tmp_path / "data"
    d.mkdir()
    path = config_path(d)
    path.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": 8765,
                "deployment_mode": "not_a_mode",
            }
        ),
        encoding="utf-8",
    )
    with caplog.at_level("WARNING"):
        c = load_config(d)
    assert c.deployment_mode == "standalone"


def test_build_local_backends_delegates_to_rag(data_dir: Path) -> None:
    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="hi"),
    )
    b = build_local_backends(rag)
    assert isinstance(b, RuntimeBackends)
    assert isinstance(b.retrieval, LocalRagRetrievalBackend)
    assert isinstance(b.ingest, LocalRagIngestBackend)
    assert isinstance(b.llm, LocalLlmBackendAdapter)
    assert b.retrieval.index_stats() == rag.index_stats()

    async def _llm() -> None:
        from memoryagent.schemas import ChatMessage

        out = await b.llm.chat(
            [ChatMessage(role="user", content="x")], context_blocks=[]
        )
        assert out == "hi"

    asyncio.run(_llm())


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


def test_get_config_includes_deployment_mode(client: TestClient, data_dir: Path) -> None:
    r = client.get("/api/v1/config", headers=_auth(data_dir))
    assert r.status_code == 200
    body = r.json()
    assert body.get("deployment_mode") == "standalone"
    assert "edge_base_url" in body
    assert body.get("edge_base_url") is None


def test_patch_config_invalid_deployment_mode(client: TestClient, data_dir: Path) -> None:
    r = client.patch(
        "/api/v1/config",
        headers=_auth(data_dir),
        json={"deployment_mode": "nope"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "VALIDATION"


def test_patch_config_deployment_mode_persists(client: TestClient, data_dir: Path) -> None:
    r = client.patch(
        "/api/v1/config",
        headers=_auth(data_dir),
        json={"deployment_mode": "host_edge"},
    )
    assert r.status_code == 200
    assert r.json()["deployment_mode"] == "host_edge"
    c = load_config(data_dir)
    assert c.deployment_mode == "host_edge"


def test_patch_config_edge_base_url_persists(client: TestClient, data_dir: Path) -> None:
    r = client.patch(
        "/api/v1/config",
        headers=_auth(data_dir),
        json={"edge_base_url": "https://edge.example.test"},
    )
    assert r.status_code == 200
    assert r.json()["edge_base_url"] == "https://edge.example.test"
    c = load_config(data_dir)
    assert c.edge_base_url == "https://edge.example.test"


def test_patch_config_edge_base_url_clear(client: TestClient, data_dir: Path) -> None:
    client.patch(
        "/api/v1/config",
        headers=_auth(data_dir),
        json={"edge_base_url": "https://edge.example.test"},
    )
    r = client.patch(
        "/api/v1/config",
        headers=_auth(data_dir),
        json={"edge_base_url": ""},
    )
    assert r.status_code == 200
    assert r.json().get("edge_base_url") in (None, "")
    c = load_config(data_dir)
    assert c.edge_base_url is None


def test_app_state_exposes_backends(client: TestClient, data_dir: Path) -> None:
    # TestClient(app) does not run lifespan by default for .app access in some versions;
    # mp1_backends is set at create_app time.
    app = client.app
    assert hasattr(app.state, "mp1_backends")
    assert app.state.mp1_backends.retrieval.index_stats()["chunks"] == 0
