# Test plan — milestones and automation

This document maps **each milestone** in [`milestones.md`](milestones.md) to **what to verify**, **what to automate**, and **what stays manual**. Implementation may use any stack (e.g. **pytest** + **httpx** for API, **Playwright** for web, **Swift XCTest** for native bridge); the important part is **repeatable** checks tied to acceptance criteria.

## 1. Principles

| Principle | Detail |
| :--- | :--- |
| **Acceptance = contract** | Each milestone’s **Acceptance** block is the source of truth for “done.” Tests should trace to those bullets. |
| **Automate the stable parts** | HTTP API, auth, ingest/chunk/embed, retrieval shape, error codes, file watcher debouncing logic. |
| **Mock or stub the LLM when you need determinism** | Integration tests can use a **fake LLM** that returns fixed strings so citations and tool routing are assertable without GPU variance. Optional **smoke** with a real local model stays manual or nightly CI. |
| **macOS-only in CI** | EventKit, file watchers, and menu bar need **macOS runners** (or manual QA) unless you abstract behind interfaces and test with fakes on Linux CI. |
| **E2E is thinner** | A few **browser** tests (welcome visible once, one chat round-trip) complement API tests; avoid flakiness by not depending on real LLM output text in CI. |

## 2. M0 — Repository and contracts

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| Core starts, binds loopback | **Integration:** `GET /health` → 200, JSON shape per [`client-api.md`](client-api.md) | First launch generates token on disk |
| Bearer enforced | **Integration:** request without `Authorization` → 401; with token → 200 on protected routes | — |
| Static web served | **Optional E2E:** `GET /` → 200, `Content-Type` HTML | Open in browser |
| Docs in sync | **CI:** link check or OpenAPI diff if OpenAPI exists | Review |

**Exit:** CI runs M0 suite green; human sanity-checks browser once.

## 3. M1 — RAG loop (no OS observation)

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| Ingest fixture text/file | **Unit/integration:** ingest pipeline produces chunks + embeddings + vector upsert; idempotent or documented behavior | — |
| Chat returns citations structure | **Integration:** with **mock LLM**, assert response includes `citations[]` with `chunk_id` / snippet when retrieval hits | Real Ollama/MLX: ask question, eyeball citation correctness |
| Streaming SSE | **Integration:** parse SSE stream; `done` event present | Browser sees streamed tokens |
| `POST /memory/entries` | **Integration:** 201, document visible in search | — |
| First-run welcome (UI-5) | **E2E (Playwright or similar):** empty chat shows welcome copy (match key phrases from [`onboarding.md`](onboarding.md)); after dismiss/first message, welcome not shown (clear storage between tests) | Copy review when `WELCOME_COPY_VERSION` changes |

**Exit:** Automated suite covers API + ingest + chat shape; one optional nightly job with real LLM.

## 4. M2 — File system watching

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| Ignore globs / debounce | **Unit/integration:** synthetic fs or temp dir; assert single index after burst of writes | — |
| Reindex updates retrieval | **Integration:** write fixture (`.md`, `.txt`, mocked `.pdf`/`.docx`), wait for job (or trigger), `GET /memory/search?q=…` finds new terms | Edit real file under watched root |
| Backpressure | **Integration or load test:** many files; assert queue depth / no crash (threshold in test doc) | Activity Monitor spot check |
| Metadata-aware retrieval filters | **Integration:** `GET /memory/search` with `source_kind`, `path_prefix`, `indexed_after`, `indexed_before` returns constrained results | Ask natural query like “find bank statement in the last month” and verify relevance |

**Exit:** CI on **macOS** runs watcher tests; Linux CI may skip or use fake file event source if implemented.

