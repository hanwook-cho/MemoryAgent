"""M5: automated checks that API failures return stable structured ``detail.error`` payloads."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.backends import LocalRagRetrievalBackend
from memoryagent.calendar_bridge import CalendarPermissionDenied
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.llm_client import FakeLlm
from memoryagent.rag_service import RagService, SearchFilters
from memoryagent.schemas import ChatMessage, SearchResultItem
from memoryagent.secrets import bearer_token_path
from memoryagent.vector_store import VectorStore
from memoryagent.watcher import NullFileWatcher


def _assert_api_error(payload: dict, *, code: str) -> None:
    assert "detail" in payload
    detail = payload["detail"]
    assert isinstance(detail, dict)
    err = detail.get("error")
    assert isinstance(err, dict), f"expected detail.error object, got {detail!r}"
    assert err.get("code") == code
    assert "message" in err
    assert isinstance(err["message"], str)
    assert len(err["message"]) > 0


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


def test_unknown_tool_returns_structured_validation(client: TestClient, data_dir: Path) -> None:
    r = client.post(
        "/api/v1/tools/invoke",
        headers=_auth(data_dir),
        json={"tool": "not.a.real.tool", "arguments": {}},
    )
    assert r.status_code == 404
    _assert_api_error(r.json(), code="VALIDATION")


def test_calendar_rest_permission_denied_structured(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def deny(_: dict) -> dict:
        raise CalendarPermissionDenied("simulated TCC denial")

    monkeypatch.setattr("memoryagent.app.run_create_event", deny)

    r = client.post(
        "/api/v1/calendar/events",
        headers=_auth(data_dir),
        json={"title": "X", "starts_at": "2026-06-01T12:00:00Z"},
    )
    assert r.status_code == 403
    _assert_api_error(r.json(), code="PERMISSION_DENIED")


def test_tools_invoke_calendar_permission_maps_to_structured_403(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def deny(_: dict) -> dict:
        raise CalendarPermissionDenied("no calendars access")

    monkeypatch.setattr("memoryagent.tool_registry.run_list_events", deny)

    r = client.post(
        "/api/v1/tools/invoke",
        headers=_auth(data_dir),
        json={
            "tool": "calendar.list_events",
            "arguments": {"start": "2026-04-21T00:00:00Z", "end": "2026-04-30T00:00:00Z"},
        },
    )
    assert r.status_code == 403
    _assert_api_error(r.json(), code="PERMISSION_DENIED")


def test_memory_search_bad_date_structured_validation(
    client: TestClient, data_dir: Path
) -> None:
    r = client.get(
        "/api/v1/memory/search",
        headers=_auth(data_dir),
        params={"q": "x", "indexed_after": "not-an-iso-timestamp"},
    )
    assert r.status_code == 400
    _assert_api_error(r.json(), code="VALIDATION")


@pytest.fixture()
def client_broken_embed(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_ollama(_: str) -> bool:
        return False

    import memoryagent.app as app_mod

    monkeypatch.setattr(app_mod, "ollama_reachable", fake_ollama)

    class BrokenEmbedder:
        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("embedding backend unreachable (test)")

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=BrokenEmbedder(),
        llm=FakeLlm(reply="ok"),
    )
    empty = data_dir / "no_web2"
    empty.mkdir()
    app = create_app(
        data_dir=data_dir,
        static_dir=empty,
        rag_service=rag,
        file_watcher=NullFileWatcher(),
    )
    return TestClient(app)


def test_memory_ingest_model_unavailable_structured(
    client_broken_embed: TestClient, data_dir: Path
) -> None:
    r = client_broken_embed.post(
        "/api/v1/memory/entries",
        headers=_auth(data_dir),
        json={"text": "hello from pytest", "tags": [], "source": "pytest"},
    )
    assert r.status_code == 503
    _assert_api_error(r.json(), code="MODEL_UNAVAILABLE")


@pytest.fixture()
def client_failing_llm(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_ollama(_: str) -> bool:
        return False

    import memoryagent.app as app_mod

    monkeypatch.setattr(app_mod, "ollama_reachable", fake_ollama)

    class FailingLlm:
        async def chat(
            self, messages: list[ChatMessage], *, context_blocks: list[str]
        ) -> str:
            _ = messages, context_blocks
            req = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
            raise httpx.ConnectError("connection refused (test)", request=req)

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    rag = RagService(
        data_dir=data_dir,
        store=VectorStore(chroma_dir),
        embedder=DeterministicEmbedder(),
        llm=FailingLlm(),
    )
    empty = data_dir / "no_web3"
    empty.mkdir()
    app = create_app(
        data_dir=data_dir,
        static_dir=empty,
        rag_service=rag,
        file_watcher=NullFileWatcher(),
    )
    return TestClient(app)


def test_chat_model_unavailable_structured(
    client_failing_llm: TestClient, data_dir: Path
) -> None:
    """Plain RAG chat path calls ``_llm.chat``; httpx errors become MODEL_UNAVAILABLE."""
    r = client_failing_llm.post(
        "/api/v1/chat",
        headers=_auth(data_dir),
        json={"messages": [{"role": "user", "content": "Say hello in one word."}]},
    )
    assert r.status_code == 503
    body = r.json()
    _assert_api_error(body, code="MODEL_UNAVAILABLE")
    assert "not reachable" in body["detail"]["error"]["message"].lower()


def test_memory_search_model_unavailable_structured(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(
        self: LocalRagRetrievalBackend,
        query: str,
        *,
        limit: int = 20,
        filters: SearchFilters | None = None,
    ) -> list[SearchResultItem]:
        _ = self, query, limit, filters
        raise RuntimeError("vector search failed (test)")

    monkeypatch.setattr(LocalRagRetrievalBackend, "search", boom)

    r = client.get(
        "/api/v1/memory/search",
        headers=_auth(data_dir),
        params={"q": "anything"},
    )
    assert r.status_code == 503
    _assert_api_error(r.json(), code="MODEL_UNAVAILABLE")


def test_chat_stream_model_unavailable_sse_error_event(
    client_failing_llm: TestClient, data_dir: Path
) -> None:
    with client_failing_llm.stream(
        "POST",
        "/api/v1/chat/stream",
        headers=_auth(data_dir),
        json={"messages": [{"role": "user", "content": "Say hello in one word."}]},
    ) as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert "event: error" in text
    assert "MODEL_UNAVAILABLE" in text
    assert "Local inference engine not reachable" in text
