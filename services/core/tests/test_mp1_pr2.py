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


def test_health_deployment_block_non_standalone_no_edge_url() -> None:
    d = health_deployment_block("host_edge", edge_base_url=None, edge_reachable=None)
    assert d["mode"] == "host_edge"
    assert d["degraded"] is True
    assert d["degraded_reason"] and "edge_base_url" in d["degraded_reason"].lower()


def test_health_deployment_block_edge_unreachable() -> None:
    d = health_deployment_block(
        "host_edge",
        edge_base_url="https://edge.example",
        edge_reachable=False,
        edge_error="connection refused",
    )
    assert d["degraded"] is True
    assert "connection refused" in (d["degraded_reason"] or "")


def test_health_deployment_block_edge_ok() -> None:
    d = health_deployment_block(
        "host_edge",
        edge_base_url="https://edge.example",
        edge_reachable=True,
        edge_error=None,
    )
    assert d["degraded"] is False
    assert d["degraded_reason"] is None
    assert d.get("edge_reachable") is True


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


def test_health_not_degraded_when_host_edge_and_edge_ping_ok(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import memoryagent.app as app_mod

    async def ok_edge(_url: str, *, bearer_token: str, timeout_seconds: float = 3.0) -> tuple[bool, str | None]:
        _ = bearer_token, timeout_seconds
        return True, None

    monkeypatch.setattr(app_mod, "fetch_edge_health", ok_edge)

    token = bearer_token_path(data_dir).read_text().strip()
    h = {"Authorization": f"Bearer {token}"}
    r = client.patch(
        "/api/v1/config",
        headers=h,
        json={
            "deployment_mode": "host_edge",
            "edge_base_url": "http://127.0.0.1:19999",
        },
    )
    assert r.status_code == 200
    rh = client.get("/api/v1/health")
    assert rh.status_code == 200
    dep = rh.json()["deployment"]
    assert dep["mode"] == "host_edge"
    assert dep["degraded"] is False
    assert dep.get("edge_reachable") is True


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