## 5. M3 — Markdown mirror and audit

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| Mirror files + validation | **API + unit:** `GET`/`PUT /mirror/{id}` (`user` or `soul`); invalid YAML → **400**; `tests/test_m3.py` | — |
| Body-only embedding | **Unit:** `ingest_mirror_document` chunks Markdown body, not front matter | — |
| Edit propagates | **Integration:** `PUT` mirror → `GET /memory/search` finds body text | **E2E:** web “Memory audit” → Save & reindex → search in Chat |

**Exit:** Regression tests for sync invariants; manual audit of Markdown once per release candidate.

## 6. M4 — Tools and MCP

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| Tool registry + permission gate | **API:** `GET /tools`; `POST /tools/invoke` unknown tool → **404**; `tests/test_m4_tools.py` | TCC prompts on real Mac when calendar tools land |
| File tool | **API:** `file.read` allowlist + size/extension checks (`tests/test_m4_file_read.py`, `tests/test_file_access.py`) | Read a real file under a watched root |
| `memory.save` | **API:** `POST /tools/invoke`; **Chat:** `POST /chat` save-prefix heuristics on last user message (`tests/test_m4_tools.py`, `tests/test_m4_chat.py`, `tests/test_memory_intent.py`) | Natural phrases in UI |
| Calendar read | **API:** `calendar.list_events` mocked in `tests/test_m4_calendar.py`; bridge in `native-bridge/macos-calendar` | Build bridge + `tools/invoke` with real date range; grant Calendars in System Settings |
| Calendar create / `search_past_events` | **Native:** XCTest or bridge tests with **EventKit** in a **dedicated test calendar** (create/cleanup in setup) | Real Calendar app shows event |
| Place reuse §3.4 | **Integration:** seed past event with location → new create proposal includes location **or** mock returns ask-user path | Dentist scenario walkthrough |
| MCP (if exposed) | **Contract:** tool schemas match registry | Manual MCP client |

**Exit:** macOS job covers EventKit; Linux CI runs non-mac tests only with `calendar` skipped or faked.

## 7. M5 — Product hardening

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| NFR-1 / NFR-2 | **Scripted:** measure cold/warm time to first token, idle CPU (document hardware in [`prerequisites.md`](prerequisites.md)) | Compare on reference Mac |
| Logs | **Integration:** rotation/truncate after N MB (`tests/test_m5_logging.py`) | Inspect files |
| Structured API errors | **Integration:** `tests/test_m5_structured_errors.py` asserts `detail.error` for `VALIDATION`, `PERMISSION_DENIED`, `MODEL_UNAVAILABLE` (incl. SSE `event: error` on `/chat/stream`) | Spot-check new routes in OpenAPI |
| Packaging / launchd | **Smoke:** install script exits 0; service starts | User installs on clean VM |
| Admin/Debug controls | **Integration:** restricted endpoints enforce auth/confirmation; `cold-start`/`reset-index` behavior and audit logs verified | Manual destructive-operation confirmation UX |

**Exit:** Benchmark doc checked in; CI fails if regression beyond agreed threshold (optional gate).

### 7.1 MP1 — PR-1 (backend scaffolding; default `standalone` unchanged)

**Relationship to [`mp1-verification-checklist.md`](mp1-verification-checklist.md):** that checklist is the **pre-implementation** design gate (**GO** / **NO-GO**). This subsection is the **test plan for the first code PR** after GO.

Scope and acceptance bullets are canonical in [`mp1-pr1.md`](mp1-pr1.md).

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| No regression in default mode | **Integration:** existing suites (`tests/test_m2.py`, M4 tool/chat tests, etc.) remain green with default config | Smoke: `GET /health`, one chat round-trip, one memory search (mock LLM OK) |
| `deployment_mode` (or equivalent) | **Unit/integration:** default is `standalone`; config load/save preserves field; unknown value policy matches PR-1 doc (reject at startup **or** log + fall back—**one** behavior, tested) | — |
| Backend seams | **Unit:** local `RetrievalBackend` / `IngestBackend` / `LlmBackend` delegates call into pre-PR-1 behavior (spot-check critical methods used by chat path) | — |

