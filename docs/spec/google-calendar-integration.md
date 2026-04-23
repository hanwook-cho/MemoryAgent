# Google Calendar integration — product direction

This document records **calendar source strategy** and **delivery order**. Dates are intentionally omitted; phases are ordered.

## User-facing rule (normative)

The user has an explicit control (e.g. toggle or setting): **Include Google Calendar**.

| User selection | Supported calendar sources |
| :--- | :--- |
| **Include Google Calendar** is **off** (default) | **Local calendar only** (platform-native, e.g. macOS EventKit where available). **No Google Calendar API calls.** OAuth tokens may remain stored (encrypted/keychain) for faster re-enable; see **Configuration and persistence** below. |
| **Include Google Calendar** is **on** | **Both** local calendar **and** Google Calendar are supported. **“On” only after OAuth completes successfully** (see inclusion flow below). |

Google access is never implied: turning **Include** on **starts OAuth**; the product does not treat Google as included until **consent succeeds** and tokens are available.

### Inclusion flow (normative)

1. User enables **Include Google Calendar** → **OAuth starts** (consent / browser or embedded flow as implemented).
2. If OAuth **succeeds** → state becomes **on** (Google Calendar is active alongside local).
3. If OAuth **fails or the user cancels** → state returns to **off** (or a neutral “not connected” state that behaves as **local only** for calendar features; implementation must not call Google without a valid connection).

## Agreed product decisions

### Reads (both sources on)

- Merge results from local and Google, **sorted by time** (single chronological list).
- **Do not hide duplicates** by default: if the same real-world event could appear twice, **show both** entries and **label each** with which calendar it came from (e.g. **Local** vs **Google** / calendar name).

### Writes (create / update when both exist)

- If the user (or caller) **does not specify** which calendar to use, the client **must ask** the user to pick **local vs Google** (or a specific calendar within those systems) before performing the write.

### Failure when Include is on

- **Soft degrade:** if Google is unavailable (network, quota, revoked token), **local calendar remains usable**; surface a **clear, user-visible** notice that Google results are missing or stale. Do not fail the whole session if local still works.

### Platform scope (v1)

- **Local calendar v1:** **macOS EventKit** only.
- **Other platforms (Linux, Windows, …):** not decided for v1; revisit when those hosts ship (may be **Google-only**, **none**, or a different native adapter per OS).

### OAuth scopes (item 4 — clarified)

- **Read path first:** `https://www.googleapis.com/auth/calendar.readonly` until Google-backed **create/update** is implemented.
- **When implementing Google writes:** add `https://www.googleapis.com/auth/calendar.events` (or broader only if strictly needed). Wider scopes can trigger **Google OAuth app verification**; plan UX and compliance before promising write features broadly.

### Logging redaction (item 5 — clarified)

Operational logs must **not** contain secrets or usable credentials, for example:

- Never log **refresh tokens**, **access tokens**, **authorization codes**, or full **OAuth redirect URLs** carrying codes.
- Prefer stable internal correlation IDs over raw Google account identifiers in logs unless necessary and policy-approved.

This reduces risk if log files are copied or leaked.

### Configuration and persistence (item 7 — normative, decided)

**Decided behavior:** **Include** is a *feature toggle*; **Disconnect Google** is *account removal*.

| Setting / state | Meaning |
| :--- | :--- |
| **Include Google Calendar — off** | **Never call Google** for calendar; **local only**. **Retain** OAuth tokens **encrypted at rest** (or in OS keychain) so the user can turn **Include** back **on** without repeating full consent when the refresh token is still valid. If refresh fails on next **on**, run OAuth again. |
| **Include Google Calendar — on** | OAuth has completed successfully; use **both** local and Google per the rules above. |
| **Disconnect Google** (explicit control in settings whenever Google has been connected) | **Revoke** access at Google when the API allows it, **delete** stored tokens locally, and set **Include** to **off**. This is the “remove Google from this device/app” path. |

**Rationale:** **Include off** means “do not use Google in calendar answers right now” without forcing another OAuth dance. **Disconnect** means “remove credentials / this account.”

A future optional **“Include off and delete tokens”** control may be added for stricter privacy; it is **not** part of the default v1 behavior unless compliance requires it.

## Decision summary (delivery order)

1. **Implement Google Calendar first** (new work): OAuth, token lifecycle, Google Calendar API usage, and client/host UX for the **Include Google Calendar** path.
2. **Verification gate (“Google inclusion”)**: End-to-end proof that Google-backed calendar operations are reliable, secure, and observable before treating Google as a supported production path.
3. **Steady-state product behavior** matches the table above: **off** → local only; **on** → local **and** Google together.

## Rationale

- Validates the harder path early: **cloud OAuth**, quotas, errors, and revocation—without blocking local-only users.
- Keeps **trust boundaries clear**: Google access is never implicit; opt-in is explicit.

## Phases (no target dates)

### Phase 1 — Google Calendar (first delivery)

- Google Cloud project, OAuth client, consent screen.
- Minimal scopes to start (prefer `https://www.googleapis.com/auth/calendar.readonly`; add `https://www.googleapis.com/auth/calendar.events` when create/update is required).
- Backend: store refresh tokens securely; call Calendar API for list/search (and events write when in scope).
- Client: **Include Google Calendar** (starts OAuth; **on** only after success); **Disconnect Google** in settings when a Google account has been connected; visible state: off | OAuth in progress | on (connected).

### Phase 2 — Verification gate (“Google inclusion”)

Criteria examples (adjust as you implement):

- Connect and disconnect flows work; revoked tokens fail gracefully.
- Error surfaces are user-safe (no token leakage in logs/UI).
- Basic load behavior acceptable (latency, rate limits); degraded messaging when Google is unavailable.
- Optional: checklist signoff in [`mp1-verification-checklist.md`](mp1-verification-checklist.md) style for this slice.

### Phase 3 — Dual calendar support (matches user-facing rule)

- **Include off:** local only; no Google Calendar API calls.
- **Include on (OAuth success):** query **both** sources; **sort by time**; **label** each row with source (local vs Google / calendar name); **soft degrade** if Google fails.
- **Writes:** if target calendar unspecified, **prompt user** to choose local vs Google (or specific calendar) before proceeding.

## Out of scope (near term)

- **Google Keep** and other Google surfaces without stable public APIs—see prior roadmap discussions; not part of this calendar-first track unless separately specified.

## Related documents

- Host/tool surface and HTTP contracts: [`client-api.md`](client-api.md)
- Overall architecture: [`architecture.md`](architecture.md)
- Agent/tool policy: [`agent-actions.md`](agent-actions.md)
