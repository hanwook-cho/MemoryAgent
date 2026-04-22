# Local HTTP API (web application)

The **web UI** is a single-page application that communicates only with this API on the same machine. All routes assume **local use**; see §5 Security.

## 1. Base URL

- Default: `http://127.0.0.1:<port>/api/v1/`
- Port and bind address come from `config.json` (see [`data-model.md`](data-model.md)).

## 2. Authentication

| Mechanism | Behavior |
| :--- | :--- |
| **Bearer token** | On first launch, core service generates a random token, persisted under `secrets/`. The web app must send `Authorization: Bearer <token>` on every request. |
| **Session cookie** | Optional alternative: `HttpOnly`, `SameSite=Strict`, `Secure=false` on localhost MVP. |

Unauthorized requests return **401** with no body details suitable for fingerprinting.

## 3. REST endpoints (normative sketch)

### 3.1 Health

`GET /health`

Response `200`:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "llm": {
    "backend": "ollama",
    "reachable": true,
    "model": "llama3.2"
  },
  "index": { "documents": 42, "chunks": 1204 }
}
```

`backend` identifies the **on-device** runtime in use (e.g. `ollama`, `mlx_lm` / `mlx-lm`, `llamacpp`). All are expected to be **local** to the machine (in-process counts as reachable); there is no cloud inference field in core health.

### 3.2 Chat (non-streaming)

`POST /chat`

If the **last user** message matches a **save-memory** prefix (case-insensitive), the core **ingests** the remainder like `POST /memory/entries` with `source: chat`, then returns a short **confirmation** reply (no RAG citations for that turn). Prefixes include: `remember that`, `remember:`, `note that`, `note:`, `save to memory:`, `memorize:` (optional leading `please `). Otherwise, normal RAG chat applies.

Request:

```json
{
  "messages": [
    { "role": "user", "content": "What did I save about project X?" }
  ],
  "session_id": "optional-uuid"
}
```

Response `200`:

```json
{
  "reply": "...",
  "citations": [
    { "chunk_id": "...", "snippet": "...", "score": 0.82 }
  ],
  "session_id": "uuid"
}
```

### 3.3 Chat (streaming)

`POST /chat/stream` with `Accept: text/event-stream`

Server emits **SSE** events:

- `event: token` — `data: {"text":"..."}`  
- `event: citation` — optional mid-stream  
- `event: done` — `data: {"session_id":"..."}`  
- `event: error` — `data: {"code":"..."}`  

(WebSocket may be added later as an alternative; keep message schema identical.)

### 3.4 Memory — manual entry

`POST /memory/entries`

```json
{
  "text": "Remember: my dentist is Dr. Lee.",
  "tags": ["health"],
  "source": "web_ui"
}
```

Response `201` with `document_id` and ingestion job id.

Chat-initiated saves should use this endpoint (or the same server-side handler) per [`agent-actions.md`](agent-actions.md).

### 3.5 Calendar — create event (optional REST surface)

`POST /calendar/events`

Creates an event via **EventKit** (native bridge). Same permission rules as [`agent-actions.md`](agent-actions.md) §4.2.

Request / response shapes are defined in **`agent-actions.md`**; core service returns `201` with `event_id` and normalized times, or `PERMISSION_DENIED` / `VALIDATION`.

### 3.6 Search (debug / power users)

`GET /memory/search?q=...&limit=20`

Returns ranked chunks with scores for UI “sources” panel.

### 3.7 Configuration (read)

`GET /config` — safe subset (no secrets): watched paths, model names, feature flags.

Optional **`ui`** object (when implemented) for cross-client parity:

```json
{
  "host": "127.0.0.1",
  "port": 8765,
  "chat_model": "llama3.2",
  "embed_model": "nomic-embed-text",
  "ollama_base_url": "http://127.0.0.1:11434",
  "watched_roots": [],
  "watch_ignore_globs": ["**/.git/**", "**/node_modules/**", "**/.DS_Store"],
  "watch_debounce_seconds": 1.5,
  "ui": {
    "chat_welcome_dismissed": false,
    "chat_welcome_version": "1"
  }
}
```

The web app may rely on **`localStorage`** alone for first-run welcome per [`onboarding.md`](onboarding.md); the `ui` fields are optional for future CLI or multi-surface sync.

### 3.8 Configuration (write)

`PATCH /config` — body may include any subset of `watched_roots`, `watch_ignore_globs`, `watch_debounce_seconds`. **Watched roots** must each be an existing directory at patch time. The service saves `config.json` and restarts filesystem watchers. May include `ui.chat_welcome_dismissed` / `ui.chat_welcome_version` when the core service persists UI preferences.

### 3.9 Markdown mirror (`mirror/USER.md`, `mirror/SOUL.md`)

Human-readable audit files under the data directory (`mirror/`). Optional YAML front matter + Markdown body per [`data-model.md`](data-model.md) §4. **Only the Markdown body** (below the closing `---`) is chunked and embedded; front matter is validated but not indexed.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/mirror` | List `{ "mirrors": [ { "id": "user" \| "soul", "filename", "title" } ] }`. Creates defaults if missing. |
| `GET` | `/mirror/{id}` | `id` is `user` or `soul`. Returns full file text, `path`, `document_id` (stable id for the file URI). |
| `PUT` | `/mirror/{id}` | Body `{ "content": "<full file>" }`. Validates front matter; writes the file; **reindexes** body into the vector store. |