**Exit:** PR-1 merged with tests above; no change to default user-visible behavior documented in [`mp1-pr1.md`](mp1-pr1.md).

### 7.2 MP1 — PR-2 (health `deployment` / degraded)

Scope: [`mp1-pr2.md`](mp1-pr2.md).

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| Health includes `deployment` | **Integration:** `GET /health` has `deployment.mode`, `degraded`, `degraded_reason`; `standalone` → not degraded | — |
| Non-standalone marks degraded | **Integration:** `PATCH /config` `deployment_mode` → `host_edge`, then `GET /health` shows `degraded: true` and non-empty reason | — |
| Unit helper | **Unit:** `health_deployment_block` for `standalone` vs `host_edge` | — |

**Exit:** PR-2 merged; [`client-api.md`](client-api.md) health example updated.

### 7.3 MP1 — Phase 3 (edge URL, health ping, chat `meta`, admin)

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| `edge_base_url` config | **Integration:** `GET/PATCH /config` round-trip; invalid URL rejected or cleared per [`config_store.py`](../../services/core/memoryagent/config_store.py) | — |
| Edge health stub | **Unit/integration:** `fetch_edge_health` + `GET /health` `deployment.edge_reachable` when `deployment_mode` ≠ `standalone` and URL set (`tests/test_mp1_pr2.py`) | Point at mock edge or real Node when available |
| Chat `meta.degraded` | **Integration:** `POST /chat` and `POST /chat/stream` include `meta` / `event: meta` aligned with deployment + edge ping (`tests/test_mp1_phase3.py`, `tests/test_m1.py`) | — |
| Admin §3.11 | **Integration:** `GET /admin/status`, `GET /admin/events`, control POSTs bearer-gated; `reset-index` clears ingested memory document (`tests/test_mp1_phase3.py`) | Confirm destructive ops in staging only |

**Exit:** [`tests/test_mp1_phase3.py`](../../services/core/tests/test_mp1_phase3.py) green on `ma-dist`.

### 7.4 MP1 — Remote retrieve (`POST /retrieve`)

| Goal | Automated | Manual / smoke |
| :--- | :--- | :--- |
| `host_edge` retrieval | **Integration:** mocked `try_node_retrieve` → `GET /memory/search` returns edge rows after `PATCH` mode+URL (`tests/test_mp1_remote_retrieve.py`) | Real edge Node |
| Mock Edge Node smoke | **Integration:** local FastAPI mock edge over TCP validates `GET /health`, `POST /retrieve`, `POST /ingest`, host `PATCH /config`, `/memory/search`, `/memory/entries`, and chat “Remember that …” (`tests/test_mp1_mock_edge_smoke.py`) | Real edge Node with same flow via [`scripts/mp1-edge-smoke.py`](../../scripts/mp1-edge-smoke.py); local dev edge via [`scripts/run-local-edge.py`](../../scripts/run-local-edge.py) |
| Fallback | **Unit:** remote returns `None` → local Chroma hits | — |
| `hybrid` merge | **Unit:** local + remote merged by best score per `chunk_id` | — |
| Chat RAG path | **Integration:** existing chat tests with `bind_retrieval_for_chat` | — |
| Remote memory ingest | **Integration:** `POST /memory/entries` with `host_edge` + mocked `try_node_ingest_memory` (`tests/test_mp1_remote_retrieve.py`) | Real edge |
| Chat / tools ingest | **Integration:** `POST /chat` “Remember that …” under `host_edge` + mock (`tests/test_mp1_remote_retrieve.py`); `RagService` routes via `bind_ingest_for_routing` | — |
| Remote file ingest (mapped) | **Unit:** `HostEdgeIngestBackend` + mocked `try_node_ingest_file` when path maps (`tests/test_mp1_remote_retrieve.py`) | Real/local edge + shared filesystem contract via `MP1_FILE_SMOKE_ROOT=... ./scripts/mp1-edge-smoke.py` |
| Hybrid memory ingest | **Unit:** background `try_node_ingest_memory` after local (`tests/test_mp1_remote_retrieve.py`) | — |
| Edge TLS verify helper | **Unit:** [`tests/test_edge_http.py`](../../services/core/tests/test_edge_http.py) | — |
| SPKI pinning | **Unit:** SPKI digest + `PinningSSLContext` / proxy handshake (`tests/test_edge_http.py`) | Lab edge with known leaf key |

