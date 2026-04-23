# SRS — MP1 Distributed Architecture Foundation

## 1. Scope

This SRS defines software requirements for MP1 architectural groundwork to support:

- `standalone`
- `host_edge`
- `hybrid`
- `ios_companion`

It focuses on architecture/API contracts and behavior consistency, not full distributed implementation.

## 2. Definitions

Canonical roles:

- **Client**: web/desktop/mobile app surface
- **Host Backend**: primary API + orchestrator runtime
- **Edge Node**: optional ingest/retrieval/index runtime

See full terminology in [`distributed-future-plan.md`](distributed-future-plan.md).

## 3. Architectural Requirements

### AR-1 Backend contract abstraction

System SHALL define and use these backend interfaces:

- `RetrievalBackend`
- `IngestBackend`
- `LlmBackend`

Orchestrator SHALL depend on interfaces rather than deployment-specific branches.

### AR-2 Deployment mode compatibility

System SHALL support configuration-driven mode selection for:

- `standalone`
- `host_edge`
- `hybrid`
- `ios_companion`

### AR-3 Role and endpoint boundaries

System SHALL preserve API boundaries:

- **Client API** (`client -> host`) documented in [`client-api.md`](client-api.md)
- **Node API** (`host -> edge`) documented in [`distributed-future-plan.md`](distributed-future-plan.md)

### AR-4 Distributed transport

Node API transport SHALL be HTTPS REST in MP1 baseline.
gRPC MAY be added later without breaking Client API contracts.

### AR-5 Security baseline

Distributed mode v1 SHALL use TLS + bearer token.
mTLS SHALL remain a planned/compatible extension but is not mandatory in MP1.

### AR-6 Hybrid retrieval default

Hybrid mode SHALL use balanced merge policy by default.

### AR-7 Degraded behavior contract

When remote retrieval is unavailable:

- system SHALL fallback to local retrieval when available
- response SHALL include degraded metadata
- client SHALL show a visible limited-source notice

If no retrieval path is available, system SHALL return retryable `UNAVAILABLE`.

## 4. Functional Requirements

### FR-1 Client API continuity

Existing client endpoints under `/api/v1/*` SHALL remain stable for MP1.

### FR-2 Node API minimum surface

Node API SHALL define at minimum:

- `GET /health`
- `GET /index/status`
- `POST /retrieve`
- `POST /ingest`
- `POST /control/reindex`

### FR-3 Error envelope consistency

Node APIs SHALL use a shared error envelope and normalized error codes (`VALIDATION`, `UNAUTHORIZED`, `UNAVAILABLE`, etc.).

### FR-4 Mode placement clarity

System documentation SHALL include block placement per mode for Client / Host Backend / Edge Node.

### FR-5 Admin/Debug mode control

System SHALL provide restricted Admin/Debug mode APIs for:

- status and diagnostics access
- reindex and restart operations
- cold-start operation
- index reset operation

Factory reset MAY be implemented as optional high-risk control.

Admin/Debug controls SHALL require explicit enablement and stronger confirmation for destructive actions.

## 5. Non-Functional Requirements

### NFR-1 Backward compatibility

Standalone behavior SHALL not regress due to MP1 architecture refactoring.

### NFR-2 Observability

Degraded/fallback state SHALL be observable in response metadata and logs.

### NFR-4 Operational safety

Destructive Admin/Debug operations SHALL be auditable and accompanied by explicit operator confirmation.

### NFR-3 Extensibility

Architecture SHALL remain compatible with future:

- mTLS hardening
- gRPC node transport
- additional client platforms

## 6. Out of Scope (MP1)

- Complete implementation of all distributed runtime features
- Mandatory mTLS rollout
- gRPC implementation
- Full mobile-local source execution stack

## 7. Verification Criteria

MP1 SRS acceptance is satisfied when:

1. Backend interfaces are documented and referenced as normative architecture contracts.
2. Client API vs Node API ownership is unambiguous.
3. Decisions D2-D5 are reflected in specs.
4. Degraded-mode behavior is defined in both API metadata and client UX expectations.
5. Mode/block placement is documented in diagrams and text.
6. Admin/Debug control support and safeguards are documented.
7. Pre-implementation go/no-go review is completed using [`mp1-verification-checklist.md`](mp1-verification-checklist.md).

## 8. Traceability

- Product requirements: [`prd-mp1-distributed.md`](prd-mp1-distributed.md)
- Architecture: [`architecture.md`](architecture.md)
- Client API: [`client-api.md`](client-api.md)
- Distributed contracts and decisions: [`distributed-future-plan.md`](distributed-future-plan.md)
- Test approach: [`test-plan.md`](test-plan.md)
- Pre-implementation verification gate: [`mp1-verification-checklist.md`](mp1-verification-checklist.md)
- First implementation PR scope: [`mp1-pr1.md`](mp1-pr1.md)
