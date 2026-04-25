"""Google Calendar OAuth connection state (Phase 2 foundation)."""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from memoryagent.config_store import AppConfig


GOOGLE_CALENDAR_TOKEN_FILENAME = "google_calendar_tokens.json"
GOOGLE_CALENDAR_OAUTH_STATE_FILENAME = "google_calendar_oauth_state.json"
GOOGLE_CALENDAR_SECRET_FILENAME = "google_calendar_client_secret.txt"
GOOGLE_CALENDAR_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_CALENDAR_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GOOGLE_CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
GOOGLE_CALENDAR_OAUTH_STATE_TTL_SECONDS = 600


def google_calendar_token_path(data_dir: Path) -> Path:
    return data_dir / "secrets" / GOOGLE_CALENDAR_TOKEN_FILENAME


def google_calendar_oauth_state_path(data_dir: Path) -> Path:
    return data_dir / "secrets" / GOOGLE_CALENDAR_OAUTH_STATE_FILENAME


def google_calendar_client_secret_path(data_dir: Path) -> Path:
    return data_dir / "secrets" / GOOGLE_CALENDAR_SECRET_FILENAME


class GoogleCalendarOAuthError(ValueError):
    """Safe OAuth setup/exchange error. Messages must not contain secrets."""


class GoogleCalendarApiError(ValueError):
    """Safe Google Calendar API error. Messages must not contain secrets."""


def _safe_google_error_message(response: httpx.Response, fallback: str) -> str:
    try:
        data = response.json()
    except ValueError:
        return fallback
    if not isinstance(data, dict):
        return fallback
    code = str(data.get("error") or "").strip()
    description = str(data.get("error_description") or "").strip()
    parts = [fallback]
    if code:
        parts.append(f"error={code}")
    if description:
        parts.append(f"description={description[:240]}")
    return "; ".join(parts)


def google_calendar_connected(data_dir: Path) -> bool:
    """Return true when OAuth token storage exists and has a refresh token."""
    path = google_calendar_token_path(data_dir)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    return bool(isinstance(data, dict) and str(data.get("refresh_token") or "").strip())


def google_calendar_account_hint(data_dir: Path) -> str | None:
    """Non-secret account label from token metadata, if present."""
    path = google_calendar_token_path(data_dir)
    if not path.is_file():
        return None
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    hint = str(data.get("account_hint") or data.get("email") or "").strip()
    return hint or None


