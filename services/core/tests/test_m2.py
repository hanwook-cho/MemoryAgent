"""M2: ignore globs, file ingest, config PATCH for watched roots."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.watcher import NullFileWatcher
from memoryagent.config_store import load_config
from memoryagent.llm_client import FakeLlm
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.rag_service import RagService
from memoryagent.secrets import bearer_token_path
from memoryagent.vector_store import VectorStore
from memoryagent.watcher import build_ignore_spec, path_matches_ignore


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


def test_ignore_globs_match() -> None:
    spec = build_ignore_spec(["**/.git/**", "**/node_modules/**", "**/.DS_Store"])
    assert spec is not None
    assert path_matches_ignore(".git/config", spec)
    assert path_matches_ignore("foo/node_modules/bar.js", spec)
    assert path_matches_ignore("x/.DS_Store", spec)
    assert not path_matches_ignore("notes/hello.md", spec)


@pytest.mark.asyncio
async def test_ingest_file_path_searchable(data_dir: Path) -> None:
    f = data_dir / "fixture.md"
    f.write_text("M2 file ingest: secret codeword is zephyr.\n", encoding="utf-8")

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="ok"),
    )

    await rag.ingest_file_path(f)
    results = await rag.search("codeword")
    assert results
    assert "zephyr" in results[0].snippet.lower()

    stats = rag.index_stats()
    assert stats["indexed_files"] >= 1
    assert stats["documents"] >= 1


def test_patch_config_watched_roots(data_dir: Path, client: TestClient) -> None:
    h = _auth(data_dir)
    watch = data_dir / "watch_here"
    watch.mkdir()

    r = client.patch(
        "/api/v1/config",
        json={"watched_roots": [str(watch)], "watch_debounce_seconds": 0.2},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert str(watch) in body["watched_roots"] or watch.resolve().as_posix() in [
        Path(x).resolve().as_posix() for x in body["watched_roots"]
    ]
    cfg = load_config(data_dir)
    assert len(cfg.watched_roots) == 1


def test_patch_config_rejects_missing_dir(data_dir: Path, client: TestClient) -> None:
    h = _auth(data_dir)
    r = client.patch(
        "/api/v1/config",
        json={"watched_roots": [str(data_dir / "nope_not_here")]},
        headers=h,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "VALIDATION"
