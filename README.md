# MemoryAgent

**MemoryAgent** is a **local-first** memory and retrieval assistant for **macOS**. You use a **local web UI** backed by an on-device **HTTP API** (by default on **127.0.0.1**) for chat with **RAG** over files you choose to watch and facts you save; **embeddings and chat** run **on the Mac** by default (no cloud required for core use). **Tools** (for example **EventKit** calendar read/create) use a small **Swift bridge** where the OS requires it. Formal requirements: [`requirement.md`](requirement.md); API, architecture, and milestones: [`docs/spec/`](docs/spec/README.md).

## Documentation and roadmap

Planned **distributed / MP1** work (multi-host, optional edge node, Client vs Node API), **PRD/SRS**, verification checklists, **Google Calendar** integration rules, and milestone tests all live under **[`docs/spec/README.md`](docs/spec/README.md)** (indexed table—not “local app only”). The **full-product phased roadmap** is in **[`docs/spec/prd-full-product.md`](docs/spec/prd-full-product.md)**; **software requirements (SHALL)** across phases are in **[`docs/spec/srs-full-product.md`](docs/spec/srs-full-product.md)**. **[`docs/spec/prd-mp1-distributed.md`](docs/spec/prd-mp1-distributed.md)** / **[`docs/spec/srs-mp1-distributed.md`](docs/spec/srs-mp1-distributed.md)** scope **MP1 only**.

**On GitHub:** the **front page** follows the **default** branch (`main`). **`main` is not continuously merged from `ma-dist`**—promotion happens only when **`ma-dist` is fully complete** for a release milestone ([`CONTRIBUTING.md`](CONTRIBUTING.md)). For the latest integration **README** and **`docs/spec/`**, select branch **`ma-dist`** in the branch menu.

## Stack (M4)

