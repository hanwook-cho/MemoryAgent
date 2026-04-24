# Node API (Host Backend <-> Edge Node)

This document defines the Node API contract used between **Host Backend** and **Edge Node** in distributed modes.

Related docs:

- Client-facing API: [`client-api.md`](client-api.md)
- Distributed architecture and decisions: [`distributed-future-plan.md`](distributed-future-plan.md)

## 1. Scope

Node API is used for:

- remote retrieval
- remote ingest trigger
- remote index/control status

It is not intended for direct end-user clients.

## 2. Transport and security

- Transport: **HTTPS REST** (Decision D2)
- Auth: **Bearer token over TLS** baseline (Decision D3)
- mTLS: optional future hardening, not required in v1
- **Host backend TLS to Node:** the Python host may set a custom CA bundle (`edge_tls_ca_bundle`), `edge_tls_spki_pins_sha256` (list of 64-hex-character **SPKI** SHA-256 digests), or `edge_tls_insecure_skip_verify` for lab only; see `GET/PATCH /config` in [`client-api.md`](client-api.md). SPKI pins are enforced on the leaf certificate public key after standard chain + hostname verification (see [`edge_http.py`](../../services/core/memoryagent/edge_http.py) `PinningSSLContext`).

### 2.1 SPKI pinning — guidelines (when and how)

**What the pin is:** each entry in `edge_tls_spki_pins_sha256` is the **SHA-256** digest of the **leaf** certificate’s **SubjectPublicKeyInfo** (SPKI) DER, expressed as **64 lowercase hex characters** (optional `:` between byte pairs is stripped on load). This matches common tooling:

```bash
# From the operator-held leaf PEM (same cert the edge uses for HTTPS):
openssl x509 -in edge-leaf.pem -noout -pubkey \
  | openssl pkey -pubin -outform DER \
  | openssl dgst -sha256 -hex
```

The line after `SHA256(stdin)=` is the value to store (hex only, no `0x`).

**From a live server** (use the hostname/port you put in `edge_base_url`; adjust SNI if needed):

```bash
echo | openssl s_client -connect EDGE_HOST:443 -servername EDGE_HOST 2>/dev/null \
  | openssl x509 -noout -pubkey \
  | openssl pkey -pubin -outform DER \
  | openssl dgst -sha256 -hex
```

**When to compute it**

- **Before enabling pins in production:** after the edge (or TLS terminator in front of it) is serving the intended **leaf** cert/key, compute the pin from that material and set `edge_tls_spki_pins_sha256` via `PATCH /config`, then confirm `GET /health` and a sample retrieve/ingest succeed.
- **Before a private-key rotation:** compute the pin for the **new** key, `PATCH` an array that includes **both** old and new pins, roll the server, then `PATCH` again to drop the old pin once stable.
- **When debugging `certificate pinning failed`:** re-run the commands against the cert the host **actually** sees (correct hostname, same path as production); compare to config (typos, wrong env, load balancer presenting a different cert).

**Operational rules**

- Pins are **not** checked when `edge_tls_insecure_skip_verify` is `true` (lab only); the host logs a warning if pins are set but skipped.
- Prefer **at least two pins** in the array during rotation windows so you do not brick clients mid-cutover.
- Re-issuing a **new leaf certificate with the same private key** usually keeps the **same** SPKI pin; changing the key changes the pin.

For field names and JSON shape on the HTTP API, see [`client-api.md`](client-api.md) §3.7–3.8.

## 3. Base URL and versioning

- Base URL: `https://<edge-node>/`
- Versioning strategy (v1): stable paths + additive fields
- Future major changes should introduce path version prefix (e.g. `/v2/...`)

## 4. Common conventions

### 4.1 JSON and time

- Content type: `application/json`
- Time values: ISO-8601 strings with timezone

### 4.2 Standard error envelope

```json
{
  "error": {
    "code": "VALIDATION",
    "message": "indexed_after must be ISO-8601",
    "retryable": false,
    "details": {}
  }
}
```

### 4.3 Error codes

- `VALIDATION`
- `UNAUTHORIZED`
- `FORBIDDEN`
- `UNAVAILABLE`
- `TIMEOUT`
- `INDEX_BUSY`
- `INTERNAL`

### 4.4 Trace metadata (optional)

Request may include optional trace object:

```json
{
  "trace": {
    "request_id": "req_123",
    "caller": "host_backend"
  }
}
```

## 5. Endpoints

## 5.1 `GET /health`

Purpose: edge service health and capabilities.

### Query parameters

None.

### Success response `200`

```json
{
  "status": "ok",
  "node_id": "edge-a",
  "capabilities": {
    "retrieve": true,
    "ingest": true,
    "reindex": true
  },
  "version": "0.1.0"
}
```

### Errors

- `UNAUTHORIZED` (`401`)
- `INTERNAL` (`500`)

## 5.2 `GET /index/status`

Purpose: queue/job/index health snapshot.

### Query parameters

None.

### Success response `200`

```json
{
  "queue_depth": 3,
  "active_jobs": 1,
  "last_indexed_at": "2026-04-22T10:25:00Z",
  "last_error": null,
  "documents": 1280,
  "chunks": 18342
}
```

### Errors