def delete_google_calendar_tokens(data_dir: Path) -> bool:
    """Delete local Google Calendar OAuth token storage. Returns true if removed."""
    path = google_calendar_token_path(data_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


async def revoke_google_calendar_tokens(
    data_dir: Path,
    *,
    timeout_seconds: float = 30.0,
) -> bool:
    """Best-effort revoke of the stored Google refresh/access token before local deletion."""
    path = google_calendar_token_path(data_dir)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as e:
        raise GoogleCalendarApiError("Google Calendar token storage is invalid.") from e
    if not isinstance(data, dict):
        raise GoogleCalendarApiError("Google Calendar token storage is invalid.")
    token = str(data.get("refresh_token") or data.get("access_token") or "").strip()
    if not token:
        return False

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            GOOGLE_CALENDAR_REVOKE_URL,
            data={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        raise GoogleCalendarApiError(
            _safe_google_error_message(response, "Google Calendar token revoke failed.")
        )
    return True


def resolve_google_calendar_client_id(cfg: AppConfig) -> str | None:
    raw = cfg.google_calendar_oauth_client_id or os.environ.get("GOOGLE_CALENDAR_CLIENT_ID") or ""
    return raw.strip() or None


def resolve_google_calendar_client_secret(data_dir: Path) -> str | None:
    env = os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET")
    if env and env.strip():
        return env.strip()
    path = google_calendar_client_secret_path(data_dir)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip() or None
    return None


def resolve_google_calendar_redirect_uri(cfg: AppConfig) -> str:
    if cfg.google_calendar_oauth_redirect_uri:
        return cfg.google_calendar_oauth_redirect_uri
    return f"http://{cfg.host}:{cfg.port}/api/v1/calendar/google/callback"


def build_google_calendar_authorization_url(
    data_dir: Path,
    cfg: AppConfig,
    *,
    now: float | None = None,
) -> tuple[str, str]:
    """Create a short-lived OAuth state and return Google's consent URL."""
    client_id = resolve_google_calendar_client_id(cfg)
    if not client_id:
        raise GoogleCalendarOAuthError("Google Calendar OAuth client ID is not configured.")

    state = secrets.token_urlsafe(32)
    redirect_uri = resolve_google_calendar_redirect_uri(cfg)
    created_at = time.time() if now is None else now
    state_path = google_calendar_oauth_state_path(data_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "state": state,
                "created_at": created_at,
                "redirect_uri": redirect_uri,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    state_path.chmod(0o600)

    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_CALENDAR_EVENTS_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return f"{GOOGLE_CALENDAR_AUTH_URL}?{query}", state


def _validate_google_calendar_oauth_state(
    data_dir: Path,
    state: str,
    *,
    now: float | None = None,
) -> str:
    path = google_calendar_oauth_state_path(data_dir)
    if not path.is_file():
        raise GoogleCalendarOAuthError("Google Calendar OAuth state is missing or expired.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as e:
        raise GoogleCalendarOAuthError("Google Calendar OAuth state is invalid.") from e
    created_at = float(data.get("created_at") or 0)
    current = time.time() if now is None else now
    if current - created_at > GOOGLE_CALENDAR_OAUTH_STATE_TTL_SECONDS:
        raise GoogleCalendarOAuthError("Google Calendar OAuth state is expired.")
    expected = str(data.get("state") or "")
    if not secrets.compare_digest(expected, state):
        raise GoogleCalendarOAuthError("Google Calendar OAuth state mismatch.")
    redirect_uri = str(data.get("redirect_uri") or "")
    if not redirect_uri:
        raise GoogleCalendarOAuthError("Google Calendar OAuth redirect URI is missing.")
    return redirect_uri


async def exchange_google_calendar_authorization_code(
    data_dir: Path,
    cfg: AppConfig,
    *,
    code: str,
    state: str,
    timeout_seconds: float = 30.0,
) -> None:
    """Exchange an OAuth code for tokens and persist them with restrictive permissions."""
    if not code.strip():
        raise GoogleCalendarOAuthError("Google Calendar OAuth code is required.")
    redirect_uri = _validate_google_calendar_oauth_state(data_dir, state)
    client_id = resolve_google_calendar_client_id(cfg)
    if not client_id:
        raise GoogleCalendarOAuthError("Google Calendar OAuth client ID is not configured.")
    client_secret = resolve_google_calendar_client_secret(data_dir)
    if not client_secret:
        raise GoogleCalendarOAuthError("Google Calendar OAuth client secret is not configured.")

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            GOOGLE_CALENDAR_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code >= 400:
        raise GoogleCalendarOAuthError(
            _safe_google_error_message(response, "Google Calendar OAuth token exchange failed.")
        )
    data = response.json()
    refresh_token = str(data.get("refresh_token") or "").strip()
    if not refresh_token:
        raise GoogleCalendarOAuthError(
            "Google Calendar OAuth completed without a refresh token; retry consent."
        )

    token_path = google_calendar_token_path(data_dir)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps(
            {
                "refresh_token": refresh_token,
                "access_token": str(data.get("access_token") or ""),
                "expires_in": data.get("expires_in"),
                "token_type": data.get("token_type"),
                "scope": data.get("scope"),
                "created_at": int(time.time()),
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    token_path.chmod(0o600)
    google_calendar_oauth_state_path(data_dir).unlink(missing_ok=True)


def _load_google_calendar_tokens(data_dir: Path) -> dict[str, Any]:
    path = google_calendar_token_path(data_dir)
    if not path.is_file():
        raise GoogleCalendarApiError("Google Calendar is not connected.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as e:
        raise GoogleCalendarApiError("Google Calendar token storage is invalid.") from e
    if not isinstance(data, dict):
        raise GoogleCalendarApiError("Google Calendar token storage is invalid.")
    return data


async def refresh_google_calendar_access_token(
    data_dir: Path,
    cfg: AppConfig,
    *,
    timeout_seconds: float = 30.0,
) -> str:
    """Use the stored refresh token to get a fresh access token."""
    tokens = _load_google_calendar_tokens(data_dir)
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not refresh_token:
        raise GoogleCalendarApiError("Google Calendar is not connected.")
    client_id = resolve_google_calendar_client_id(cfg)
    if not client_id:
        raise GoogleCalendarApiError("Google Calendar OAuth client ID is not configured.")
    client_secret = resolve_google_calendar_client_secret(data_dir)
    if not client_secret:
        raise GoogleCalendarApiError("Google Calendar OAuth client secret is not configured.")

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            GOOGLE_CALENDAR_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code >= 400:
        raise GoogleCalendarApiError(
            _safe_google_error_message(response, "Google Calendar token refresh failed.")
        )
    data = response.json()
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise GoogleCalendarApiError("Google Calendar token refresh returned no access token.")

    token_path = google_calendar_token_path(data_dir)
    tokens.update(
        {
            "access_token": access_token,
            "expires_in": data.get("expires_in"),
            "token_type": data.get("token_type"),
            "scope": data.get("scope", tokens.get("scope")),
            "refreshed_at": int(time.time()),
        }
    )
    token_path.write_text(json.dumps(tokens, separators=(",", ":")), encoding="utf-8")
    token_path.chmod(0o600)
    return access_token


def _google_event_time(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    raw = value.get("dateTime") or value.get("date") or ""
    return str(raw)


def _normalize_google_event(item: dict[str, Any], *, calendar_id: str) -> dict[str, Any]:
    start = item.get("start")
    end = item.get("end")
    return {
        "event_id": str(item.get("id") or ""),
        "title": str(item.get("summary") or "(No title)"),
        "starts_at": _google_event_time(start),
        "ends_at": _google_event_time(end),
        "location": str(item.get("location") or ""),
        "notes": str(item.get("description") or ""),
        "all_day": isinstance(start, dict) and bool(start.get("date") and not start.get("dateTime")),
        "calendar_id": calendar_id,
        "source": "google",
        "source_label": "Google Calendar",
        "html_link": str(item.get("htmlLink") or ""),
    }


async def list_google_calendar_events(
    data_dir: Path,
    cfg: AppConfig,
    args: dict[str, Any],
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """List Google Calendar events in [start, end), using the stored refresh token."""
    start = args.get("start")
    end = args.get("end")
    if not isinstance(start, str) or not start.strip():
        raise GoogleCalendarApiError("start is required (ISO-8601 string)")
    if not isinstance(end, str) or not end.strip():
        raise GoogleCalendarApiError("end is required (ISO-8601 string)")
    raw_calendar_id = args.get("google_calendar_id") or args.get("calendar_id") or "primary"
    calendar_id = str(raw_calendar_id).strip() or "primary"
    raw_limit = args.get("limit", 100)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 250))

    access_token = await refresh_google_calendar_access_token(
        data_dir,
        cfg,
        timeout_seconds=timeout_seconds,
    )
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "timeMin": start.strip(),
                "timeMax": end.strip(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": str(limit),
            },
        )
    if response.status_code >= 400:
        raise GoogleCalendarApiError(
            _safe_google_error_message(response, "Google Calendar events request failed.")
        )
    data = response.json()
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    events = [
        _normalize_google_event(item, calendar_id=calendar_id)
        for item in items
        if isinstance(item, dict)
    ]
    return {"events": events, "count": len(events)}


def _parse_iso_instant_or_now(raw: Any) -> datetime:
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        try:
            if text.endswith("Z"):
                return datetime.fromisoformat(text[:-1] + "+00:00")
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_instant(raw: str, *, field: str) -> datetime:
    text = raw.strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text[:-1] + "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError as e:
        raise GoogleCalendarApiError(f"{field} must be an ISO-8601 string") from e
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _search_keywords(args: dict[str, Any]) -> list[str]:
    raw_kw = args.get("keywords")
    if not isinstance(raw_kw, list) or not raw_kw:
        raise GoogleCalendarApiError("keywords is required (non-empty array of strings)")
    keywords = [x.strip() for x in raw_kw if isinstance(x, str) and x.strip()]
    if not keywords:
        raise GoogleCalendarApiError("keywords must contain at least one non-empty string")
    return keywords


def _bounded_int(raw: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


async def search_google_calendar_past_events(
    data_dir: Path,
    cfg: AppConfig,
    args: dict[str, Any],
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Search Google Calendar events before an instant using the Calendar API q filter."""
    keywords = _search_keywords(args)
    before = _parse_iso_instant_or_now(args.get("before"))
    lookback_days = _bounded_int(args.get("lookback_days", 730), default=730, minimum=1, maximum=3650)
    limit = _bounded_int(args.get("limit", 20), default=20, minimum=1, maximum=100)
    raw_calendar_id = args.get("google_calendar_id") or args.get("calendar_id") or "primary"
    calendar_id = str(raw_calendar_id).strip() or "primary"

    access_token = await refresh_google_calendar_access_token(
        data_dir,
        cfg,
        timeout_seconds=timeout_seconds,
    )
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "timeMin": _iso_z(before - timedelta(days=lookback_days)),
                "timeMax": _iso_z(before),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": str(limit),
                "q": " ".join(keywords),
            },
        )
    if response.status_code >= 400:
        raise GoogleCalendarApiError(
            _safe_google_error_message(response, "Google Calendar search request failed.")
        )
    data = response.json()
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    events = [
        _normalize_google_event(item, calendar_id=calendar_id)
        for item in items
        if isinstance(item, dict)
    ]
    return {"events": events, "count": len(events)}


def _google_create_event_body(args: dict[str, Any]) -> dict[str, Any]:
    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        raise GoogleCalendarApiError("title is required")
    starts_at = args.get("starts_at")
    if not isinstance(starts_at, str) or not starts_at.strip():
        raise GoogleCalendarApiError("starts_at is required (ISO-8601)")

    body: dict[str, Any] = {"summary": title.strip()}
    location = args.get("location")
    if isinstance(location, str) and location:
        body["location"] = location
    notes = args.get("notes")
    if isinstance(notes, str) and notes:
        body["description"] = notes

    if bool(args.get("all_day")):
        start_dt = _parse_iso_instant(starts_at, field="starts_at")
        ends_at = args.get("ends_at")
        if isinstance(ends_at, str) and ends_at.strip():
            end_dt = _parse_iso_instant(ends_at, field="ends_at")
        else:
            end_dt = start_dt + timedelta(days=1)
        body["start"] = {"date": start_dt.date().isoformat()}
        body["end"] = {"date": end_dt.date().isoformat()}
        return body

    start_dt = _parse_iso_instant(starts_at, field="starts_at")
    ends_at = args.get("ends_at")
    if isinstance(ends_at, str) and ends_at.strip():
        end_dt = _parse_iso_instant(ends_at, field="ends_at")
    else:
        end_dt = start_dt + timedelta(hours=1)
    body["start"] = {"dateTime": _iso_z(start_dt)}
    body["end"] = {"dateTime": _iso_z(end_dt)}
    return body


async def create_google_calendar_event(
    data_dir: Path,
    cfg: AppConfig,
    args: dict[str, Any],
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Create a Google Calendar event. Requires OAuth consent with calendar.events."""
    raw_calendar_id = args.get("google_calendar_id") or args.get("calendar_id") or "primary"
    calendar_id = str(raw_calendar_id).strip() or "primary"
    access_token = await refresh_google_calendar_access_token(
        data_dir,
        cfg,
        timeout_seconds=timeout_seconds,
    )
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            json=_google_create_event_body(args),
        )
    if response.status_code >= 400:
        raise GoogleCalendarApiError(
            _safe_google_error_message(response, "Google Calendar event create failed.")
        )
    data = response.json()
    if not isinstance(data, dict):
        raise GoogleCalendarApiError("Google Calendar event create returned invalid data.")
    event = _normalize_google_event(data, calendar_id=calendar_id)
    return {
        "event_id": event["event_id"],
        "title": event["title"],
        "starts_at": event["starts_at"],
        "ends_at": event["ends_at"],
        "calendar_target": "google",
        "calendar_id": calendar_id,
        "html_link": event.get("html_link", ""),
    }
