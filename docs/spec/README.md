# MemoryAgent — detailed specification (index)

This folder expands the high-level [`requirement.md`](../../requirement.md) into implementable contracts. **OS integration order** (files → EventKit calendar/reminders → optional Notes; defer Mail/IMAP pattern; no iMessage/Journal baseline) is defined in **requirement §2.1.1**. Read in this order:

| Document | Contents |
| :--- | :--- |
| [`architecture.md`](architecture.md) | Processes, components, data flow, web app vs native helper |
| [`data-model.md`](data-model.md) | Memory records, chunks, embeddings, Markdown sync |
| [`http-api.md`](http-api.md) | Local HTTP/WebSocket API for the **web-based UI** |
| [`agent-actions.md`](agent-actions.md) | Chat-triggered **save to memory** and **create calendar event** |
| [`onboarding.md`](onboarding.md) | First-run chat welcome copy, dismissal, client persistence |
| [`permissions-matrix.md`](permissions-matrix.md) | macOS capabilities, when to ask, fallbacks |
| [`milestones.md`](milestones.md) | Phased delivery and acceptance themes |
| [`test-plan.md`](test-plan.md) | Per-milestone tests and **automation** guidance (API, E2E, macOS-only) |
| [`prerequisites.md`](prerequisites.md) | Required macOS software, local LLM, dev tooling |

**Primary interaction:** users operate a **local web application** in the browser, backed by an on-device API. **Inference** uses a **Mac-local LLM** (e.g. Ollama, **mlx-lm** / MLX), not a remote API, for default operation. Optional native surfaces (menu bar, CLI) complement but are not required for core chat and memory audit flows.

Current implementation status: M0-M4 core goals are implemented, including EventKit tools for `calendar.list_events`, `calendar.search_past_events`, and `calendar.create_event` plus REST `POST /api/v1/calendar/events`; optional Reminders integration remains open.