**Exit:** [`tests/test_mp1_remote_retrieve.py`](../../services/core/tests/test_mp1_remote_retrieve.py), [`tests/test_mp1_mock_edge_smoke.py`](../../services/core/tests/test_mp1_mock_edge_smoke.py), and [`tests/test_edge_http.py`](../../services/core/tests/test_edge_http.py) green.

**Local distributed smoke evidence:** persistent Chroma-backed local Edge Node (`scripts/run-local-edge.py`) + `scripts/mp1-edge-smoke.py` passed with `MP1_REQUIRE_RETRIEVE_HITS=1` and `MP1_FILE_SMOKE_ROOT=...`; see [`mp1-implementation-status.md`](mp1-implementation-status.md).

**Remaining external gate:** repeat or waive the same smoke against a non-local HTTPS Edge Node, including `edge_tls_ca_bundle` / `edge_tls_spki_pins_sha256` when configured.

## 8. Optional — Native shell

| Goal | Automated | Manual |
| :--- | :--- | :--- |
| Menu bar / hotkey | **XCUITest** or limited UI automation | Click opens correct `http://127.0.0.1:…` |

## 9. CI matrix (recommended)

| Job | Runs on | Scope |
| :--- | :--- | :--- |
| **unit+api** | Linux (or macOS) | Pure logic, mock LLM, HTTP against test server |
| **macos-integration** | macOS | File watcher, optional EventKit in M4+ |
| **e2e-web** | macOS (or Linux with Xvfb if only API-backed) | Thin Playwright: health, welcome, one chat with mock backend |
| **nightly** | macOS | Real LLM smoke (optional, non-blocking) |

## 10. Manual test procedures (exact steps)

Use these when **automated** coverage is insufficient or before a release. Replace placeholders with values from your environment:

| Placeholder | Meaning |
| :--- | :--- |
| `<BASE>` | API base, e.g. `http://127.0.0.1:<PORT>/api/v1` (see [`client-api.md`](client-api.md)) |
| `<TOKEN>` | Bearer token from first-run `secrets/` or app UI |
| `<WEB>` | Web UI URL, e.g. `http://127.0.0.1:<PORT>/` |

**For each procedure:** record **Pass/Fail**, **date**, **git commit or build id**, **tester name**, **macOS version**, and **machine model** (e.g. M2, 16 GB) for NFR-related runs.

### 10.1 M0 — Service, auth, static web

#### MT-M0-01 — Health without auth (if health is public)

1. Start the core service per project README.
2. In Terminal (use your implementation’s health path; typically `<BASE>/health` where `<BASE>` is `http://127.0.0.1:<PORT>/api/v1`):  
   `curl -sS "<BASE>/health"`  
3. **Expected:** HTTP **200** and JSON body includes `"status": "ok"` (or documented equivalent). If health is protected like other routes, expect **401** and document that variant; then use MT-M0-03 token for an authenticated health check instead.

#### MT-M0-02 — Protected route rejects missing token

1. Call a route that requires auth, e.g. `GET <BASE>/config` with **no** `Authorization` header:  
   `curl -sS -o /dev/null -w "%{http_code}" "<BASE>/config"`
2. **Expected:** HTTP **401**.

#### MT-M0-03 — Protected route accepts valid token

1. Read `<TOKEN>` from the documented secrets location (or copy from Settings in the web UI if shown).
2. Run:  
   `curl -sS -H "Authorization: Bearer <TOKEN>" "<BASE>/config"`
