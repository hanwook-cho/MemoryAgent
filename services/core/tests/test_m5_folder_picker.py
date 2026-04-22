"""M5: native folder picker endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.secrets import bearer_token_path
from memoryagent.watcher import NullFileWatcher


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


def _auth(data_dir: Path) -> dict[str, str]:
    token = bearer_token_path(data_dir).read_text().strip()
    return {"Authorization": f"Bearer {token}"}


def test_pick_folder_success(client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("memoryagent.app.pick_folder_macos", lambda: "/tmp")
    r = client.post("/api/v1/config/pick-folder", headers=_auth(data_dir))
    assert r.status_code == 200
    assert r.json()["path"] == "/tmp"


def test_pick_folder_validation_error(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> str:
        raise RuntimeError("Folder selection was cancelled.")

    monkeypatch.setattr("memoryagent.app.pick_folder_macos", boom)
    r = client.post("/api/v1/config/pick-folder", headers=_auth(data_dir))
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "VALIDATION"