- **Vector DB:** [Chroma](https://www.trychroma.com/) (persistent under `MEMORYAGENT_DATA_DIR/store/vector/chroma`).
- **Embeddings / chat:** [Ollama](https://ollama.com/) (`nomic-embed-text`, chat model from `config.json`).

## Status snapshot

- M0-M3 complete (core API, RAG loop, watcher, mirror/audit UI).
- M4 complete for tools + calendar EventKit path: `calendar.list_events`, `calendar.search_past_events`, `calendar.create_event`.
- REST wrapper for calendar create is live: `POST /api/v1/calendar/events`.
- Optional M4 remainder: Reminders read integration.
- Document format expansion plan (index DB + PDF/DOCX): `docs/spec/pdf-docx-index-plan.md` (index DB + PDF + DOCX + metadata-aware retrieval now implemented).

## M0 / M4 quick start

**Prerequisites:** Python 3.11+, Node.js 20+ (for web build), optional [Ollama](https://ollama.com) for `llm.reachable` in `/health`. One-shot: [`scripts/setup-dev.sh`](scripts/setup-dev.sh).

From the **repository root**, run **one line at a time** (or use the single chained block below). Do **not** paste comment lines (`# …`) as commands, and always put **`&&`** between shell commands when joining them on one line.

**First-time setup**

```bash
./scripts/setup-dev.sh
cd services/core && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cd ../../web && npm ci && npm run build
```

**One-shot run** (creates `services/core/.venv` and runs `npm run build` if missing; then starts the server):

```bash
cd /path/to/MemoryAgent
./scripts/run.sh
```

**Manual start** (from repo root; keeps `.memoryagent` next to the clone)

```bash
cd /path/to/MemoryAgent
export MEMORYAGENT_DATA_DIR="${MEMORYAGENT_DATA_DIR:-$PWD/.memoryagent}"
services/core/.venv/bin/memoryagent-core
```

Open **http://127.0.0.1:8765/** — static UI loads from `web/dist`. The first log line prints the **bearer token**; paste it in the page to call `GET /api/v1/config`.

### Troubleshooting

| Problem | What to do |
| :--- | :--- |
| **`vite build` / `Could not resolve "#/index.html"` / root contains `#`** | Run **only** `npm run build` inside `web/` with **no** extra words after it. If you accidentally created a folder named `#`, remove it: `rm -rf web/\#` |
| **`zsh: command not found: #`** | A line with only `#` was executed; skip comment lines when pasting. |
| **`pip install ...cd` or `buildcd`** | Missing `&&` between commands — don’t concatenate lines from the README without `&&`. |
| **Rebuild web after UI edits** | `cd web && npm run build` |
| **Calendar tools unavailable** (`calendar.list_events`, `calendar.search_past_events`, `calendar.create_event`) | On macOS, build the helper: `./scripts/build-calendar-bridge.sh` (requires Xcode / Swift). Optionally set `MEMORYAGENT_CALENDAR_BRIDGE` to the `memoryagent-calendar` binary. |
| **Calendar permission denied from API but manual helper works** | TCC is per host app/process. Run `./scripts/run.sh` from Terminal.app once (or enable Calendar for Cursor/Python host process) and retry. |

- **API docs (OpenAPI):** http://127.0.0.1:8765/api/v1/docs  
- **Health (no auth):** `GET /api/v1/health` (includes `deployment` / degraded flags when config uses non-`standalone` modes; see OpenAPI)

**Web dev (Vite proxy):** `cd web && npm run dev` → uses proxy to port 8765; run the core separately.

**MP1 real Edge Node smoke:** with the core running, set `EDGE_BASE_URL` and run `./scripts/mp1-edge-smoke.py` to validate host↔edge `GET /health`, `POST /retrieve`, and `POST /ingest` paths (see [`docs/spec/mp1-implementation-status.md`](docs/spec/mp1-implementation-status.md)).

**MP1 local Edge Node (dev only):** start the host once so `.memoryagent/secrets/bearer.token` exists, then in a second terminal run `./scripts/run-local-edge.py` (default `http://127.0.0.1:9876`). In a third terminal: `MP1_REQUIRE_RETRIEVE_HITS=1 EDGE_BASE_URL=http://127.0.0.1:9876 ./scripts/mp1-edge-smoke.py`.

## Validated calendar commands

Assuming the server is running, load `TOKEN` from the active data dir:

```bash
export MEMORYAGENT_DATA_DIR="${MEMORYAGENT_DATA_DIR:-$PWD/.memoryagent}"
TOKEN=$(tr -d '\n' < "$MEMORYAGENT_DATA_DIR/secrets/bearer.token")
```

Then run:

```bash
# List events in a time window
curl -sS -X POST "http://127.0.0.1:8765/api/v1/tools/invoke" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"tool":"calendar.list_events","arguments":{"start":"2026-04-21T00:00:00Z","end":"2026-04-28T23:59:59Z"}}'

# Search past events by keyword (requires before > matching event end)
curl -sS -X POST "http://127.0.0.1:8765/api/v1/tools/invoke" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"tool":"calendar.search_past_events","arguments":{"keywords":["Graduation"],"before":"2026-05-20T00:00:00Z"}}'

# Create event through tools endpoint
curl -sS -X POST "http://127.0.0.1:8765/api/v1/tools/invoke" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"tool":"calendar.create_event","arguments":{"title":"Test","starts_at":"2026-05-10T15:00:00Z"}}'

# Create event through REST endpoint
curl -sS -X POST "http://127.0.0.1:8765/api/v1/calendar/events" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"REST","starts_at":"2026-05-10T16:00:00Z","ends_at":"2026-05-10T17:00:00Z"}'
```

### Chat calendar flow (M4)

Chat supports a structured create intent:

```text
create calendar event: title=Dentist Checkup; starts_at=2026-07-01T14:00:00Z; ends_at=2026-07-01T15:00:00Z
```

Natural style is also accepted when using ISO timestamps, e.g.:

```text
schedule dentist checkup at 2026-07-01T14:00:00Z to 2026-07-01T15:00:00Z in Smile Clinic
```

If `location` is omitted, the server first runs `calendar.search_past_events` using title-derived keywords and reuses the newest matching location when found; otherwise it asks for clinic/address.

Free-form lookup queries are also routed to calendar tools, for example:
`let me get the date and time of appointment at Takashi Dental in June`.

## Layout

| Path | Role |
| :--- | :--- |
| `services/core/` | Python FastAPI + uvicorn (`memoryagent-core`) |
| `web/` | Vite + TypeScript SPA → `web/dist` served by core |
| `native-bridge/macos-calendar/` | Swift CLI: EventKit calendar bridge for `list_events`, `search_past_events`, and `create_event` |

## Tests

```bash
cd services/core && source .venv/bin/activate && pytest
```

## M5 benchmark (step 1)

With the server running:

```bash
export MEMORYAGENT_DATA_DIR="${MEMORYAGENT_DATA_DIR:-$PWD/.memoryagent}"
python scripts/benchmark_m5.py --data-dir "$MEMORYAGENT_DATA_DIR" --out docs/benchmarks/m5-latest.md
```

See `docs/benchmarks/README.md` for details.

## How to use MemoryAgent

Use these patterns in chat for the best results:

- **Save memory:** `Remember that my dentist is Takashi Dental.`
- **Search memory:** `What did I save about benchmark scripts?`
- **Calendar lookup:** `Show my Takashi Dental appointments in June.`
- **Create calendar event (structured):**  
  `create calendar event: title=Dentist Checkup; starts_at=2026-07-01T14:00:00Z`
- **Create calendar event (natural):**  
  `schedule dentist checkup at 2026-07-01T14:00:00Z to 2026-07-01T15:00:00Z in Smile Clinic`

In app chat, ask **`what can you do for me?`** (or **`help`**) to get this capability guide.

## Contributing

How to propose changes, run tests, and open pull requests is described in [`CONTRIBUTING.md`](CONTRIBUTING.md). The default merge branch there is **`ma-dist`**, which is the project **integration** line—not “macOS-only” despite the name; follow the guide for bases and checks.
