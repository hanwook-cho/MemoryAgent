# SRS — MemoryAgent (full product)

## 1. Scope

This SRS defines **software requirements** (normative **SHALL** / **SHOULD** statements) for **MemoryAgent** across the **full product lifecycle** described in [`prd-full-product.md`](prd-full-product.md) (Phases 0–8).

| In scope | Out of scope (this document) |
| :--- | :--- |
| Requirements traceable to [`requirement.md`](../../requirement.md), [`prd-full-product.md`](prd-full-product.md), and linked specs | Implementation source code except as contract references |
| Behavior of Host Backend, Client surfaces, and (when built) Edge Node per published APIs | Vendor-internal Google/Microsoft implementation details |
| **MP1** subset | **Normative MP1-only** detail remains in [`srs-mp1-distributed.md`](srs-mp1-distributed.md); this SRS **incorporates** it by reference and **extends** it for later phases |

---

## 2. Normative references

| ID | Document |
| :--- | :--- |
| R-REQ | [`requirement.md`](../../requirement.md) |
| R-PRD | [`prd-full-product.md`](prd-full-product.md) |
| R-MP1-PRD | [`prd-mp1-distributed.md`](prd-mp1-distributed.md) |
| R-MP1-SRS | [`srs-mp1-distributed.md`](srs-mp1-distributed.md) |
| R-ARCH | [`architecture.md`](architecture.md) |
| R-DIST | [`distributed-future-plan.md`](distributed-future-plan.md) |
| R-CLIENT | [`client-api.md`](client-api.md) |
| R-NODE | [`node-api.md`](node-api.md) |
| R-DATA | [`data-model.md`](data-model.md) |
| R-TEST | [`test-plan.md`](test-plan.md) |
| R-MILE | [`milestones.md`](milestones.md) |
| R-CAL-G | [`google-calendar-integration.md`](google-calendar-integration.md) |
| R-FMT | [`document-format-vnext-plan.md`](document-format-vnext-plan.md) |
| R-PERM | [`permissions-matrix.md`](permissions-matrix.md) |

---

## 3. Definitions and acronyms

Terms **Client**, **Host Backend**, **Edge Node**, **Ingest**, **Retrieval**, **Degraded mode**, and deployment mode names SHALL follow **R-DIST** Terminology unless this SRS defines a stricter rule.

**Baseline product** means Phases **0** and ongoing **1** in **R-PRD** unless a later phase is explicitly enabled by configuration and implementation.

---

## 4. System context (software)

The software system under requirement comprises:

1. **Host Backend** process(es) exposing **R-CLIENT** on HTTP(S), orchestrating RAG, tools, and configuration.
2. **Web Client** (and optional future native clients) consuming **R-CLIENT**.
3. **Optional Edge Node** process(es) exposing **R-NODE** when Phase 4 is implemented.
4. **Optional bridges** (e.g. macOS calendar) as adapters from **R-ARCH**.

---

## 5. Functional requirements by phase

### 5.1 Phase 0 — Core platform **(baseline; largely shipped)**

| ID | Requirement |
| :--- | :--- |
| SR-P0-1 | The Host Backend SHALL implement **M0–M4** acceptance themes in **R-MILE** and automated/manual checks in **R-TEST** for items marked complete. |
| SR-P0-2 | Chat with retrieval SHALL produce **citations** or an explicit empty retrieval path consistent with **R-CLIENT** and **R-DATA**. |
| SR-P0-3 | File ingestion SHALL honor **watched roots**, ignore globs, debouncing, and supported suffixes per **R-DATA** and **R-ARCH**. |
| SR-P0-4 | Calendar tools on macOS SHALL use **EventKit** (or documented bridge) and SHALL surface **PERMISSION_DENIED** when TCC denies access, per **R-PERM** and **R-CLIENT**. |
| SR-P0-5 | The system SHALL NOT require a wide-area network for **core** chat, memory ingest, or local file retrieval in **standalone** configuration. |

---

### 5.2 Phase 1 — Product hardening **(M5)**

| ID | Requirement |
| :--- | :--- |
| SR-P1-1 | The Host Backend SHALL support **repeatable** measurement of latency and resource usage per **R-TEST** M5 and **R-REQ** NFRs, using a documented hardware profile. |
| SR-P1-2 | Log output SHALL be **bounded** in default configuration (rotation or truncation policy documented and tested per **R-TEST**). |
| SR-P1-3 | Installation or launch SHALL be **scriptable** or documented such that a clean-environment smoke test exits successfully per **R-PRD** Phase 1 acceptance. |

