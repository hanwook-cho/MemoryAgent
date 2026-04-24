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
  "deployment": {
    "mode": "standalone",
    "degraded": false,
    "degraded_reason": null,
    "edge_base_url": null
  },
  "llm": {
    "backend": "ollama",
    "reachable": true,
    "model": "llama3.2"
  },
  "index": { "documents": 42, "chunks": 1204 }
}
```

- **`deployment`:** reflects `deployment_mode` from config (see `GET/PATCH /config`). When the mode is not `standalone`, **`degraded`** is **`true`** if the edge URL is missing or `GET /health` on the edge fails; **`degraded_reason`** is a short machine-oriented explanation for clients to surface in UI or logs.

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
  "session_id": "uuid",
  "meta": {
    "degraded": false,
    "degraded_reason": null
  }
}
```

`meta` is always present on `POST /chat`: when `deployment_mode` is not `standalone` and the edge is misconfigured or unreachable, `meta.degraded` is `true` with a stable `degraded_reason`.

### 3.3 Chat (streaming)

`POST /chat/stream` with `Accept: text/event-stream`

Server emits SSE:

- `event: token` — `data: {"text":"..."}`
- `event: citation`
- `event: meta` — `data: {"degraded": false, "degraded_reason": null}` (emitted immediately before `event: done` when the stream completes successfully)
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

`GET /config` — safe subset (no secrets): watched paths, model names, feature flags, `deployment_mode`, optional `edge_base_url` (HTTPS edge Node base URL for distributed modes), optional edge TLS fields (`edge_tls_ca_bundle`, `edge_tls_insecure_skip_verify`, `edge_tls_spki_pins_sha256` for SPKI SHA-256 pinning), optional host→edge path prefixes for remote file ingest (`edge_ingest_path_host_prefix`, `edge_ingest_path_edge_prefix`).

### 3.8 Configuration (write)

`PATCH /config` — may include any subset of `watched_roots`, `watch_ignore_globs`, `watch_debounce_seconds`, `deployment_mode`, `edge_base_url` (empty string clears `edge_base_url`), the edge TLS and `edge_ingest_path_*` fields above (including `edge_tls_spki_pins_sha256` as a JSON array; use `[]` to clear pins). Changing any of those edge-related keys rebinds retrieval/ingest clients in-process.

### 3.9 Markdown mirror

`GET /mirror`, `GET /mirror/{id}`, `PUT /mirror/{id}`.

### 3.10 Tools

`GET /tools`, `POST /tools/invoke`.

### 3.11 Admin/Debug mode (restricted)

These endpoints are for admin/debug workflows and SHOULD be hidden behind explicit UI mode + stronger auth policy. They live under the same **`/api/v1`** prefix and bearer auth as other client routes (e.g. `GET /api/v1/admin/status`).

`GET /admin/status`

- Consolidated diagnostics snapshot (host + optional edge summary): queue depth, active jobs, degraded flags, backend reachability.

`GET /admin/events?level=error&since=<iso>&limit=200`

- Sanitized operational event stream (no secrets/token leakage).

`POST /admin/control/reindex`

- Trigger controlled reindex from client side (host handles local/remote execution policy).

`POST /admin/control/restart`

- Soft restart of workers/adapters without deleting persisted data.

`POST /admin/control/cold-start`

- Rebuild runtime state from persisted stores; no persistent data deletion.

`POST /admin/control/reset-index`

- Clears index stores and triggers full reindex (destructive for index data; source files remain).

`POST /admin/control/factory-reset` (optional, highest risk)

- Wipes local app state/config/index; requires explicit multi-step confirmation.

## 4. Web app static files

- Production: serve built assets from host backend.
- Development: proxy `/api` to backend.

## 5. Security notes

| Risk | Mitigation |
| :--- | :--- |
| Other local processes calling the API | Bearer token + bind controls |
| CSRF from malicious site | Same-origin policy; no broad CORS |
| XSS in web UI | CSP + sanitization |
| Debug/admin misuse | Role/scope-gated endpoints, explicit debug-mode flag, audit log entries |

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

Admin/control endpoints should also use:

- `FORBIDDEN`
- `UNAVAILABLE`
- `TIMEOUT`
