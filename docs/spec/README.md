# MemoryAgent — detailed specification (index)

This folder expands the high-level [`requirement.md`](../../requirement.md) into implementable contracts. **Development:** open PRs against **`ma-dist`** (see [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md)). **OS integration order** (files → EventKit calendar/reminders → optional Notes; defer Mail/IMAP pattern; no iMessage/Journal baseline) is defined in **requirement §2.1.1**. Read in this order:

| Document | Contents |
| :--- | :--- |
| [`architecture.md`](architecture.md) | Processes, components, data flow, web app vs native helper |
| [`prd-mp1-distributed.md`](prd-mp1-distributed.md) | Clean product requirements document for MP1 distributed architecture foundation |
| [`srs-mp1-distributed.md`](srs-mp1-distributed.md) | Software requirements specification for MP1 distributed architecture foundation |
| [`data-model.md`](data-model.md) | Memory records, chunks, embeddings, Markdown sync |
| [`client-api.md`](client-api.md) | Client API (HTTP/WebSocket) for web, desktop, and mobile clients |
| [`node-api.md`](node-api.md) | Node API (HTTP/HTTPS) for Host Backend ↔ Edge Node control/retrieval/ingest |
| [`agent-actions.md`](agent-actions.md) | Chat-triggered **save to memory** and **create calendar event** |
| [`onboarding.md`](onboarding.md) | First-run chat welcome copy, dismissal, client persistence |
| [`permissions-matrix.md`](permissions-matrix.md) | macOS capabilities, when to ask, fallbacks |
| [`milestones.md`](milestones.md) | Phased delivery and acceptance themes |
| [`test-plan.md`](test-plan.md) | Per-milestone tests and **automation** guidance (API, E2E, macOS-only) |
| [`prerequisites.md`](prerequisites.md) | Required macOS software, local LLM, dev tooling |
| [`pdf-docx-index-plan.md`](pdf-docx-index-plan.md) | Phased plan for index DB + PDF/DOCX ingestion support |
| [`document-format-vnext-plan.md`](document-format-vnext-plan.md) | Next-version roadmap for additional document formats (xlsx/pptx/OCR/email/etc.) |
| [`distributed-future-plan.md`](distributed-future-plan.md) | Future architecture plan across host OS, optional edge index node, hybrid retrieval, and iOS companion |
| [`mp1-pr1.md`](mp1-pr1.md) | MP1 first code PR: local backend adapters + `deployment_mode` |
| [`mp1-verification-checklist.md`](mp1-verification-checklist.md) | Pre-implementation GO/NO-GO checklist before MP1 coding |
| [`google-calendar-integration.md`](google-calendar-integration.md) | Google Calendar + local EventKit product rules and phases |

**Primary interaction:** users operate a **local web application** in the browser, backed by an on-device API. **Inference** uses a **Mac-local LLM** (e.g. Ollama, **mlx-lm** / MLX), not a remote API, for default operation. Optional native surfaces (menu bar, CLI) complement but are not required for core chat and memory audit flows.

Current implementation status: M0-M4 core goals are implemented, including EventKit tools for `calendar.list_events`, `calendar.search_past_events`, and `calendar.create_event` plus REST `POST /api/v1/calendar/events`; optional Reminders integration remains open.

Terminology glossary: see the **Terminology** section in [`distributed-future-plan.md`](distributed-future-plan.md) for canonical definitions of ingest/reindex/retrieval/backend contracts and control/data plane.

## Current implemented capabilities

- Local web UI + local API with bearer authentication (`/api/v1/*`).
- Memory ingest/retrieval with citations, chat + chat streaming.
- Folder-based ingestion with watcher + ignore globs.
- Supported ingestion formats: `.md`, `.txt`, `.pdf`, `.docx`.
- Incremental indexing via `store/file_index.db` (skip unchanged files).
- Metadata-aware retrieval filters (`source_kind`, `path_prefix`, `indexed_after`, `indexed_before`), including chat-side use for prompts like "last month".
- Safety guardrails in extraction path (per-format max size + timeout/failure logging).
- Implementation trail for format/index work: [`pdf-docx-index-plan.md`](pdf-docx-index-plan.md).