3. **Expected:** HTTP **200** and JSON body (no secret fields).

#### MT-M0-04 — Web UI loads

1. Open `<WEB>` in Safari (or Chrome).
2. **Expected:** Page loads without console **errors** (warnings acceptable); main layout visible (chat or shell).

---

### 10.2 M1 — RAG, memory, welcome (no OS tools)

#### MT-M1-01 — First-run welcome (UI-5)

1. Clear site data for `<WEB>` (Safari: Develop → Empty Caches / remove website data; Chrome: Application → Clear storage) **or** use a private window first time only.
2. Open Chat with **no prior messages** in that profile.
3. **Expected:** Assistant shows **static** welcome content matching [`onboarding.md`](onboarding.md) (opening line + help bullets); **no** loading spinner that implies an LLM call **only** for that welcome block (implementation may still load the page).
4. Click **Got it** if present **or** type any short user message and send.
5. Reload the page; open Chat again.
6. **Expected:** The long welcome block does **not** reappear (unless **Show welcome again** is used or `WELCOME_COPY_VERSION` changed).

#### MT-M1-02 — Manual memory entry and retrieval with citation

1. Use the web UI **Add memory** / equivalent, or call:  
   `curl -sS -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d '{"text":"Manual test fact: favorite color is teal for MT-M1-02.","tags":["test"],"source":"manual_mt"}' "<BASE>/memory/entries"`  
2. **Expected:** HTTP **201** (or documented success).
3. In Chat, send: `What is my favorite color according to what I saved?`
4. **Expected:** Reply mentions **teal** (or the saved fact); UI shows **at least one citation** or source link to the ingested chunk (per milestone acceptance).

#### MT-M1-03 — Non-streaming chat (API)

1. `curl -sS -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"What did I save about favorite color?"}]}' "<BASE>/chat"`
2. **Expected:** HTTP **200**, JSON includes `reply` and `citations` array (may be empty only if retrieval truly finds nothing).

#### MT-M1-04 — Streaming chat (browser)

1. Open Chat; send a question that should use memory.
2. **Expected:** Tokens appear progressively (SSE/stream); stream ends without error; final state shows citations if applicable.

---

### 10.3 M2 — File watching

#### MT-M2-01 — Watched file updates memory

**Preconditions:** A directory is configured as a **watched root** (Settings or `config.json`).

1. Create a new file under that root, e.g. `watched-test-mt-m2.md`, with unique content: `MT-M2-01 unique token: alpha-beta-gamma-7731`.
2. Wait for the **documented SLA** (e.g. 2 minutes) **or** click **Reindex** if the UI provides it.
3. In Chat or Search, query for `alpha-beta-gamma-7731`.
4. **Expected:** Result includes content from that file.
5. Edit the same file: change token to `alpha-beta-gamma-7732`; wait SLA or reindex.
6. Query for `7732`; **Expected:** hit. For the **old** token: search for the **full** string `alpha-beta-gamma-7731` (or read the result **snippet**); **Expected:** that exact phrase no longer appears in indexed content. **Note:** A **short** query such as `q=7731` alone may still **rank** the updated chunk because `/memory/search` is embedding-based; that does not mean the old text is still stored—check the snippet or use the full old phrase.

#### MT-M2-01 — Result log (fill in after each run)

| Procedure | Pass/Fail | Date | Commit / build | Tester | macOS | Hardware | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| *Template row* | Pass/Fail | YYYY-MM-DD | `git rev-parse --short HEAD` | | | | |

**Example (recorded run):**

| Procedure | Pass/Fail | Date | Commit / build | Tester | macOS | Hardware | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| MT-M2-01 | Pass | 2026-04-21 | *(none — workspace not a git checkout)* | | | Mac mini | `PATCH /config` with `watched_roots` = `/tmp/memoryagent-watch-test`, `watch_debounce_seconds` = 2; created `watched-test.md`; `GET /memory/search` found `alpha-beta-gamma-7731` then, after overwrite, `7732` with updated snippet; same `document_id` for file URI as expected. |

