# Google Calendar OAuth Setup

This guide records the live setup path used for MemoryAgent Google Calendar validation.

## 1. Google Cloud Project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project for MemoryAgent local testing.
3. Go to **APIs & Services → Library**.
4. Enable **Google Calendar API** (`calendar-json.googleapis.com`).

If this is skipped, MemoryAgent can complete OAuth but calendar reads will soft-degrade with `SERVICE_DISABLED` / `accessNotConfigured`.

## 2. OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Configure the app name, support email, and developer contact.
3. Keep the app in **Testing** mode for local development.
4. Add your Gmail / Google Workspace account under **Test users**.

Without the test user entry, Google blocks consent with “app has not completed the Google verification process.”

## 3. OAuth Client

Create an OAuth client:

- **Application type:** `Web application`
- **Authorized JavaScript origins:** not required for this backend flow
- **Authorized redirect URI:**

```text
http://127.0.0.1:8765/api/v1/calendar/google/callback
```

Copy the generated **Client ID** and **Client secret**. The client ID looks like:

```text
...apps.googleusercontent.com
```

## 4. Local Secret Storage

Do not commit Google OAuth secrets.

Preferred local paths:

- Client ID: environment variable `GOOGLE_CALENDAR_CLIENT_ID`, or API config field `google_calendar_oauth_client_id`.
- Client secret: environment variable `GOOGLE_CALENDAR_CLIENT_SECRET`, or `.memoryagent/secrets/google_calendar_client_secret.txt`.

The backend needs the client secret during the browser callback. `scripts/google-calendar-smoke.py` copies an env-provided secret into `.memoryagent/secrets/google_calendar_client_secret.txt` so the already-running backend can read it.

If a client secret is pasted into chat, logs, screenshots, or committed files, rotate it in Google Cloud.

## 5. Smoke Test

Start the backend:

```bash
./scripts/run.sh
```

In a second terminal:

```bash
export GOOGLE_CALENDAR_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_CALENDAR_CLIENT_SECRET="your-client-secret"
services/core/.venv/bin/python scripts/google-calendar-smoke.py
```

The script will:

1. Patch the local host config with the client ID and redirect URI.
2. Start the OAuth flow and print the Google consent URL.
3. Wait while you approve access in the browser.
4. Verify `calendar.list_events` and `calendar.search_past_events` have a non-degraded Google source.

New OAuth grants request `https://www.googleapis.com/auth/calendar.events` so Google-backed create can be tested after reconnecting. Older refresh tokens created during the read-only phase may need Disconnect + Connect before Google writes work.

To include write validation and automatic cleanup of the smoke event:

```bash
GOOGLE_CALENDAR_WRITE_SMOKE=1 services/core/.venv/bin/python scripts/google-calendar-smoke.py
```

To also validate Disconnect Google at the end (revokes the token best-effort, deletes local token storage, and leaves Include off):

```bash
GOOGLE_CALENDAR_WRITE_SMOKE=1 GOOGLE_CALENDAR_DISCONNECT_SMOKE=1 services/core/.venv/bin/python scripts/google-calendar-smoke.py
```

Expected success:

```text
OK: host GET /calendar/google/status
OK: calendar.list_events: Google source checked
OK: calendar.search_past_events: Google source checked
OK: Google Calendar OAuth/list/search smoke passed
```

Expected write smoke additions:

```text
OK: calendar.create_event: Google event created
OK: calendar.create_event: Google smoke event cleaned up
OK: Google Calendar OAuth/list/search/write smoke passed
```

Expected disconnect smoke addition:

```text
OK: host POST /calendar/google/disconnect
OK: Google Calendar OAuth/list/search/write/disconnect smoke passed
```

## 6. Troubleshooting

| Error | Likely cause | Fix |
| :--- | :--- | :--- |
| `invalid_client` / “OAuth client was not found” | Wrong value used as client ID, or not an OAuth client ID | Use the **OAuth 2.0 Client ID** ending in `.apps.googleusercontent.com`. |
| “provided client secret is invalid” | Secret does not match the selected OAuth client | Copy the client secret from the same Web OAuth client; update `.memoryagent/secrets/google_calendar_client_secret.txt`. |
| “has not completed Google verification process” | App is in Testing mode and account is not a test user | Add the Gmail account under OAuth consent screen → Test users. |
| `SERVICE_DISABLED` / `accessNotConfigured` | Google Calendar API is disabled for the project | Enable **Google Calendar API** in APIs & Services → Library, then wait a few minutes. |
| Browser callback returns `Unauthorized` | Backend is stale from before the public callback route change | Restart `./scripts/run.sh`. |
| Google source `degraded: true` with local events present | Google API failed, but local EventKit worked | Inspect `sources.google.degraded_reason`; local fallback is expected behavior. |
