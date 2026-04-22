"""M4: calendar.list_events tool (mocked bridge; real binary optional on macOS)."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.calendar_bridge import CalendarPermissionDenied
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


def test_list_tools_includes_calendar_list(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    r = client.get("/api/v1/tools", headers=h)
    names = {t["name"] for t in r.json()["tools"]}
    assert "calendar.list_events" in names
    assert "calendar.search_past_events" in names
    assert "calendar.create_event" in names


def test_invoke_calendar_list_mocked(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)

    async def fake_run(args: dict) -> dict:
        assert "start" in args and "end" in args
        return {
            "events": [
                {
                    "event_id": "1",
                    "title": "Test event",
                    "starts_at": "2026-04-22T15:00:00Z",
                    "ends_at": "2026-04-22T16:00:00Z",
                    "location": "Here",
                    "all_day": False,
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr("memoryagent.tool_registry.run_list_events", fake_run)

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={
            "tool": "calendar.list_events",
            "arguments": {
                "start": "2026-04-21T00:00:00Z",
                "end": "2026-04-30T23:59:59Z",
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["count"] == 1
    assert body["result"]["events"][0]["title"] == "Test event"


def test_invoke_calendar_permission_denied(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)

    async def deny(_: dict) -> dict:
        raise CalendarPermissionDenied("no access")

    monkeypatch.setattr("memoryagent.tool_registry.run_list_events", deny)

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={
            "tool": "calendar.list_events",
            "arguments": {"start": "2026-04-21T00:00:00Z", "end": "2026-04-30T00:00:00Z"},
        },
    )
    assert r.status_code == 403


def test_invoke_calendar_missing_dates(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={"tool": "calendar.list_events", "arguments": {}},
    )
    assert r.status_code == 400


def test_invoke_calendar_search_mocked(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)

    async def fake_search(args: dict) -> dict:
        assert "keywords" in args
        return {
            "events": [
                {
                    "event_id": "past-1",
                    "title": "Dentist",
                    "starts_at": "2025-01-01T10:00:00Z",
                    "ends_at": "2025-01-01T11:00:00Z",
                    "location": "123 Main",
                    "all_day": False,
                    "notes": "cleaning",
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr("memoryagent.tool_registry.run_search_past_events", fake_search)

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={
            "tool": "calendar.search_past_events",
            "arguments": {"keywords": ["dentist"]},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["count"] == 1
    assert body["result"]["events"][0]["location"] == "123 Main"


def test_invoke_calendar_create_mocked(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)

    async def fake_create(args: dict) -> dict:
        assert args.get("title") == "Meet"
        return {
            "event_id": "new-eid",
            "title": "Meet",
            "starts_at": "2026-05-01T15:00:00Z",
            "ends_at": "2026-05-01T16:00:00Z",
        }

    monkeypatch.setattr("memoryagent.tool_registry.run_create_event", fake_create)

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={
            "tool": "calendar.create_event",
            "arguments": {
                "title": "Meet",
                "starts_at": "2026-05-01T15:00:00Z",
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["event_id"] == "new-eid"


def test_post_calendar_events_rest_mocked(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)

    async def fake_create(args: dict) -> dict:
        return {
            "event_id": "rest-1",
            "title": args["title"],
            "starts_at": args["starts_at"],
            "ends_at": args.get("ends_at") or "2026-06-01T17:00:00Z",
        }

    monkeypatch.setattr("memoryagent.app.run_create_event", fake_create)

    r = client.post(
        "/api/v1/calendar/events",
        headers=h,
        json={
            "title": "REST meet",
            "starts_at": "2026-06-01T16:00:00Z",
            "ends_at": "2026-06-01T17:00:00Z",
        },
    )
    assert r.status_code == 201
    j = r.json()
    assert j["event_id"] == "rest-1"
    assert j["title"] == "REST meet"