- `UNAUTHORIZED` (`401`)
- `INTERNAL` (`500`)

## 5.3 `POST /retrieve`

Purpose: retrieve ranked chunks from edge index.

### Request body

| Field | Type | Required | Notes |
| :--- | :--- | :--- | :--- |
| `query` | string | yes | User query text |
| `limit` | integer | no | default `8`, max implementation-defined |
| `filters` | object | no | Metadata filters |
| `filters.source_kind` | string | no | e.g. `file_pdf`, `file_docx`, `memory` |
| `filters.path_prefix` | string | no | Source URI prefix |
| `filters.indexed_after` | string | no | ISO-8601 |
| `filters.indexed_before` | string | no | ISO-8601 |
| `trace` | object | no | Request tracing |

Example request:

```json
{
  "query": "find bank statement in the last month",
  "limit": 8,
  "filters": {
    "source_kind": "file_pdf",
    "path_prefix": "file:///data/docs/",
    "indexed_after": "2026-03-01T00:00:00Z",
    "indexed_before": "2026-03-31T23:59:59Z"
  }
}
```

### Success response `200`

| Field | Type | Notes |
| :--- | :--- | :--- |
| `results` | array | Ranked search results |
| `results[].chunk_id` | string | Unique chunk id |
| `results[].document_id` | string | Document grouping id |
| `results[].snippet` | string | Text excerpt |
| `results[].score` | number | Normalized relevance score |
| `results[].source` | string | Source URI |
| `results[].source_kind` | string | Source type |
| `results[].indexed_at` | string | ISO-8601 |
| `results[].backend_id` | string | e.g. `remote_edge` |
| `meta` | object | Diagnostics |
| `meta.query_ms` | integer | Query latency |
| `meta.backend_id` | string | Serving backend |
| `meta.total_candidates` | integer | Candidates considered |

Example response:

```json
{
  "results": [
    {
      "chunk_id": "doc123:4",
      "document_id": "doc123",
      "snippet": "Statement amount ...",
      "score": 0.82,
      "source": "file:///data/docs/bank.pdf",
      "source_kind": "file_pdf",
      "indexed_at": "2026-04-22T10:10:00Z",
      "backend_id": "remote_edge"
    }
  ],
  "meta": {
    "query_ms": 42,
    "backend_id": "remote_edge",
    "total_candidates": 56
  }
}
```

### Errors

- `VALIDATION` (`400`)
- `UNAUTHORIZED` (`401`)
- `UNAVAILABLE` (`503`, retryable)
- `TIMEOUT` (`504`, retryable)
- `INTERNAL` (`500`)

## 5.4 `POST /ingest`

Purpose: trigger ingest on edge node.

### Request body

| Field | Type | Required | Notes |
| :--- | :--- | :--- | :--- |
| `kind` | string | yes | `file` or `memory` |
| `path` | string | req for `kind=file` | Node-local file path |
| `text` | string | req for `kind=memory` | Memory text |
| `tags` | array[string] | no | For memory kind |
| `source` | string | no | Memory source label |
| `options.force_reindex` | boolean | no | Default false |
| `trace` | object | no | Request tracing |

Example request (`file`):

```json
{
  "kind": "file",
  "path": "/data/docs/report.docx",
  "options": {
    "force_reindex": false
  }
}
```

Example request (`memory`):

```json
{
  "kind": "memory",
  "text": "Remember this project note",
  "tags": ["project"],
  "source": "remote_host"
}
```

### Success response `202`

```json
{
  "job_id": "job_456",
  "status": "accepted"
}
```

### Errors

- `VALIDATION` (`400`)
- `UNAUTHORIZED` (`401`)
- `INDEX_BUSY` (`409`, retryable)
- `UNAVAILABLE` (`503`, retryable)
- `INTERNAL` (`500`)

## 5.5 `POST /control/reindex`

Purpose: trigger controlled reindex operations.

### Request body

| Field | Type | Required | Notes |
| :--- | :--- | :--- | :--- |
| `scope.mode` | string | yes | `all`, `path_prefix`, `source_kind`, `document_id` |
| `scope.value` | string | req except `mode=all` | Scope selector |
| `options.force` | boolean | no | Default false |
| `trace` | object | no | Request tracing |

Example request:

```json
{
  "scope": {
    "mode": "path_prefix",
    "value": "file:///data/docs/"
  },
  "options": {
    "force": true
  }
}
```

### Success response `202`

```json
{
  "job_id": "job_789",
  "status": "accepted"
}
```

### Errors

- `VALIDATION` (`400`)
- `UNAUTHORIZED` (`401`)
- `INDEX_BUSY` (`409`, retryable)
- `UNAVAILABLE` (`503`, retryable)
- `INTERNAL` (`500`)

## 6. Degraded/fallback semantics contract

Node API does not directly enforce client UX; Host Backend applies fallback policy.
When node retrieval/control calls fail, Host Backend should follow degraded-mode rules in [`distributed-future-plan.md`](distributed-future-plan.md).

## 7. Mode availability

| Mode | Node API usage |
| :--- | :--- |
| `standalone` | Not required |
| `host_edge` | Required for remote retrieval/ingest |
| `hybrid` | Required for remote branch of retrieval/ingest |
| `ios_companion` | Indirect (through Host Backend mode) |
