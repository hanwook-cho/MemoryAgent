"""M2: ignore globs, file ingest, config PATCH for watched roots."""

from __future__ import annotations

from pathlib import Path
import time

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
from memoryagent.watcher import build_ignore_spec, collect_supported_files, path_matches_ignore


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


def test_collect_supported_files_honors_ignore_and_suffixes(data_dir: Path) -> None:
    root = data_dir / "watchroot"
    root.mkdir()
    (root / "a.md").write_text("a", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "c.pdf").write_bytes(b"%PDF-1.4\n%fake")
    (root / "d.docx").write_bytes(b"fake")
    (root / "skip.bin").write_bytes(b"x")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "e.md").write_text("ignore me", encoding="utf-8")

    spec = build_ignore_spec(["**/node_modules/**"])
    out = collect_supported_files(root, spec)
    names = {p.name for p in out}
    assert names == {"a.md", "b.txt", "c.pdf", "d.docx"}


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


@pytest.mark.asyncio
async def test_ingest_pdf_path_searchable_with_mock_reader(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = data_dir / "fixture.pdf"
    f.write_bytes(b"%PDF-1.4\n% fake")

    class _P:
        def __init__(self, t: str) -> None:
            self._t = t

        def extract_text(self) -> str:
            return self._t

    class _R:
        def __init__(self, _path: str) -> None:
            self.pages = [_P("Statement amount 123"), _P("Bank account ending 1111")]

    monkeypatch.setattr("memoryagent.document_extractors.PdfReader", _R)

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="ok"),
    )

    await rag.ingest_file_path(f)
    results = await rag.search("bank statement")
    assert results
    assert "statement" in results[0].snippet.lower() or "bank" in results[0].snippet.lower()


@pytest.mark.asyncio
async def test_ingest_docx_path_searchable_with_mock_reader(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = data_dir / "fixture.docx"
    f.write_bytes(b"fake")

    class _Para:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Doc:
        def __init__(self, _path: str) -> None:
            self.paragraphs = [_Para("Quarterly bank statement"), _Para("Account 1111")]

    monkeypatch.setattr("memoryagent.document_extractors.Document", _Doc)

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="ok"),
    )

    await rag.ingest_file_path(f)
    results = await rag.search("bank statement")
    assert results
    assert "statement" in results[0].snippet.lower() or "bank" in results[0].snippet.lower()


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


@pytest.mark.asyncio
async def test_search_filter_source_kind(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md = data_dir / "notes.md"
    md.write_text("Project zephyr notes", encoding="utf-8")
    pdf = data_dir / "statement.pdf"
    pdf.write_bytes(b"%PDF fake")

    class _P:
        def __init__(self, t: str) -> None:
            self._t = t

        def extract_text(self) -> str:
            return self._t

    class _R:
        def __init__(self, _path: str) -> None:
            self.pages = [_P("bank statement april")]
    monkeypatch.setattr("memoryagent.document_extractors.PdfReader", _R)

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="ok"),
    )

    await rag.ingest_file_path(md)
    await rag.ingest_file_path(pdf)
    from memoryagent.rag_service import SearchFilters

    results = await rag.search("statement", filters=SearchFilters(source_kind="file_pdf"))
    assert results
    assert "statement" in results[0].snippet.lower()


@pytest.mark.asyncio
async def test_search_filter_path_prefix(data_dir: Path) -> None:
    scope = data_dir / "scope"
    other = data_dir / "other"
    scope.mkdir()
    other.mkdir()
    f1 = scope / "a.md"
    f2 = other / "b.md"
    f1.write_text("bank statement scoped", encoding="utf-8")
    f2.write_text("bank statement other", encoding="utf-8")

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="ok"),
    )
    await rag.ingest_file_path(f1)
    await rag.ingest_file_path(f2)
    from memoryagent.rag_service import SearchFilters

    results = await rag.search(
        "bank statement",
        filters=SearchFilters(path_prefix=scope.resolve().as_uri()),
    )
    assert results
    assert all("scoped" in r.snippet.lower() for r in results)


def test_memory_search_filter_invalid_indexed_after(
    data_dir: Path, client: TestClient
) -> None:
    h = _auth(data_dir)
    r = client.get(
        "/api/v1/memory/search",
        params={"q": "anything", "indexed_after": "not-an-iso"},
        headers=h,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "VALIDATION"


def test_query_text_filters_last_month_window() -> None:
    from memoryagent.rag_service import _filters_from_query_text

    f = _filters_from_query_text("find bank statement in the last month as pdf")
    assert f.source_kind == "file_pdf"
    assert f.indexed_after is not None
    assert f.indexed_before is not None


@pytest.mark.asyncio
async def test_ingest_file_path_extraction_timeout(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = data_dir / "slow.md"
    f.write_text("hello", encoding="utf-8")

    def _slow(_path: Path) -> tuple[str, str]:
        time.sleep(0.05)
        return "hello", "file"

    monkeypatch.setattr("memoryagent.rag_service.extract_text_from_path", _slow)
    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FakeLlm(reply="ok"),
        extract_timeout_seconds=0.001,
    )
    with pytest.raises(ValueError, match="timed out"):
        await rag.ingest_file_path(f)
