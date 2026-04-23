"""MP1 PR-2: health deployment / degraded flags (see docs/spec/mp1-pr2.md)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.deployment_runtime import health_deployment_block
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.llm_client import FakeLlm
from memoryagent.rag_service import RagService
from memoryagent.secrets import bearer_token_path
from memoryagent.vector_store import VectorStore
from memoryagent.watcher import NullFileWatcher


def test_health_deployment_block_standalone() -> None:
    d = health_deployment_block("standalone")
    assert d["mode"] == "standalone"
    assert d["degraded"] is False
    assert d["degraded_reason"] is None


def test_health_deployment_block_non_standalone() -> None:
    d = health_deployment_block("host_edge")
    assert d["mode"] == "host_edge"
    assert d["degraded"] is True
    assert d["degraded_reason"] and "remote" in d["degraded_reason"].lower()


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


def test_health_degraded_when_config_host_edge(
    client: TestClient, data_dir: Path
) -> None:
    token = bearer_token_path(data_dir).read_text().strip()
    h = {"Authorization": f"Bearer {token}"}
    r = client.patch("/api/v1/config", headers=h, json={"deployment_mode": "host_edge"})
    assert r.status_code == 200
    rh = client.get("/api/v1/health")
    assert rh.status_code == 200
    body = rh.json()
    dep = body["deployment"]
    assert dep["mode"] == "host_edge"
    assert dep["degraded"] is True
    assert dep["degraded_reason"]
