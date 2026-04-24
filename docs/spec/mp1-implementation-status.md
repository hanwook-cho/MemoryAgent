# MP1 Implementation Status

Date: 2026-04-24  
Branch: `ma-dist`

Purpose: record the current implementation and verification status for the MP1 distributed foundation. This is **not** the `ma-dist` → `main` promotion checklist; that remains governed by [`ma-dist-promotion-checklist.md`](ma-dist-promotion-checklist.md), which requires full product phases 0–8 or explicit waivers.

## Summary

MP1 distributed foundation is implemented on `ma-dist` for host-side contracts and mock-edge validation:

- Backend contracts and runtime wiring: `RetrievalBackend`, `IngestBackend`, `LlmBackend`.
- Deployment modes in config: `standalone`, `host_edge`, `hybrid`, `ios_companion`.
- `edge_base_url` config and in-process backend rebinding on relevant `PATCH /config` changes.
- Edge health ping via `GET /health`.
- Remote retrieval via Node `POST /retrieve` for `host_edge`, and local+remote merge for `hybrid`.
- Remote memory ingest via Node `POST /ingest`, including HTTP memory entry and chat “Remember that …” paths.
- Optional file/mirror `POST /ingest` path mapping via `edge_ingest_path_host_prefix` and `edge_ingest_path_edge_prefix`.
- Edge TLS support: default CA trust, optional `edge_tls_ca_bundle`, SPKI pinning via `edge_tls_spki_pins_sha256`, lab-only `edge_tls_insecure_skip_verify`.
- Admin/debug endpoints from Client API §3.11 are present with current MVP behavior.

## Verification Evidence

Last recorded local run:

```text
122 passed
```

Covered tests:

- [`tests/test_mp1_pr1.py`](../../services/core/tests/test_mp1_pr1.py) — backend contract/config foundation.
- [`tests/test_mp1_pr2.py`](../../services/core/tests/test_mp1_pr2.py) — health deployment/degraded metadata.
- [`tests/test_mp1_phase3.py`](../../services/core/tests/test_mp1_phase3.py) — chat metadata and admin/debug endpoints.
- [`tests/test_mp1_remote_retrieve.py`](../../services/core/tests/test_mp1_remote_retrieve.py) — remote retrieve, ingest fan-out, hybrid behavior, edge file path mapping.
- [`tests/test_mp1_mock_edge_smoke.py`](../../services/core/tests/test_mp1_mock_edge_smoke.py) — local FastAPI mock Edge Node over TCP exercising host `PATCH /config`, `GET /health`, `POST /retrieve`, `POST /ingest`, `/memory/search`, `/memory/entries`, and chat save ingest over the real HTTP client path.
- [`tests/test_edge_http.py`](../../services/core/tests/test_edge_http.py) — TLS verify helper, SPKI digest extraction, and pin mismatch behavior.

## Remaining Gate

Before treating MP1 as externally validated, run the same smoke flow against a **real Edge Node** (or record an explicit waiver):

1. Configure `deployment_mode=host_edge` and a real `edge_base_url`.
2. Confirm host `GET /api/v1/health` reports `deployment.edge_reachable=true` and `degraded=false`.
3. Confirm `/api/v1/memory/search` reaches real Node `POST /retrieve`.
4. Confirm `/api/v1/memory/entries` reaches real Node `POST /ingest` with `kind=memory`.
5. Confirm chat “Remember that …” reaches real Node `POST /ingest` with `source=chat`.
6. If HTTPS is used, verify `edge_tls_ca_bundle` and, if enabled, `edge_tls_spki_pins_sha256`.

Reusable smoke command (host must already be running):

```bash
EDGE_BASE_URL="https://edge.example:9443" ./scripts/mp1-edge-smoke.py
```

For local development without a real edge deployment, start the in-memory local edge in a second terminal:

```bash
# Terminal 1: host
./scripts/run.sh

# Terminal 2: local Edge Node (loopback, in-memory)
./scripts/run-local-edge.py

# Terminal 3: smoke host -> local edge
MP1_REQUIRE_RETRIEVE_HITS=1 EDGE_BASE_URL="http://127.0.0.1:9876" ./scripts/mp1-edge-smoke.py
```

`run-local-edge.py` reads the same bearer token from `.memoryagent/secrets/bearer.token` by default. Its data is in-memory and resets on restart.

Useful variants:

```bash
# Require retrieve/search to return at least one hit after direct edge ingest.
MP1_REQUIRE_RETRIEVE_HITS=1 EDGE_BASE_URL="https://edge.example:9443" ./scripts/mp1-edge-smoke.py

# Direct edge checks through a private CA bundle.
EDGE_BASE_URL="https://edge.example:9443" EDGE_CA_BUNDLE=/path/to/ca.pem ./scripts/mp1-edge-smoke.py

# Lab-only direct edge TLS bypass (host config is still restored at the end).
EDGE_BASE_URL="https://edge.example:9443" EDGE_INSECURE_SKIP_VERIFY=1 ./scripts/mp1-edge-smoke.py
```

## Promotion Status

`ma-dist` → `main` promotion is **HOLD** under current policy because [`ma-dist-promotion-checklist.md`](ma-dist-promotion-checklist.md) requires phases 0–8, not just MP1 Phase 3. The next eligible action is either:

- complete and verify the remaining product phases, or
- explicitly revise/waive the promotion policy in writing.
