"""M4: chat path triggers memory.save heuristics (same ingest as POST /memory/entries)."""

from __future__ import annotations

from pathlib import Path

import pytest
import re
from fastapi.testclient import TestClient

from memoryagent.app import create_app
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
        llm=FakeLlm(reply="Saved; I'll remember that."),
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


def test_chat_remember_that_ingests_and_replies(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    secret = "m4-chat-save-token-773399"
    r = client.post(
        "/api/v1/chat",
        headers=h,
        json={
            "messages": [
                {"role": "user", "content": f"Remember that {secret}"},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "reply" in body
    assert body["citations"] == []

    r2 = client.get(
        "/api/v1/memory/search",
        params={"q": "773399"},
        headers=h,
    )
    assert r2.status_code == 200
    assert any(secret in x["snippet"] for x in r2.json()["results"])


def test_chat_without_remember_still_uses_rag(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    client.post(
        "/api/v1/memory/entries",
        json={"text": "Chat path test fact: river is blue.", "tags": [], "source": "pytest"},
        headers=h,
    )
    r = client.post(
        "/api/v1/chat",
        headers=h,
        json={
            "messages": [
                {"role": "user", "content": "What color is the river I saved?"},
            ],
        },
    )
    assert r.status_code == 200
    assert len(r.json().get("citations", [])) >= 1


def test_chat_calendar_create_reuses_location_from_past_search(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)

    async def fake_search(args: dict) -> dict:
        assert "keywords" in args
        return {
            "events": [
                {
                    "event_id": "old-1",
                    "title": "Dentist old",
                    "starts_at": "2025-01-01T10:00:00Z",
                    "ends_at": "2025-01-01T11:00:00Z",
                    "location": "123 Dental St",
                    "all_day": False,
                }
            ],
            "count": 1,
        }

    async def fake_create(args: dict) -> dict:
        assert args["location"] == "123 Dental St"
        return {
            "event_id": "new-1",
            "title": args["title"],
            "starts_at": args["starts_at"],
            "ends_at": args.get("ends_at", "2026-07-01T15:00:00Z"),
        }

    monkeypatch.setattr("memoryagent.rag_service.run_search_past_events", fake_search)
    monkeypatch.setattr("memoryagent.rag_service.run_create_event", fake_create)

    r = client.post(
        "/api/v1/chat",
        headers=h,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "create calendar event: title=Dentist Checkup; "
                        "starts_at=2026-07-01T14:00:00Z"
                    ),
                }
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "Created calendar event" in body["reply"]
    assert "123 Dental St" in body["reply"]
    assert body["citations"] == []


def test_chat_calendar_create_asks_for_location_when_not_found(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)

    async def fake_search(_: dict) -> dict:
        return {"events": [], "count": 0}

    async def fake_create(_: dict) -> dict:
        raise AssertionError("create should not be called when location is missing")

    monkeypatch.setattr("memoryagent.rag_service.run_search_past_events", fake_search)
    monkeypatch.setattr("memoryagent.rag_service.run_create_event", fake_create)

    r = client.post(
        "/api/v1/chat",
        headers=h,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "create calendar event: title=Dentist Checkup; "
                        "starts_at=2026-07-01T14:00:00Z"
                    ),
                }
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "could not find a previous location" in body["reply"]


def test_chat_calendar_create_natural_phrase(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)

    async def fake_search(_: dict) -> dict:
        return {"events": [], "count": 0}

    async def fake_create(args: dict) -> dict:
        assert args["title"] == "dentist checkup"
        assert args["location"] == "Smile Clinic"
        return {
            "event_id": "natural-1",
            "title": args["title"],
            "starts_at": args["starts_at"],
            "ends_at": args.get("ends_at", "2026-07-01T15:00:00Z"),
        }

    monkeypatch.setattr("memoryagent.rag_service.run_search_past_events", fake_search)
    monkeypatch.setattr("memoryagent.rag_service.run_create_event", fake_create)

    r = client.post(
        "/api/v1/chat",
        headers=h,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Schedule dentist checkup at 2026-07-01T14:00:00Z "
                        "to 2026-07-01T15:00:00Z in Smile Clinic"
                    ),
                }
            ]
        },
    )
    assert r.status_code == 200
    assert "Created calendar event" in r.json()["reply"]


def test_chat_calendar_lookup_freeform_uses_calendar(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)

    async def fake_list(args: dict) -> dict:
        assert "start" in args and "end" in args
        return {
            "events": [
                {
                    "event_id": "ev-1",
                    "title": "Takashi Dental",
                    "starts_at": "2026-06-08T17:00:00.000Z",
                    "ends_at": "2026-06-08T18:00:00.000Z",
                    "location": "San Mateo",
                    "all_day": False,
                },
                {
                    "event_id": "ev-2",
                    "title": "Juneteenth",
                    "starts_at": "2026-06-19T07:00:00.000Z",
                    "ends_at": "2026-06-20T06:59:59.000Z",
                    "location": "",
                    "all_day": True,
                }
            ],
            "count": 2,
        }

    monkeypatch.setattr("memoryagent.rag_service.run_list_events", fake_list)

    r = client.post(
        "/api/v1/chat",
        headers=h,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "let me get the date and time of appointment at Takashi Dental in June",
                }
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "I found these matching appointments" in body["reply"]
    assert "Takashi Dental" in body["reply"]
    assert "Juneteenth" not in body["reply"]
    # local formatted datetime shape: HH:MM, DD:MM:YYYY
    assert re.search(r"\d{2}:\d{2}, \d{2}:\d{2}:\d{4}", body["reply"]) is not None
    assert body["citations"] == []


def test_chat_capabilities_reply_is_app_specific(client: TestClient, data_dir: Path) -> None:
    h = _auth(data_dir)
    r = client.post(
        "/api/v1/chat",
        headers=h,
        json={"messages": [{"role": "user", "content": "what can you do for me?"}]},
    )
    assert r.status_code == 200
    reply = r.json()["reply"].lower()
    assert "memoryagent" in reply
    assert "calendar" in reply
    assert "long-term memory" in reply
