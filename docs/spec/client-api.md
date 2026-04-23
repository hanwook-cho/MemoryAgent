# Client API (HTTP/WebSocket)

Client-facing HTTP API for host backend surfaces (`/api/v1/*`). Web, desktop, and mobile clients can all consume this contract.

## 1. Base URL

- Default local: `http://127.0.0.1:<port>/api/v1/`
- Distributed host: `https://<host>/api/v1/`
- Port and bind address come from `config.json` (see [`data-model.md`](data-model.md)).

## 2. Authentication

| Mechanism | Behavior |
| :--- | :--- |
| **Bearer token** | On first launch, core service generates a random token, persisted under `secrets/`. Client must send `Authorization: Bearer <token>` on every request. |
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

`backend` identifies the runtime in use (e.g. `ollama`, `mlx_lm` / `mlx-lm`, `llamacpp`).

### 3.2 Chat (non-streaming)

`POST /chat`

If the **last user** message matches a **save-memory** prefix (case-insensitive), the core **ingests** the remainder like `POST /memory/entries` with `source: chat`, then returns a short confirmation reply.

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

Server emits SSE:

- `event: token` — `data: {"text":"..."}`
- `event: citation`
- `event: done`
- `event: error`

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

### 3.5 Calendar — create event (optional REST surface)

`POST /calendar/events`

Creates an event via EventKit (native bridge). Request/response shapes are defined in [`agent-actions.md`](agent-actions.md).

### 3.6 Search

`GET /memory/search?q=...&limit=20&source_kind=...&path_prefix=...&indexed_after=...&indexed_before=...`

Optional filters:

- `source_kind`
- `path_prefix`
- `indexed_after` / `indexed_before`

### 3.7 Configuration (read)

`GET /config` — safe subset (no secrets): watched paths, model names, feature flags.

### 3.8 Configuration (write)

`PATCH /config` — may include any subset of `watched_roots`, `watch_ignore_globs`, `watch_debounce_seconds`.

### 3.9 Markdown mirror

`GET /mirror`, `GET /mirror/{id}`, `PUT /mirror/{id}`.

### 3.10 Tools

`GET /tools`, `POST /tools/invoke`.

## 4. Web app static files

- Production: serve built assets from host backend.
- Development: proxy `/api` to backend.

## 5. Security notes

| Risk | Mitigation |
| :--- | :--- |
| Other local processes calling the API | Bearer token + bind controls |
| CSRF from malicious site | Same-origin policy; no broad CORS |
| XSS in web UI | CSP + sanitization |

## 6. Error shape

```json
{
  "error": {
    "code": "MODEL_UNAVAILABLE",
    "message": "Local inference engine not reachable."
  }
}
```

Codes include: `UNAUTHORIZED`, `VALIDATION`, `MODEL_UNAVAILABLE`, `INDEX_BUSY`, `PERMISSION_DENIED`.