---

### 5.3 Phase 2 — Google Calendar **(opt-in)**

| ID | Requirement |
| :--- | :--- |
| SR-P2-1 | When **Include Google Calendar** is **off**, the system SHALL NOT invoke Google Calendar APIs for calendar features; **local-only** behavior SHALL match **R-CAL-G**. |
| SR-P2-2 | When **Include Google Calendar** is **on** only after **successful OAuth**, the system SHALL merge **local** and **Google** read results per **R-CAL-G** (sort order, duplicate display, labels). |
| SR-P2-3 | For writes when both sources exist and the user has not specified a target, the Client or Host flow SHALL **prompt** for calendar target before mutating state, per **R-CAL-G**. |
| SR-P2-4 | When Google is unavailable but Include is on, the system SHALL **soft-degrade**: local calendar remains usable with a **user-visible** notice, per **R-CAL-G**. |
| SR-P2-5 | **Disconnect Google** SHALL revoke/delete tokens and disable inclusion per **R-CAL-G**; **Include off** SHALL retain tokens only if **R-CAL-G** “decided behavior” is implemented as specified. |
| SR-P2-6 | Operational logs SHALL NOT contain OAuth **secrets** (refresh/access tokens, auth codes) per **R-CAL-G** logging rules. |

---

### 5.4 Phase 3 — MP1 distributed foundation

| ID | Requirement |
| :--- | :--- |
| SR-P3-0 | Software labeled **MP1** SHALL satisfy **R-MP1-SRS** in full. |
| SR-P3-1 | With `deployment_mode` = `standalone`, runtime behavior for existing **R-CLIENT** features SHALL remain **backward compatible** with Phase 0 baselines unless **R-MP1-PRD** explicitly documents an allowed breaking change. |
| SR-P3-2 | `GET /health` SHALL expose a **`deployment`** object (`mode`, `degraded`, `degraded_reason`) consistent with **R-CLIENT** and **R-PRD** Phase 3 / **mp1-pr2**. |
| SR-P3-3 | Unknown `deployment_mode` values in persisted config SHALL normalize to **`standalone`** with a warning on load, or SHALL be rejected on write per **R-TEST** §7.1 policy—**one** behavior SHALL be implemented and tested. |

---

### 5.5 Phase 4 — Distributed operations **(host + edge)**

| ID | Requirement |
| :--- | :--- |
| SR-P4-1 | When `host_edge`, `hybrid`, or related modes are **fully implemented**, the Host Backend SHALL communicate with Edge using **R-NODE** over **HTTPS** with **TLS** and **bearer** authentication baseline per **R-MP1-SRS** AR-4 / AR-5 and **R-DIST**. |
| SR-P4-2 | On remote failure with a local path available, the Host Backend SHALL **soft-degrade** per **R-MP1-SRS** AR-7 and SHALL expose **degraded** semantics to clients per **R-DIST**. |
| SR-P4-3 | Hybrid retrieval SHALL implement the **default merge policy** documented in **R-DIST** / **R-MP1-SRS** AR-6 unless a user-visible configuration overrides it. |

---

### 5.6 Phase 5 — Mobile companion

| ID | Requirement |
| :--- | :--- |
| SR-P5-1 | Any **iOS/Android** companion SHALL use **R-CLIENT** (or a documented superset) for host-backed operations; SHALL NOT bypass Host policy for privileged tools without explicit design in **R-DIST**. |
| SR-P5-2 | Local-on-mobile sources (files, calendars, journals) SHALL be **opt-in** and **policy-gated** per **R-DIST** mobile constraints; SHALL NOT imply always-on background ingestion where the platform forbids it. |
| SR-P5-3 | Verification criteria for a given mobile release SHALL be recorded in a **mobile SRS** or annex before GA of that client. |

---

### 5.7 Phase 6 — Format expansion **(V-next)**