On core startup, default mirror files are created if absent and **indexed** (same pipeline as `PUT`).

### 3.10 Tools (registry + invoke)

Aligned with [`agent-actions.md`](agent-actions.md). The orchestrator (or tests) can call tools over HTTP; each tool uses the same side effects as the equivalent manual API where applicable.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/tools` | List `{ "tools": [ { "name", "description", "required_capability" } ] }`. `required_capability` is `null` when no OS prompt is needed (e.g. `memory.save`). |
| `POST` | `/tools/invoke` | Body `{ "tool": "<name>", "arguments": { ... } }`. Success: `{ "ok": true, "result": { ... } }`. Errors: **404** unknown tool, **400** `VALIDATION`, **403** `PERMISSION_DENIED` (when a capability is required but not granted). |

**`memory.save`** — arguments: `text` (required), `tags` (optional array of strings), `source` (optional, default `chat`). Same ingest pipeline as `POST /memory/entries`.

**`file.read`** — arguments: `path` (required string, absolute or user-expanded). Reads **UTF-8** **`.md`** or **`.txt`** only. The resolved path must lie under the app **data directory** (`MEMORYAGENT_DATA_DIR`) **or** under a directory listed in **`watched_roots`** in `config.json`. Rejects paths outside those trees, non-files, wrong extension, or files larger than **512 KiB** (`VALIDATION`).

**`calendar.list_events`** — arguments: **`start`**, **`end`** (required ISO-8601 strings). **macOS only:** runs the native **`memoryagent-calendar`** helper (EventKit). Set **`MEMORYAGENT_CALENDAR_BRIDGE`** to the executable path, or build `native-bridge/macos-calendar` (`swift build -c release`) so the core can find `.build/*/release/memoryagent-calendar`. Returns `{ "events": [ { "event_id", "title", "starts_at", "ends_at", "location", "all_day" } ], "count" }`. **`403`** / **`PERMISSION_DENIED`** if the user denies Calendars access.

**`calendar.search_past_events`** — arguments: **`keywords`** (required array of strings); optional **`before`** (ISO-8601 instant, default now UTC), **`lookback_days`** (default **730**), **`limit`** (default **20**, max **100**). Returns past events in the window ending at **`before`**, matched if any keyword appears in title, notes, or location (case-insensitive), sorted by **`starts_at`** descending. Events include optional **`notes`** when present (truncated). **`403`** / **`PERMISSION_DENIED`** if Calendars access is denied.

**`calendar.create_event`** — arguments: **`title`**, **`starts_at`** (required ISO-8601); optional **`ends_at`** (default **starts_at + 1 hour**), **`all_day`**, **`notes`**, **`location`**, **`calendar_id`**. Returns `{ "event_id", "title", "starts_at", "ends_at" }`. Same native bridge as above. **`403`** / **`PERMISSION_DENIED`** if denied.

**REST:** `POST /api/v1/calendar/events` with the same fields as **`calendar.create_event`** (JSON body per [`agent-actions.md`](agent-actions.md) §4.2); response **201** with `{ "event_id", "title", "starts_at", "ends_at" }`, or **`403`** / **`422`** validation.

## 4. Web app static files

- **Production:** Serve `index.html` and assets from the core service at `/` with `Cache-Control` appropriate for hashed filenames.
- **Development:** Vite (or similar) proxy `/api` to the core service to avoid CORS complexity.

## 5. Security notes

| Risk | Mitigation |
| :--- | :--- |
| Other local processes calling the API | Bearer token + bind to loopback by default |
| CSRF from malicious site | Same-origin policy for API; do not enable CORS for arbitrary origins |
| XSS in web UI | Standard CSP and sanitization for rendered Markdown |

## 6. Error shape

```json
{
  "error": {
    "code": "MODEL_UNAVAILABLE",
    "message": "Local inference engine not reachable."
  }
}
```

Codes to define in implementation: `UNAUTHORIZED`, `VALIDATION`, `MODEL_UNAVAILABLE`, `INDEX_BUSY`, `PERMISSION_DENIED` (OS tool).
