# PRD — MP1 Distributed Architecture Foundation

## 1. Purpose

Define the product requirements for MP1: introducing a distributed-capable architecture while preserving current standalone behavior and user experience.

This PRD is implementation-oriented and based on:

- [`architecture.md`](architecture.md)
- [`client-api.md`](client-api.md)
- [`distributed-future-plan.md`](distributed-future-plan.md)
- [`data-model.md`](data-model.md)
- [`test-plan.md`](test-plan.md)
- [`mp1-verification-checklist.md`](mp1-verification-checklist.md)

## 2. Problem Statement

Current implementation works well in single-node local mode, but future deployments require:

- portable topology (host + optional edge node)
- consistent behavior across standalone/distributed/hybrid/mobile-companion modes
- clear API boundaries between Client API and Node API
- resilient fallback when remote systems are unavailable

Without this foundation, future feature delivery (edge indexing, hybrid retrieval, mobile clients) risks branching logic and inconsistent UX.

## 3. Goals (MP1)

- Preserve one orchestration logic path across deployment modes via backend interfaces.
- Formalize runtime role model: **Client**, **Host Backend**, **Edge Node**.
- Stabilize API boundaries:
  - Client API (`client -> host`)
  - Node API (`host -> edge`)
- Lock distributed baseline decisions:
  - Node transport: HTTPS REST first
  - Security v1: TLS + bearer token (mTLS-ready)
  - Hybrid default: balanced merge
  - Degraded behavior: soft degrade with explicit metadata and user notice

## 4. Non-Goals (MP1)

- Full implementation of edge services and all deployment modes
- gRPC implementation
- mTLS mandatory rollout
- mobile-first runtime migration
- OCR/format expansion beyond already-delivered baseline

## 5. Users and Primary Scenarios

- Existing standalone users who need no behavior regression.
- Advanced users operating host+edge topology for always-on indexing.
- Companion mobile users consuming Host Backend APIs.

Primary scenario groups:

- `standalone`: all services local.
- `host_edge`: retrieval/ingest delegated to edge.
- `hybrid`: local + edge retrieval fan-out and merge.
- `ios_companion`: mobile client calling Host Backend.

## 6. Functional Requirements

### FR-1: Backend interface model

System MUST define and use backend contracts:

- `RetrievalBackend`
- `IngestBackend`
- `LlmBackend`

Orchestrator MUST depend on interfaces, not deployment-specific conditionals.

### FR-2: Deployment mode compatibility

System MUST support configuration-level mode selection:

- `standalone`
- `host_edge`
- `hybrid`
- `ios_companion`

### FR-3: Client API stability

Client API contract in [`client-api.md`](client-api.md) MUST remain the primary client integration surface across web/desktop/mobile clients.

### FR-4: Node API definition

Node API contract for host->edge interactions MUST be specified and versioned in [`distributed-future-plan.md`](distributed-future-plan.md).

### FR-5: Fallback and degraded behavior

When remote edge retrieval is unavailable:

- system SHOULD fallback to local retrieval when available
- response MUST indicate degraded state (`meta.degraded=true` + reason)
- client MUST present limited-source warning

If no retrieval path is available, system MUST return retryable `UNAVAILABLE`.

### FR-6: Admin/Debug control mode

System MUST support an explicit Admin/Debug mode for operational control and diagnostics from client surfaces.

Minimum support:

- status/diagnostics retrieval
- reindex/restart control
- cold-start operation
- index reset operation (destructive)

Optional high-risk support:

- full factory reset

Safety requirements for Admin/Debug mode:

- explicit enablement (not default user mode)
- stronger confirmation for destructive actions
- auditable action logs
- clear user messaging for destructive consequences

## 7. Non-Functional Requirements

- **NFR-1 Compatibility:** current standalone behavior remains intact.
- **NFR-2 Security baseline:** distributed mode v1 uses TLS + bearer token.
- **NFR-3 Extensibility:** architecture remains mTLS-ready and gRPC-ready.
- **NFR-4 Operability:** errors and degraded state are observable via explicit response metadata.

## 8. API and Message Requirements

- Client API endpoints remain under `/api/v1/*`.
- Node API includes at minimum:
  - `GET /health`
  - `GET /index/status`
  - `POST /retrieve`
  - `POST /ingest`
  - `POST /control/reindex`
- Shared error envelope and codes must be consistent across node APIs.

## 9. Acceptance Criteria

MP1 architecture foundation is complete when:

- all four mode diagrams and block placement definitions are approved
- backend contracts are documented and accepted
- security/transport/fallback decisions are documented (D2-D5)
- Client API vs Node API ownership is unambiguous
- design review signs off without unresolved critical ambiguities
- admin/debug control requirements and safeguards are documented and agreed
- pre-implementation go/no-go review is completed using [`mp1-verification-checklist.md`](mp1-verification-checklist.md)

## 10. Risks and Mitigations

- **Risk:** documentation drift between architecture and API docs  
  **Mitigation:** explicit ownership links and review gates.
- **Risk:** fallback ambiguity causes inconsistent client UX  
  **Mitigation:** normative degraded metadata and warning requirements.
- **Risk:** distributed scope creeps into MP1 implementation  
  **Mitigation:** explicit non-goals and phased rollout after architecture sign-off.

## 11. Delivery Output (MP1)

- Approved architecture and API documents
- Finalized decision record (transport/security/hybrid/fallback)
- Branch-ready baseline for MP1 implementation planning

### 11.1 First implementation PR (PR-1)

The first merged code change for MP1 is defined in [`mp1-pr1.md`](mp1-pr1.md): backend interface scaffolding + `deployment_mode` (default `standalone`) with **no user-visible behavior change** in default configuration.
