"""M4: calendar.list_events tool (mocked bridge; real binary optional on macOS)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pytest
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.calendar_bridge import CalendarPermissionDenied
from memoryagent.config_store import load_config, save_config
from memoryagent.google_calendar import GoogleCalendarApiError
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


def test_invoke_calendar_list_merges_google_when_include_on(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)
    c = load_config(data_dir)
    c.google_calendar_include = True
    save_config(data_dir, c)

    async def fake_local(args: dict) -> dict:
        assert args["start"] == "2026-04-21T00:00:00Z"
        return {
            "events": [
                {
                    "event_id": "local-1",
                    "title": "Local later",
                    "starts_at": "2026-04-22T16:00:00Z",
                    "ends_at": "2026-04-22T17:00:00Z",
                }
            ],
            "count": 1,
        }

    async def fake_google(_data_dir: Path, _cfg: object, args: dict) -> dict:
        assert args["end"] == "2026-04-30T23:59:59Z"
        return {
            "events": [
                {
                    "event_id": "google-1",
                    "title": "Google earlier",
                    "starts_at": "2026-04-22T15:00:00Z",
                    "ends_at": "2026-04-22T15:30:00Z",
                    "source": "google",
                    "source_label": "Google Calendar",
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr("memoryagent.tool_registry.run_list_events", fake_local)
    monkeypatch.setattr("memoryagent.tool_registry.list_google_calendar_events", fake_google)

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
    result = r.json()["result"]
    assert result["count"] == 2
    assert [e["event_id"] for e in result["events"]] == ["google-1", "local-1"]
    assert result["events"][0]["source"] == "google"
    assert result["events"][1]["source"] == "local"
    assert result["sources"]["google"]["degraded"] is False


def test_invoke_calendar_list_soft_degrades_when_google_fails(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)
    c = load_config(data_dir)
    c.google_calendar_include = True
    save_config(data_dir, c)

    async def fake_local(_: dict) -> dict:
        return {
            "events": [
                {
                    "event_id": "local-1",
                    "title": "Local only",
                    "starts_at": "2026-04-22T16:00:00Z",
                }
            ],
            "count": 1,
        }

    async def fake_google(_data_dir: Path, _cfg: object, _args: dict) -> dict:
        raise GoogleCalendarApiError("Google Calendar events request failed.")

    monkeypatch.setattr("memoryagent.tool_registry.run_list_events", fake_local)
    monkeypatch.setattr("memoryagent.tool_registry.list_google_calendar_events", fake_google)

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
    result = r.json()["result"]
    assert result["count"] == 1
    assert result["events"][0]["source"] == "local"
    assert result["sources"]["google"]["degraded"] is True
    assert "failed" in result["sources"]["google"]["degraded_reason"]


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


def test_invoke_calendar_search_merges_google_when_include_on(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)
    c = load_config(data_dir)
    c.google_calendar_include = True
    save_config(data_dir, c)

    async def fake_local(args: dict) -> dict:
        assert args["keywords"] == ["dentist"]
        return {
            "events": [
                {
                    "event_id": "local-old",
                    "title": "Local dentist",
                    "starts_at": "2025-01-01T10:00:00Z",
                    "location": "Local Clinic",
                }
            ],
            "count": 1,
        }

    async def fake_google(_data_dir: Path, _cfg: object, args: dict) -> dict:
        assert args["keywords"] == ["dentist"]
        return {
            "events": [
                {
                    "event_id": "google-new",
                    "title": "Google dentist",
                    "starts_at": "2025-02-01T10:00:00Z",
                    "location": "Google Clinic",
                    "source": "google",
                    "source_label": "Google Calendar",
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr("memoryagent.tool_registry.run_search_past_events", fake_local)
    monkeypatch.setattr(
        "memoryagent.tool_registry.search_google_calendar_past_events",
        fake_google,
    )

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={
            "tool": "calendar.search_past_events",
            "arguments": {"keywords": ["dentist"], "before": "2026-01-01T00:00:00Z"},
        },
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["count"] == 2
    assert [e["event_id"] for e in result["events"]] == ["google-new", "local-old"]
    assert result["sources"]["google"]["degraded"] is False


def test_invoke_calendar_search_soft_degrades_when_google_fails(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)
    c = load_config(data_dir)
    c.google_calendar_include = True
    save_config(data_dir, c)

    async def fake_local(_: dict) -> dict:
        return {
            "events": [
                {
                    "event_id": "local-1",
                    "title": "Local dentist",
                    "starts_at": "2025-01-01T10:00:00Z",
                }
            ],
            "count": 1,
        }

    async def fake_google(_data_dir: Path, _cfg: object, _args: dict) -> dict:
        raise GoogleCalendarApiError("Google Calendar search request failed.")

    monkeypatch.setattr("memoryagent.tool_registry.run_search_past_events", fake_local)
    monkeypatch.setattr(
        "memoryagent.tool_registry.search_google_calendar_past_events",
        fake_google,
    )

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={"tool": "calendar.search_past_events", "arguments": {"keywords": ["dentist"]}},
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["count"] == 1
    assert result["events"][0]["source"] == "local"
    assert result["sources"]["google"]["degraded"] is True
    assert "failed" in result["sources"]["google"]["degraded_reason"]


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
    assert body["result"]["calendar_target"] == "local"


def test_invoke_calendar_create_requires_target_when_google_included(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)
    c = load_config(data_dir)
    c.google_calendar_include = True
    save_config(data_dir, c)

    async def fake_create(_: dict) -> dict:
        raise AssertionError("local create should not run without explicit target")

    monkeypatch.setattr("memoryagent.tool_registry.run_create_event", fake_create)

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={
            "tool": "calendar.create_event",
            "arguments": {"title": "Meet", "starts_at": "2026-05-01T15:00:00Z"},
        },
    )
    assert r.status_code == 400
    assert "calendar_target is required" in r.json()["detail"]["error"]["message"]


def test_invoke_calendar_create_google_target(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)
    c = load_config(data_dir)
    c.google_calendar_include = True
    save_config(data_dir, c)

    async def fake_google(_data_dir: Path, _cfg: object, args: dict) -> dict:
        assert args["calendar_target"] == "google"
        return {
            "event_id": "google-new-eid",
            "title": args["title"],
            "starts_at": args["starts_at"],
            "ends_at": "2026-05-01T16:00:00Z",
            "calendar_target": "google",
            "calendar_id": "primary",
        }

    monkeypatch.setattr("memoryagent.tool_registry.create_google_calendar_event", fake_google)

    r = client.post(
        "/api/v1/tools/invoke",
        headers=h,
        json={
            "tool": "calendar.create_event",
            "arguments": {
                "title": "Google Meet",
                "starts_at": "2026-05-01T15:00:00Z",
                "calendar_target": "google",
            },
        },
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["event_id"] == "google-new-eid"
    assert result["calendar_target"] == "google"


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
    assert j["calendar_target"] == "local"


def test_post_calendar_events_google_target(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)
    c = load_config(data_dir)
    c.google_calendar_include = True
    save_config(data_dir, c)

    async def fake_google(_data_dir: Path, _cfg: object, args: dict) -> dict:
        return {
            "event_id": "google-rest-1",
            "title": args["title"],
            "starts_at": args["starts_at"],
            "ends_at": "2026-06-01T17:00:00Z",
            "calendar_target": "google",
            "calendar_id": "primary",
            "html_link": "https://calendar.google.test/event",
        }

    monkeypatch.setattr("memoryagent.app.create_google_calendar_event", fake_google)

    r = client.post(
        "/api/v1/calendar/events",
        headers=h,
        json={
            "title": "REST Google",
            "starts_at": "2026-06-01T16:00:00Z",
            "calendar_target": "google",
        },
    )
    assert r.status_code == 201
    j = r.json()
    assert j["event_id"] == "google-rest-1"
    assert j["calendar_target"] == "google"
    assert j["html_link"] == "https://calendar.google.test/event"


def test_google_calendar_status_default_off(client: TestClient, data_dir: Path) -> None:
    r = client.get("/api/v1/calendar/google/status", headers=_auth(data_dir))
    assert r.status_code == 200
    body = r.json()
    assert body["include"] is False
    assert body["connected"] is False
    assert body["status"] == "off"


def test_google_calendar_connect_requires_client_id(
    client: TestClient, data_dir: Path
) -> None:
    r = client.post("/api/v1/calendar/google/connect", headers=_auth(data_dir))
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "GOOGLE_CALENDAR_OAUTH_CONFIG"


def test_google_calendar_connect_returns_authorization_url(
    client: TestClient, data_dir: Path
) -> None:
    c = load_config(data_dir)
    c.google_calendar_oauth_client_id = "client-id.example.test"
    c.google_calendar_oauth_redirect_uri = (
        "http://127.0.0.1:8765/api/v1/calendar/google/callback"
    )
    save_config(data_dir, c)

    r = client.post("/api/v1/calendar/google/connect", headers=_auth(data_dir))
    assert r.status_code == 200
    body = r.json()
    parsed = urlparse(body["authorization_url"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert query["client_id"] == ["client-id.example.test"]
    assert query["scope"] == ["https://www.googleapis.com/auth/calendar.events"]
    assert query["state"] == [body["state"]]


def test_google_calendar_callback_enables_include_after_exchange(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = load_config(data_dir)
    c.google_calendar_oauth_client_id = "client-id.example.test"
    save_config(data_dir, c)

    async def fake_exchange(
        exchange_data_dir: Path,
        _cfg: object,
        *,
        code: str,
        state: str,
    ) -> None:
        assert exchange_data_dir == data_dir
        assert code == "auth-code"
        assert state == "state-token"
        token_path = data_dir / "secrets" / "google_calendar_tokens.json"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(
            json.dumps({"refresh_token": "secret-refresh-token"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "memoryagent.app.exchange_google_calendar_authorization_code",
        fake_exchange,
    )

    r = client.get(
        "/api/v1/calendar/google/callback?code=auth-code&state=state-token",
        headers=_auth(data_dir),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["include"] is True
    assert body["connected"] is True
    assert body["status"] == "on"
    assert load_config(data_dir).google_calendar_include is True


def test_google_calendar_callback_does_not_require_bearer(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = load_config(data_dir)
    c.google_calendar_oauth_client_id = "client-id.example.test"
    save_config(data_dir, c)

    async def fake_exchange(
        exchange_data_dir: Path,
        _cfg: object,
        *,
        code: str,
        state: str,
    ) -> None:
        assert exchange_data_dir == data_dir
        assert code == "auth-code"
        assert state == "state-token"
        token_path = data_dir / "secrets" / "google_calendar_tokens.json"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(
            json.dumps({"refresh_token": "secret-refresh-token"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "memoryagent.app.exchange_google_calendar_authorization_code",
        fake_exchange,
    )

    r = client.get("/api/v1/calendar/google/callback?code=auth-code&state=state-token")
    assert r.status_code == 200
    assert r.json()["status"] == "on"


def test_google_calendar_disconnect_deletes_tokens_and_turns_include_off(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _auth(data_dir)
    token_path = data_dir / "secrets" / "google_calendar_tokens.json"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps({"refresh_token": "secret-refresh-token", "account_hint": "user@example.test"}),
        encoding="utf-8",
    )
    c = load_config(data_dir)
    c.google_calendar_include = True
    save_config(data_dir, c)
    revoked: list[Path] = []

    async def fake_revoke(revoke_data_dir: Path) -> bool:
        revoked.append(revoke_data_dir)
        return True

    monkeypatch.setattr("memoryagent.app.revoke_google_calendar_tokens", fake_revoke)

    r = client.post("/api/v1/calendar/google/disconnect", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["include"] is False
    assert body["connected"] is False
    assert body["status"] == "off"
    assert revoked == [data_dir]
    assert not token_path.exists()
    assert load_config(data_dir).google_calendar_include is False
