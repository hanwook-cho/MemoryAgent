# MP1 — PR-1 (first implementation PR)

Status: **GO** (post checklist). This document is the canonical description of **PR-1** scope.

## Title

**MP1-PR1: Backend interface scaffolding + deployment mode config (standalone unchanged)**

## Goal

Land the **three backend contracts** from the distributed architecture specs and a **deployment/mode configuration** seam, while keeping **runtime behavior identical** to the pre-MP1 baseline: same chat, RAG, watcher, and local-only data paths.

## Non-goals (not in PR-1)

- Edge Node runtime, Node API server/client, or HTTPS calls to a remote index.
- Google Calendar OAuth or merging local + Google reads (see [`google-calendar-integration.md`](google-calendar-integration.md); separate PRs).
- Admin/Debug HTTP endpoints (unless already present; no new destructive control in PR-1).
- Changing external Client API response shapes in a breaking way.

## Rationale

`create_app` in the host currently wires `VectorStore`, `RagService`, and `LlmClient` directly. PR-1 introduces **narrow abstractions** so later PRs can add remote retrieval/ingest and mode-specific wiring **without** a second full rewrite of the FastAPI composition root.

## Suggested implementation shape

1. **New module(s)** (example layout; names may match codebase conventions):
   - `RetrievalBackend`: protocol or ABC for operations the orchestrator needs for **read/search** (minimal surface first; extend as needed).
   - `IngestBackend`: protocol for **ingest**; may be the same concrete object as retrieval in v1 if ingest and search share one store today.
   - `LlmBackend`: protocol aligned with existing `LlmClient` (`chat` / stream as implemented).

2. **Local implementations** that **delegate** to existing `RagService` / `LlmClient` (and related types). PR-1 should **not** move large chunks of logic out of `rag_service.py` unless necessary for typing; delegation keeps risk low.

3. **Configuration** (extend `config_store` / Pydantic models):
   - Add `deployment_mode` (or equivalent) with default **`standalone`**.
   - Non-standalone values: either **ignored with a clear log** or rejected at startup—pick one policy and document it; default must remain **standalone** with **no behavior change**.

4. **Wiring** in `create_app` (or a small factory):
   - Construct backends once; inject into the code path that serves health, memory search/ingest, and mirror ingest so **standalone** still uses local vector store + local LLM exactly as today.
   - `POST /chat` and `POST /chat/stream` remain on `RagService` for PR-1 (orchestration + tools + streaming); adapters cover retrieval/ingest/LLM seams for later extraction.
   - `app.state.mp1_backends` holds `RuntimeBackends` for tests and future orchestrator injection.

## Acceptance criteria

- All **existing automated tests** pass; no intentional regressions in default mode.
- **Manual smoke** (or scripted smoke if available): health, chat, memory search, file ingest path unchanged for default config.
- **New tests** (minimal):
  - Default `deployment_mode` resolves to **standalone** and uses local delegation backends.
  - Unknown/future mode policy is covered by one test if such values are accepted in config files.

**Test plan mapping:** repeatable rows for this PR live in [`test-plan.md`](test-plan.md) **§7.1**. The [`mp1-verification-checklist.md`](mp1-verification-checklist.md) is **spec/design** sign-off **before** code; §7.1 is **verification of PR-1 code** after GO.

## References

- Architecture roles and direction: [`distributed-future-plan.md`](distributed-future-plan.md), [`architecture.md`](architecture.md)
- Pre-implementation gate: [`mp1-verification-checklist.md`](mp1-verification-checklist.md)
- Product scope: [`prd-mp1-distributed.md`](prd-mp1-distributed.md)

## Follow-on PRs (not PR-1)

Document only as pointers; scope is defined elsewhere or in future PR docs.

- PR-2+: remote `RetrievalBackend` / `IngestBackend` adapters, degraded metadata, Node API client.
- Parallel track: Google Calendar OAuth and read path per [`google-calendar-integration.md`](google-calendar-integration.md).
