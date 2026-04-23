# MemoryAgent core

Local HTTP API (`FastAPI` + `uvicorn`). See repository root `README.md` and `docs/spec/http-api.md`. **MP1:** `edge_base_url` + `deployment_mode` in `config.json`; `GET /api/v1/admin/status` and `/api/v1/admin/control/*` per `docs/spec/client-api.md` §3.11.

```bash
cd services/core
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
memoryagent-core
```

Or: `uvicorn memoryagent.app:create_app_factory --factory --host 127.0.0.1 --port 8765`

OpenAPI: `http://127.0.0.1:8765/api/v1/docs` (when server is running).

Data directory: `MEMORYAGENT_DATA_DIR` or `.memoryagent/` in the current working directory (`config.json`, `secrets/bearer.token`, Chroma under `store/vector/chroma/`).

**M4 status:** tools and calendar endpoints are available behind bearer auth:

- `GET /api/v1/tools`
- `POST /api/v1/tools/invoke` with `memory.save`, `file.read`, `calendar.list_events`, `calendar.search_past_events`, `calendar.create_event`
- `POST /api/v1/calendar/events` (REST wrapper for event creation)

Core memory/chat routes (`POST /api/v1/memory/entries`, `POST /api/v1/chat`, `GET /api/v1/memory/search`, `POST /api/v1/chat/stream`) also require bearer auth. Runtime requires **Ollama** for embedding + chat (`embed_model` / `chat_model` in config).

`GET /api/v1/memory/search` supports optional metadata filters: `source_kind`, `path_prefix`, `indexed_after`, `indexed_before`.

## Ingestion formats

- Supported for file ingestion/indexing: `.md`, `.txt`, `.pdf`, `.docx`
- PDF uses local text extraction (`pypdf`) and skips image-only PDFs with a clear error.
- DOCX uses paragraph extraction (`python-docx`) and skips docs with no extractable paragraph text.
- Per-format size guardrails apply during extraction (text: 2 MiB, PDF/DOCX: 25 MiB).
- File extraction has a timeout guardrail (default 8s) and logs structured failures.
- `file.read` tool remains text-file focused (`.md`, `.txt`) by design.

## Logging (M5 hardening)

- Core logs write to console and rotating file: `MEMORYAGENT_DATA_DIR/logs/core.log`.
- Rotation defaults: `5_000_000` bytes, `3` backups.
- Optional env overrides:
  - `MEMORYAGENT_LOG_MAX_BYTES`
  - `MEMORYAGENT_LOG_BACKUP_COUNT`
- **Tests:** `pytest tests/test_m5_logging.py` (rotation); `pytest tests/test_m5_structured_errors.py` (HTTP `detail.error.code` / `message` for tool, calendar, memory, chat, and chat-stream paths).
