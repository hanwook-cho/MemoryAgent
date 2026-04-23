# Milestones and acceptance themes

Phases assume **web UI + local API** as the primary product surface ([`architecture.md`](architecture.md)).

**Testing:** See [`test-plan.md`](test-plan.md) for per-milestone **automated** vs **manual** checks; **§10** contains **exact step-by-step manual procedures** (MT-M0-01 … MT-OPT-01).

**OS integration order:** Ship capabilities in the order that matches supported APIs and lowest integration risk—see [`requirement.md`](../../requirement.md) §2.1.1. In short: **manual ingest and RAG (M1) → watched folders (M2) → EventKit calendar/reminders tools (M4) → Notes automation only if prioritized**; defer Mail/IMAP and exclude iMessage/Journal as baseline product features until requirements change.

## M0 — Repository and contracts

- [x] Monorepo layout: `services/core`, `web`, optional `native-bridge`
- [x] OpenAPI or static doc for [`client-api.md`](client-api.md) kept in sync (`GET /api/v1/openapi.json`, `/api/v1/docs`)
- [x] Local config and secrets paths documented (repository `README.md`, [`data-model.md`](data-model.md), `MEMORYAGENT_DATA_DIR`)

**Acceptance:** Core service starts, serves health + static web build, enforces bearer token.

## M1 — RAG loop without OS observation

- [x] Ingest user paste and small test files from a fixture directory (API + pytest; fixture dir optional)
- [x] Chunking + embeddings (**ChromaDB**) + vector upsert
- [x] Chat with citations (non-streaming + **SSE** `/chat/stream`)
- [x] First-run **static** chat welcome and “how to use” per [`onboarding.md`](onboarding.md) (UI-5); dismissal persisted in `localStorage` (or equivalent)

**Acceptance:** From the web UI, user adds a memory entry and retrieves it in a follow-up question with at least one correct citation. On first open of Chat with no messages, the user sees the introduction from `onboarding.md` without an extra LLM request; after dismiss or first user message, it does not reappear until “Show welcome again” (if implemented) or a new `WELCOME_COPY_VERSION`.

## M2 — File system watching

- [x] Configurable roots, ignore globs, debouncing
- [x] Backpressure when many files change

**Acceptance:** Editing a watched Markdown file updates retrieval results within a documented SLA (e.g. &lt; 2 minutes or on-demand “reindex” button).

## M3 — Markdown mirror and audit

- [x] `SOUL.md` / `USER.md` or equivalent mirror strategy per [`data-model.md`](data-model.md)
- [x] Web UI page to view/edit with validation

**Acceptance:** Manual edit propagates to retrieval after sync rules are applied, or user sees a clear “reindex required” path.

## M4 — Tools and MCP

- [x] Tool registry with permission checks per [`permissions-matrix.md`](permissions-matrix.md) (`GET /tools`, `POST /tools/invoke`; `memory.save` registered; capability gate for future OS tools)
- [x] At least one file tool — **`file.read`** via `POST /tools/invoke` (paths under data dir or `watched_roots`; `.md`/`.txt`, max 512 KiB)
- [x] **EventKit-backed** calendar **read** tool — **`calendar.list_events`** via `POST /tools/invoke` + `native-bridge/macos-calendar` (see [`client-api.md`](client-api.md) §3.10)
- [x] **Chat-initiated memory save** — `POST /chat` detects save prefixes on the last user message and ingests like `POST /memory/entries`; `POST /tools/invoke` `memory.save` remains available per [`agent-actions.md`](agent-actions.md)
- [x] **Calendar create** — `calendar.create_event` backed by EventKit; REST `POST /calendar/events` per [`client-api.md`](client-api.md) §3.5
- [x] **Past event search for place reuse** — `calendar.search_past_events` to fill `location` for recurring-style appointments per [`agent-actions.md`](agent-actions.md) §3.4 before falling back to asking the user
- [ ] Optional: Reminders read in the same bridge if Calendars permission model allows

**Acceptance:** Chat can answer from calendar or file search in controlled demo scenarios. User can say “remember that …” and see the fact retrievable in a follow-up question. User can request a new calendar event and see it created (or a clear permission/validation error). For a **dentist-style** appointment with **no address given**, if a **prior** calendar event exists with a location, the proposed event includes that location (or the user is asked for clinic/name per §3.4). Notes automation is not required for M4 acceptance.

## M5 — Product hardening

- [x] NFR-1 / NFR-2 — **verified** (repeatable [`scripts/benchmark_m5.py`](../../scripts/benchmark_m5.py), baseline [`docs/benchmarks/m5-latest.md`](../benchmarks/m5-latest.md); Apple Silicon + OS in report; **NFR-2** within cap in artifact; **NFR-1** baselined for M5 per product review **2026-04-23**)
- [ ] Log rotation, structured errors
- [x] Packaging / distribution model — **decision recorded** ([`m5-packaging-decision.md`](m5-packaging-decision.md)): **no product bundle** now (documented README + `scripts/`); **signed macOS .app** may follow after substantive product work; optional **`launchd`** doc later if desired

**Acceptance:** Repeatable benchmark doc; no unbounded log growth in default config.

## Optional — Native shell

- Menu bar presence, global hotkey, opening web UI in default browser

**Acceptance:** One-click “open MemoryAgent” from menu bar; status reflects core service health.