#### MT-M2-02 — Watched file (API-only, curl)

Use when there is no Settings UI yet: `<BASE>` and `<TOKEN>` as in the table above.

1. `mkdir -p /tmp/memoryagent-watch-test` (or any **existing** directory you will watch).
2. Register the watcher:  
   `curl -sS -X PATCH -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d '{"watched_roots":["/tmp/memoryagent-watch-test"],"watch_debounce_seconds":2}' "<BASE>/config"`
3. **Expected:** HTTP **200** and JSON includes `watched_roots` with that path.
4. Write a test file:  
   `echo "MT-M2-01 unique token: alpha-beta-gamma-7731" > /tmp/memoryagent-watch-test/watched-test.md`
5. Wait at least **debounce + embed** time (e.g. a few seconds with local Ollama).
6. `curl -sS -H "Authorization: Bearer <TOKEN>" "<BASE>/memory/search?q=alpha-beta-gamma-7731&limit=5"`  
   **Expected:** `results` non-empty; snippet contains the token.
7. Overwrite with the second token, wait again, search for `7732`. **Expected:** snippet shows `7732`. Record the run in **MT-M2-01 — Result log**.

---

### 10.4 M3 — Markdown mirror audit

#### MT-M3-01 — Edit mirror and retrieval

1. Open the **Memory audit** / Markdown page per UI-4.
2. Append a line to `USER.md` or equivalent: `MT-M3-01 mirror line 99441`.
3. Save; follow any **reindex** prompt if shown.
4. **Verify indexing:** `GET /memory/search?q=99441` (or a longer phrase from the line) — **Expected:** at least one `results[]` entry whose `snippet` contains the new line (rank order may include unrelated chunks; embedding-only search is not exact-match).
5. **Optional — Chat:** Ask a specific question (e.g. “What line did I add to USER.md for MT-M3-01?”). Short numeric-only chat questions may retrieve weakly; prefer step 4 for a strict pass.

#### MT-M3-01 — Result log (fill in after each run)

| Procedure | Pass/Fail | Date | Commit / build | Tester | macOS | Hardware | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| *Template row* | Pass/Fail | YYYY-MM-DD | `git rev-parse --short HEAD` | | | | |

**Example (recorded run):**

| Procedure | Pass/Fail | Date | Commit / build | Tester | macOS | Hardware | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| MT-M3-01 | Pass | 2026-04-21 | *(local)* | | | | Appended `MT-M3-01 mirror line 99441` to `USER.md` via Memory audit; **Save & reindex**. `GET /memory/search?q=99441` returned `USER.md` chunk (snippet included that line; another unrelated chunk ranked higher). Chat answered correctly for: “What line did I add to USER.md for MT-M3-01?” |

---

### 10.5 M4 — Tools, calendar, remember, place reuse

**Preconditions:** **Calendars** permission can be granted in **System Settings** for the app or bridge binary as documented.

#### MT-M4-01 — “Remember that …” from chat

1. In Chat, send: `Remember that my manual test code for MT-M4-01 is 48291.`
2. **Expected:** Assistant confirms save (or shows confirmation per product).
3. Ask: `What is my manual test code for MT-M4-01?`
4. **Expected:** Answer includes **48291** with citation to stored memory.

#### MT-M4-02 — Calendar read in chat

1. In **Calendar.app**, create an event **tomorrow** titled `MT-M4-02 visibility test`, any time.
2. Grant **Calendars** access to MemoryAgent if prompted.
3. In Chat: `What do I have tomorrow?` (or equivalent that triggers calendar read tool).
4. **Expected:** Reply references the event title **MT-M4-02 visibility test** or explains permission denial clearly.

#### MT-M4-03 — Create calendar event (with confirmation if implemented)

