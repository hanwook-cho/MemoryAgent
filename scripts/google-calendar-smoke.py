#!/usr/bin/env python3
"""Smoke-test the live Google Calendar OAuth/read path against a running host."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _json_request(
    method: str,
    url: str,
    *,
    token: str | None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return int(r.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return int(e.code), payload


def _bearer_from_data_dir(data_dir: Path) -> str | None:
    p = data_dir / "secrets" / "bearer.token"
    if not p.is_file():
        return None
    token = p.read_text(encoding="utf-8").strip()
    return token or None


def _die(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


def _assert_status(label: str, status: int, allowed: set[int], payload: dict[str, Any]) -> None:
    if status not in allowed:
        redacted = json.dumps(payload, sort_keys=True)[:500]
        _die(f"{label}: HTTP {status}: {redacted}")


def _ensure_client_secret_for_host(data_dir: Path) -> None:
    """Persist env-provided secret where the already-running host can read it."""
    secret_path = data_dir / "secrets" / "google_calendar_client_secret.txt"
    if secret_path.is_file():
        return
    secret = os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET")
    if not secret or not secret.strip():
        _die(
            "missing Google OAuth client secret; set GOOGLE_CALENDAR_CLIENT_SECRET "
            "or create secrets/google_calendar_client_secret.txt"
        )
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(secret.strip() + "\n", encoding="utf-8")
    secret_path.chmod(0o600)


def _callback_path_from_url(raw: str) -> str:
    text = raw.strip()
    if not text:
        _die("empty callback URL")
    parsed = urllib.parse.urlparse(text)
    query = urllib.parse.parse_qs(parsed.query)
    code = query.get("code", [""])[0]
    state = query.get("state", [""])[0]
    error = query.get("error", [""])[0]
    if error:
        _die("Google OAuth callback contains an error; consent was denied or cancelled")
    if not code or not state:
        _die("callback URL must contain code and state query parameters")
    return (
        "/calendar/google/callback?"
        + urllib.parse.urlencode({"code": code, "state": state})
    )


def _tool_invoke(host: str, token: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    status, payload = _json_request(
        "POST",
        f"{host}/tools/invoke",
        token=token,
        body={"tool": tool, "arguments": arguments},
    )
    _assert_status(f"host tool {tool}", status, {200}, payload)
    result = payload.get("result")
    if not isinstance(result, dict):
        _die(f"{tool} response missing result object")
    return result


def _assert_google_not_degraded(label: str, result: dict[str, Any]) -> None:
    sources = result.get("sources")
    if not isinstance(sources, dict):
        _die(f"{label}: missing sources block; Google path may not have run")
    google = sources.get("google")
    if not isinstance(google, dict):
        _die(f"{label}: missing sources.google block")
    if google.get("degraded"):
        _die(f"{label}: Google degraded: {google.get('degraded_reason')}")
    _ok(f"{label}: Google source checked (count={google.get('count', 0)})")


def _load_google_refresh_token(data_dir: Path) -> str:
    path = data_dir / "secrets" / "google_calendar_tokens.json"
    if not path.is_file():
        _die("missing Google token storage; cannot clean up write smoke event")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _die("invalid Google token storage; cannot clean up write smoke event")
    refresh_token = str(data.get("refresh_token") or "").strip() if isinstance(data, dict) else ""
    if not refresh_token:
        _die("missing Google refresh token; cannot clean up write smoke event")
    return refresh_token


def _google_access_token(data_dir: Path, client_id: str) -> str:
    secret = (data_dir / "secrets" / "google_calendar_client_secret.txt").read_text(
        encoding="utf-8"
    ).strip()
    refresh_token = _load_google_refresh_token(data_dir)
    data = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30.0) as r:
        payload = json.loads(r.read().decode("utf-8"))
    token = str(payload.get("access_token") or "").strip()
    if not token:
        _die("Google token refresh returned no access token")
    return token


def _delete_google_event(data_dir: Path, client_id: str, calendar_id: str, event_id: str) -> None:
    access_token = _google_access_token(data_dir, client_id)
    quoted_calendar = urllib.parse.quote(calendar_id, safe="")
    quoted_event = urllib.parse.quote(event_id, safe="")
    req = urllib.request.Request(
        f"https://www.googleapis.com/calendar/v3/calendars/{quoted_calendar}/events/{quoted_event}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=30.0) as r:
            if int(r.status) not in {200, 204}:
                _die(f"Google event cleanup returned HTTP {r.status}")
    except urllib.error.HTTPError as e:
        _die(f"Google event cleanup failed: HTTP {e.code}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--host-base-url",
        default=os.environ.get("HOST_BASE_URL", "http://127.0.0.1:8765/api/v1"),
        help="MemoryAgent Client API base URL (default: %(default)s)",
    )
    ap.add_argument(
        "--data-dir",
        default=os.environ.get(
            "MEMORYAGENT_DATA_DIR",
            str(Path(__file__).resolve().parents[1] / ".memoryagent"),
        ),
        help="MemoryAgent data dir used to find bearer token (default: repo .memoryagent)",
    )
    ap.add_argument(
        "--token",
        default=os.environ.get("TOKEN"),
        help="Bearer token. Defaults to MEMORYAGENT_DATA_DIR/secrets/bearer.token.",
    )
    ap.add_argument(
        "--client-id",
        default=os.environ.get("GOOGLE_CALENDAR_CLIENT_ID"),
        help="Google OAuth client ID. Also accepted via GOOGLE_CALENDAR_CLIENT_ID.",
    )
    ap.add_argument(
        "--redirect-uri",
        default=os.environ.get("GOOGLE_CALENDAR_REDIRECT_URI"),
        help="OAuth redirect URI registered in Google Cloud. Defaults to host callback.",
    )
    ap.add_argument(
        "--callback-url",
        default=os.environ.get("GOOGLE_CALENDAR_CALLBACK_URL"),
        help="Full callback URL after browser consent. If omitted, the script prompts.",
    )
    ap.add_argument(
        "--start",
        default=os.environ.get("GOOGLE_CALENDAR_SMOKE_START", "2026-01-01T00:00:00Z"),
        help="calendar.list_events start instant.",
    )
    ap.add_argument(
        "--end",
        default=os.environ.get("GOOGLE_CALENDAR_SMOKE_END", "2027-01-01T00:00:00Z"),
        help="calendar.list_events end instant.",
    )
    ap.add_argument(
        "--keyword",
        default=os.environ.get("GOOGLE_CALENDAR_SMOKE_KEYWORD", "meeting"),
        help="Keyword for calendar.search_past_events.",
    )
    ap.add_argument(
        "--write-smoke",
        action="store_true",
        default=os.environ.get("GOOGLE_CALENDAR_WRITE_SMOKE") == "1",
        help="Also create and clean up a Google Calendar test event.",
    )
    ap.add_argument(
        "--write-start",
        default=os.environ.get("GOOGLE_CALENDAR_WRITE_SMOKE_START", "2026-06-01T16:00:00Z"),
        help="Start instant for optional Google write smoke.",
    )
    ap.add_argument(
        "--write-end",
        default=os.environ.get("GOOGLE_CALENDAR_WRITE_SMOKE_END", "2026-06-01T16:15:00Z"),
        help="End instant for optional Google write smoke.",
    )
    ap.add_argument(
        "--disconnect-smoke",
        action="store_true",
        default=os.environ.get("GOOGLE_CALENDAR_DISCONNECT_SMOKE") == "1",
        help="Also disconnect Google at the end and verify Include is off.",
    )
    args = ap.parse_args()

    host = args.host_base_url.rstrip("/")
    data_dir = Path(args.data_dir).expanduser()
    token = args.token or _bearer_from_data_dir(data_dir)
    if not token:
        _die("missing bearer token; start the host once or pass --token")
    if not args.client_id:
        _die("missing Google OAuth client ID; pass --client-id or set GOOGLE_CALENDAR_CLIENT_ID")
    _ensure_client_secret_for_host(data_dir)

    status, payload = _json_request("GET", f"{host}/health", token=token)
    _assert_status("host GET /health", status, {200}, payload)
    _ok("host GET /health")

    redirect_uri = args.redirect_uri or f"{host}/calendar/google/callback"
    status, payload = _json_request(
        "PATCH",
        f"{host}/config",
        token=token,
        body={
            "google_calendar_oauth_client_id": args.client_id,
            "google_calendar_oauth_redirect_uri": redirect_uri,
        },
    )
    _assert_status("host PATCH /config OAuth settings", status, {200}, payload)
    _ok("host PATCH /config OAuth settings")

    status, payload = _json_request("POST", f"{host}/calendar/google/connect", token=token)
    _assert_status("host POST /calendar/google/connect", status, {200}, payload)
    auth_url = str(payload.get("authorization_url") or "")
    if not auth_url:
        _die("connect response missing authorization_url")
    _ok("host POST /calendar/google/connect")

    print("\nOpen this URL in a browser and approve Google Calendar access:\n")
    print(auth_url)
    print("\nAfter consent, the browser should show a small JSON status response.")

    callback_url = args.callback_url
    if callback_url:
        callback_path = _callback_path_from_url(callback_url)
        status, payload = _json_request("GET", f"{host}{callback_path}", token=None)
        _assert_status("host GET /calendar/google/callback", status, {200}, payload)
        _ok("host GET /calendar/google/callback")
    else:
        input("Press Enter here after the browser callback completes...")

    status, payload = _json_request("GET", f"{host}/calendar/google/status", token=token)
    _assert_status("host GET /calendar/google/status", status, {200}, payload)
    if payload.get("status") != "on":
        _die(f"Google Calendar status is not on after callback: {payload}")
    _ok("host GET /calendar/google/status")

    list_result = _tool_invoke(
        host,
        token,
        "calendar.list_events",
        {"start": args.start, "end": args.end},
    )
    _assert_google_not_degraded("calendar.list_events", list_result)

    search_result = _tool_invoke(
        host,
        token,
        "calendar.search_past_events",
        {"keywords": [args.keyword], "before": args.end},
    )
    _assert_google_not_degraded("calendar.search_past_events", search_result)

    if args.write_smoke:
        status, payload = _json_request(
            "POST",
            f"{host}/calendar/events",
            token=token,
            body={
                "title": "MemoryAgent Google write smoke",
                "starts_at": args.write_start,
                "ends_at": args.write_end,
                "calendar_target": "google",
            },
        )
        _assert_status("host POST /calendar/events google", status, {201}, payload)
        event_id = str(payload.get("event_id") or "")
        calendar_id = str(payload.get("calendar_id") or "primary")
        if not event_id or payload.get("calendar_target") != "google":
            _die(f"Google write smoke returned invalid payload: {payload}")
        _ok(f"calendar.create_event: Google event created (event_id={event_id})")
        _delete_google_event(data_dir, args.client_id, calendar_id, event_id)
        _ok("calendar.create_event: Google smoke event cleaned up")

    if args.disconnect_smoke:
        status, payload = _json_request(
            "POST",
            f"{host}/calendar/google/disconnect",
            token=token,
        )
        _assert_status("host POST /calendar/google/disconnect", status, {200}, payload)
        if payload.get("status") != "off" or payload.get("connected") is not False:
            _die(f"Google Calendar disconnect did not turn status off: {payload}")
        _ok("host POST /calendar/google/disconnect")

    suffix = "/list/search"
    if args.write_smoke:
        suffix += "/write"
    if args.disconnect_smoke:
        suffix += "/disconnect"
    _ok(f"Google Calendar OAuth{suffix} smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