| ID | Requirement |
| :--- | :--- |
| SR-P6-1 | Each new format SHALL preserve **incremental indexing** semantics (**R-DATA**, file index DB) unless a migration document explicitly exempts it. |
| SR-P6-2 | Each new format SHALL define **max size**, **timeout**, and **failure logging** analogous to current extractors per **R-FMT** and **R-TEST**. |
| SR-P6-3 | Rollout order for formats SHOULD follow **R-FMT** recommended phases unless risk review reorders with documentation. |

---

### 5.8 Phase 7 — Optional OS depth and native shell

| ID | Requirement |
| :--- | :--- |
| SR-P7-1 | Reminders, Notes automation, or menu-bar features SHALL ship only with **R-PERM**-aligned prompts and **R-MILE** optional acceptance. |
| SR-P7-2 | Optional native shell SHALL NOT be required for **core** memory or chat workflows (**R-REQ** UI-1 baseline). |

---

### 5.9 Phase 8 — Enterprise **(future)**

| ID | Requirement |
| :--- | :--- |
| SR-P8-1 | Enterprise features (mTLS mandatory, SSO, multi-tenant) SHALL be specified in a **future annex or SRS** before implementation; until then, software SHALL remain compatible with **mTLS-ready** narrative in **R-DIST** without mandating enterprise configuration. |

---

## 6. Non-functional requirements (product-wide)

| ID | Requirement |
| :--- | :--- |
| NFR-FP-1 | **Privacy:** Default configuration SHALL NOT transmit user memory content or chat transcripts to third-party servers for **core** operation (**R-REQ** FR-8, NFR-3). |
| NFR-FP-2 | **Performance:** The system SHOULD meet **R-REQ** NFR-1 / NFR-2 where measured in **R-TEST** M5; gaps SHALL be documented with rationale. |
| NFR-FP-3 | **Security:** Authentication for **R-CLIENT** SHALL remain effective; secrets SHALL NOT appear in logs (**R-TEST**, calendar spec, ops hygiene). |
| NFR-FP-4 | **Maintainability:** New features SHALL update **R-CLIENT** and/or **R-NODE** and **R-TEST** in the same release train when behavior is user-visible. |
| NFR-FP-5 | **Accessibility of failure:** Error responses SHALL use stable **codes** and shapes per **R-CLIENT** for programmatic and UI handling. |

---

## 7. Interface requirements (summary)

| Interface | Requirement |
| :--- | :--- |
| **R-CLIENT** | Host Backend SHALL conform to published routes, auth, and error envelopes; changes SHALL be versioned or backward-compatible per release policy. |
| **R-NODE** | Edge SHALL conform to **R-NODE** when Phase 4 is in scope; optional gRPC SHALL NOT break HTTPS clients when introduced (**R-MP1-SRS** AR-4). |

---

## 8. Verification matrix (phases → evidence)

| Phase | Primary evidence |
| :--- | :--- |
| 0 | **R-MILE** checkboxes + **R-TEST** M0–M4 suites |
| 1 | **R-TEST** §7 M5 + benchmark artifacts |
| 2 | **R-CAL-G** criteria + dedicated integration tests |
| 3 | **R-MP1-SRS** §7 + **R-TEST** §7.1–§7.2 + **mp1-verification-checklist** (pre-GO) |
| 4 | Host+edge integration tests + security checklist (**R-DIST**) |
| 5 | Mobile SRS annex + Client API contract tests |
| 6 | Per-format tests in **R-TEST** + **R-FMT** exit criteria |
| 7 | Optional milestone tests in **R-MILE** / **R-TEST** §10 |
| 8 | Future enterprise SRS |

---

## 9. Compliance statement

Implementation releases **SHALL** maintain traceability: for each **SR-P** / **NFR-FP** clause exercised in a release, at least one automated or documented manual test in **R-TEST** (or successor) SHALL exist or SHALL be explicitly waived with product approval.

---

## 10. Traceability

| Document | Relationship |
| :--- | :--- |
| [`prd-full-product.md`](prd-full-product.md) | Product phases and goals — **parent** of this SRS |
| [`srs-mp1-distributed.md`](srs-mp1-distributed.md) | **Subset** SRS for MP1 — **normative** where SR-P3-0 applies |
| [`prd-mp1-distributed.md`](prd-mp1-distributed.md) | MP1 PRD — refines Phase 3 |
| [`requirement.md`](../../requirement.md) | Original SRS-style requirements — **SHALL** be satisfied where not superseded by later explicit clauses |
