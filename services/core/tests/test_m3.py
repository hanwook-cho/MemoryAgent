"""M3: Markdown mirror API (USER.md / SOUL.md), body-only indexing."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.llm_client import FakeLlm
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.mirror import ensure_mirror_file, mirror_path
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


def test_mirror_list_and_get(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    r = client.get("/api/v1/mirror", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert len(body["mirrors"]) == 2
    ids = {m["id"] for m in body["mirrors"]}
    assert ids == {"user", "soul"}

    r2 = client.get("/api/v1/mirror/user", headers=h)
    assert r2.status_code == 200
    j = r2.json()
    assert j["mirror_id"] == "user"
    assert "USER.md" in j["filename"]
    assert "durable preferences" in j["content"] or "USER memory" in j["content"]


def test_mirror_put_validates_yaml(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    bad = "---\n[ broken\n---\n\n# Body\n"
    r = client.put(
        "/api/v1/mirror/user",
        headers=h,
        json={"content": bad},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "VALIDATION"


def test_mirror_put_reindexes_body_only(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    secret = "m3-secret-phrase-unique-991177"
    fm = {
        "id": "test-id",
        "updated_at": "2026-01-01T00:00:00Z",
        "tags": [],
        "mirror": "user",
    }
    md = f"---\n{yaml.safe_dump(fm, sort_keys=False).strip()}\n---\n\n# Hi\n\n{secret}\n"
    r = client.put("/api/v1/mirror/user", headers=h, json={"content": md})
    assert r.status_code == 200
    assert r.json()["reindexed"] is True

    r2 = client.get(
        "/api/v1/memory/search",
        params={"q": secret},
        headers=h,
    )
    assert r2.status_code == 200
    snippets = [x["snippet"] for x in r2.json()["results"]]
    assert any(secret in s for s in snippets)
    # Front matter should not be the primary retrieval text for "id"
    for s in snippets:
        assert "test-id" not in s or secret in s


@pytest.mark.asyncio
async def test_ingest_mirror_skips_front_matter_in_chunks(data_dir: Path) -> None:
    """Direct RagService: YAML block is not in embedded chunks."""
    ensure_mirror_file(data_dir, "user")
    p = mirror_path(data_dir, "user")
    fm = {"id": "x", "mirror": "user"}
    body_md = "# T\n\nhello m3 direct test\n"
    p.write_text(f"---\n{yaml.safe_dump(fm).strip()}\n---\n\n{body_md}", encoding="utf-8")

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="ok"),
    )

    await rag.ingest_mirror_document(p, mirror_key="user")
    results = await rag.search("hello m3 direct")
    assert results
    assert "hello m3 direct" in results[0].snippet
    assert "id: x" not in results[0].snippet
