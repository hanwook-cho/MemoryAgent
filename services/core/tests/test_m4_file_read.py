"""M4: file.read tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.config_store import load_config, save_config
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


def test_file_read_under_data_dir(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    p = data_dir / "mirror" / "tool-read-test.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("hello file tool m4", encoding="utf-8")

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={"tool": "file.read", "arguments": {"path": str(p)}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["content"] == "hello file tool m4"
    assert body["result"]["path"] == str(p.resolve())


def test_file_read_under_watched_root(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    watch = data_dir / "watched_tool"
    watch.mkdir()
    cfg = load_config(data_dir)
    cfg.watched_roots = [str(watch)]
    save_config(data_dir, cfg)

    p = watch / "x.md"
    p.write_text("# title\n", encoding="utf-8")

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={"tool": "file.read", "arguments": {"path": str(p)}},
    )
    assert r.status_code == 200
    assert r.json()["result"]["content"].startswith("# title")


def test_file_read_denied_outside(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    outside = data_dir.parent / "outside_m4.txt"
    outside.write_text("nope", encoding="utf-8")

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={"tool": "file.read", "arguments": {"path": str(outside)}},
    )
    assert r.status_code == 400


def test_file_read_too_large(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    import memoryagent.tool_registry as tr

    p = data_dir / "huge.txt"
    p.write_bytes(b"x" * (tr.MAX_FILE_READ_BYTES + 1))

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={"tool": "file.read", "arguments": {"path": str(p)}},
    )
    assert r.status_code == 400


def test_list_tools_includes_file_read(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    r = client.get("/api/v1/tools", headers=h)
    names = {t["name"] for t in r.json()["tools"]}
    assert "file.read" in names
