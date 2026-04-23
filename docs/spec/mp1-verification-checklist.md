# MP1 Pre-Implementation Verification Checklist

Purpose: provide a single go/no-go artifact before starting MP1 implementation.

Scope: distributed architecture foundation for `Client`, `Host Backend`, and `Edge Node` across `standalone`, `host_edge`, `hybrid`, and `ios_companion` modes.

## 1) Document consistency gate

- [ ] Terminology is consistent across:
  - `distributed-future-plan.md`
  - `architecture.md`
  - `client-api.md`
  - `node-api.md`
  - `prd-mp1-distributed.md`
  - `srs-mp1-distributed.md`
- [ ] Role names are canonical everywhere: `Client`, `Host Backend`, `Edge Node`.
- [ ] No conflicting statements about block placement by mode.
- [ ] No conflicting statements about fallback/degraded behavior.

## 2) API contract freeze gate (v1 draft)

- [ ] Node API request/response/error envelopes are fixed for required endpoints:
  - `GET /health`
  - `GET /index/status`
  - `POST /retrieve`
  - `POST /ingest`
  - `POST /control/reindex`
- [ ] Client-facing API required endpoints are fixed for MP1 scope.
- [ ] Admin/Debug endpoints are fixed for MP1 scope:
  - `GET /admin/status`
  - `GET /admin/events`
  - `POST /admin/control/reindex`
  - `POST /admin/control/restart`
  - `POST /admin/control/cold-start`
  - `POST /admin/control/reset-index`
- [ ] Optional endpoints are explicitly marked optional (`factory-reset`, etc.).
- [ ] Error code set is stable and reused consistently (`UNAUTHORIZED`, `FORBIDDEN`, `VALIDATION`, `UNAVAILABLE`, `TIMEOUT`, `INDEX_BUSY`).

## 3) Mode behavior gate

- [ ] For each mode, docs specify:
  - Which blocks run on which platform
  - Which APIs are available
  - What degraded fallback path applies
- [ ] `ios_companion` flow is explicit (endpoint location and data/control flow).
- [ ] Hybrid merge/routing policy for retrieval is documented.

## 4) Security and trust gate

- [ ] Transport policy is explicit:
  - local development: HTTP loopback allowed
  - networked control/data plane: HTTPS required
- [ ] Authentication and authorization boundaries are defined for both Client API and Node API.
- [ ] Admin/Debug mode is explicitly gated (not default mode).
- [ ] Destructive actions require stronger confirmation and audit logging.
- [ ] Secret/token handling and log redaction expectations are documented.

## 5) Operational safety gate

- [ ] Semantics are unambiguous for:
  - restart
  - cold-start
  - reset-index
  - optional factory-reset
- [ ] Destructive operations document:
  - blast radius
  - pre-check/dry-run behavior
  - backup/export guidance
  - expected recovery path
- [ ] Operator-visible result states are defined (`accepted`, `running`, `succeeded`, `failed`).

## 6) NFR readiness gate

- [ ] MP1 NFR targets are measurable and testable:
  - startup/health readiness
  - retrieval latency budget
  - ingest/reindex behavior
  - degraded-mode response correctness
- [ ] Measurement environments are documented (reference hardware/profile).

## 7) Verification and traceability gate

- [ ] Every mandatory PRD/SRS requirement maps to at least one test in `test-plan.md`.
- [ ] Each required API endpoint has contract tests planned.
- [ ] Degraded/fallback paths have explicit integration tests planned.
- [ ] Admin/Debug controls have safety and permission tests planned.

## 8) Implementation readiness gate

- [ ] MP1 is sliced into reviewable milestones (small PR-friendly units).
- [ ] First code PR scope is documented in [`mp1-pr1.md`](mp1-pr1.md).
- [ ] After **GO**, PR-1 **code** verification follows [`test-plan.md`](test-plan.md) **§7.1** (this checklist is **spec** sign-off before implementation; the test plan owns post-merge checks for PR-1).
- [ ] Dependency/risk list is documented with owners and mitigation.
- [ ] Unknowns are tracked as explicit decision items (no hidden assumptions).
- [ ] Go/No-Go decision owner and date are assigned.

---

## Go/No-Go decision

Decision: `GO` / `NO-GO`  
Date: `YYYY-MM-DD`  
Owner: `<name>`  
Notes: `<short rationale and any follow-up constraints>`

