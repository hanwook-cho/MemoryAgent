"""M0 acceptance: health public, config requires bearer, OpenAPI present."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.watcher import NullFileWatcher
from memoryagent.secrets import bearer_token_path


@pytest.fixture()
def client(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_ollama(_: str) -> bool:
        return False

    import memoryagent.app as app_mod

    monkeypatch.setattr(app_mod, "ollama_reachable", fake_ollama)

    empty = data_dir / "no_web"
    empty.mkdir()
    app = create_app(data_dir=data_dir, static_dir=empty, file_watcher=NullFileWatcher())
    return TestClient(app)


def test_health_ok(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["llm"]["backend"] == "ollama"
    assert body["llm"]["reachable"] is False
    idx = body["index"]
    assert isinstance(idx["documents"], int)
    assert isinstance(idx["chunks"], int)
    assert idx["documents"] >= 0
    assert idx["chunks"] >= 0


def test_config_unauthorized(client: TestClient) -> None:
    r = client.get("/api/v1/config")
    assert r.status_code == 401


def test_config_with_token(client: TestClient, data_dir: Path) -> None:
    token = bearer_token_path(data_dir).read_text().strip()
    r = client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["chat_model"] == "llama3.2"
    assert body["embed_model"] == "nomic-embed-text"
    assert body.get("deployment_mode") == "standalone"


def test_openapi_json(client: TestClient) -> None:
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["info"]["title"] == "MemoryAgent API"