1. In Chat: `Add event titled MT-M4-03 Manual Test for next Wednesday at 3pm` (adjust date to a real upcoming Wednesday).
2. **Expected:** Confirmation card shows **title**, **date/time**, **timezone**; user confirms.
3. Open **Calendar.app**; locate the event **MT-M4-03 Manual Test**.
4. **Expected:** Event exists at the agreed time (or user sees clear validation error if parsing failed).

#### MT-M4-04 — Dentist place reuse (§3.4)

1. In **Calendar.app**, create a **past** event (yesterday or last month): title `Dentist`, set **Location** to `123 Manual Test Dental Lane, Testville`, save.
2. In Chat: `Add dentist appointment July 1 at 2pm` (use a future year/date consistent with your calendar).
3. **Expected:** Proposed event shows **Location** containing `123 Manual Test Dental Lane` **or** assistant asks for clinic/name only if no match (per [`agent-actions.md`](agent-actions.md) §3.4).
4. Confirm creation if required; verify in Calendar.app that the new event has the expected location or notes.

#### MT-M4-05 — Permission denied path

1. Revoke **Calendars** access for the app in **System Settings → Privacy & Security → Calendars**.
2. Request: `What’s on my calendar tomorrow?`
3. **Expected:** Structured failure message and hint to re-enable permission (no silent empty answer).

---

### 10.6 M5 — Hardening and packaging

#### MT-M5-01 — Time to first token (NFR-1 smoke)

1. Quit and restart the core service (cold).
2. Open Chat; send a short prompt; start a timer at **Send**.
3. **Expected:** First visible token within **2.0 s** on the **reference** Apple Silicon machine documented in the benchmark doc (adjust threshold if product doc says otherwise).

#### MT-M5-02 — Idle CPU (NFR-2 smoke)

1. Let the app idle with watchers enabled **5 minutes**; observe CPU in Activity Monitor for the core process.
2. **Expected:** Roughly within **5%** average CPU at idle per NFR-2 (document exceptions if indexing runs).

#### MT-M5-03 — Log rotation

1. Note `logs/` directory size; trigger or wait for rotation threshold per implementation.
2. **Expected:** No single log file grows without bound; old logs truncated/archived.

#### MT-M5-04 — Clean install smoke (packaging)

1. On a **fresh user account** or VM, follow the **authoritative install path** for the current release. Until a retail bundle exists, this is the **documented source + scripts** flow in repository `README.md` and [`prerequisites.md`](prerequisites.md) §7 (see [`m5-packaging-decision.md`](m5-packaging-decision.md)).
2. Start the app; complete first-run; send one chat message.
3. **Expected:** No crash; health OK.

---

### 10.7 Optional — Native shell

#### MT-OPT-01 — Menu bar opens web UI

1. Click the MemoryAgent menu bar icon.
2. Choose **Open** / default action.
3. **Expected:** Browser opens `<WEB>` (or documented URL); page loads.

---

## 11. Related documents

- [`prd-full-product.md`](prd-full-product.md) — full-product phased roadmap
- [`srs-full-product.md`](srs-full-product.md) — full-product SHALL requirements and verification matrix
- [`ma-dist-promotion-checklist.md`](ma-dist-promotion-checklist.md) — merge `ma-dist` → `main` when integration complete
- [`milestones.md`](milestones.md) — acceptance themes
- [`client-api.md`](client-api.md) — contract under test
- [`agent-actions.md`](agent-actions.md) — tool behaviors to cover in M4
- [`mp1-pr1.md`](mp1-pr1.md) — first MP1 code PR scope; **§7.1** above maps tests to that PR
- [`mp1-pr2.md`](mp1-pr2.md) — MP1 PR-2 health deployment/degraded; **§7.2**
- [`mp1-verification-checklist.md`](mp1-verification-checklist.md) — pre-implementation spec gate (before PR-1 code)
