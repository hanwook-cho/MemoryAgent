# `ma-dist` → `main` promotion checklist

Purpose: define **when `ma-dist` is “fully complete”** enough to merge into **`main`** ([`CONTRIBUTING.md`](../../CONTRIBUTING.md) `main` branch policy).

**Normative rule:** **`main` promotion requires ALL product phases 0 through 8** in [`prd-full-product.md`](prd-full-product.md) §6 to be **verified complete**, with evidence (or **explicit product waiver**) recorded below. **Partial** phase subsets are **not** sufficient unless this policy is **revised in writing** (PR to `ma-dist` updating this file and [`CONTRIBUTING.md`](../../CONTRIBUTING.md)).

Complete this checklist **once per promotion** to `main`; keep the filled copy (e.g. in the merge PR body or release notes).

## 0) Record this promotion

| Field | Value |
| :--- | :--- |
| **Promotion name / version** | e.g. `v1.0.0-full-product` |
| **Phases in scope** | **Fixed:** **0 – 8** ([`prd-full-product.md`](prd-full-product.md) §6) |
| **Target `main` commit or tag** | (after merge) |
| **Owner** | |
| **Date** | |

---

## 0.1) Phase verification log (required)

Each phase **SHALL** be **Verified = Y** with a pointer to tests, signed review, or **Waiver** (owner + rationale). **N** blocks promotion unless waived.

| Phase | Name (see R-PRD §6) | Verified (Y/N) | Evidence (path, PR, test run) or waiver |
| :---: | :--- | :---: | :--- |
| 0 | Foundation (M0–M4 shipped) | | |
| 1 | Product hardening (M5) | | |
| 2 | Google Calendar (opt-in) | | |
| 3 | MP1 distributed foundation | | |
| 4 | Distributed operations (host + edge) | | |
| 5 | Mobile companion | | |
| 6 | Format expansion (V-next) | | |
| 7 | Optional OS depth / native shell | | |
| 8 | Enterprise / future (or waived as N/A) | | |

**Gate:** all phases **Y** or **N/A with approved waiver** in the **Evidence** column.

---

## 1) Engineering completeness

- [ ] **`pytest`** (or agreed CI) green on `ma-dist` for `services/core/tests/` at promotion SHA.
- [ ] **Smoke:** `GET /api/v1/health`, config round-trip, one chat path with mock or agreed LLM per [`test-plan.md`](test-plan.md).
- [ ] **No known P0/P1 defects** open against **phases 0–8** (or each has explicit waiver + owner in §0.1).

---

## 2) Requirements and specs alignment

- [ ] **[`srs-full-product.md`](srs-full-product.md)** — all **SR-P0** … **SR-P8** and applicable **NFR-FP** satisfied or waived with product sign-off.
- [ ] **[`client-api.md`](client-api.md)** matches shipped behavior for the promotion.
- [ ] If Phase 4+ shipped: **[`node-api.md`](node-api.md)** and integration tests exist or waiver in §0.1.
- [ ] **[`milestones.md`](milestones.md)** and **R-PRD** phase descriptions match shipped reality.

---

## 3) Documentation and discoverability

- [ ] **[`README.md`](../../README.md)** on `ma-dist` reflects install, stack, and GitHub branch guidance.
- [ ] **[`docs/spec/README.md`](README.md)** lists all normative docs for shipped scope.
- [ ] **OpenAPI** (`/api/v1/openapi.json`) verified if routes changed.

---

## 4) Security and privacy (when applicable)

- [ ] No secrets or tokens committed; log redaction rules respected ([`google-calendar-integration.md`](google-calendar-integration.md) if OAuth shipped).
- [ ] **TLS/auth** documented for every networked surface in scope ([`distributed-future-plan.md`](distributed-future-plan.md)).

---

## 5) Release mechanics

- [ ] **Merge plan:** single PR `ma-dist` → `main` (or documented merge steps), with no unintended partial merges.
- [ ] **Post-merge:** default branch `main` builds; README and spec tree render on GitHub.

---

## 6) Sign-off

| Role | Name | Date | GO / HOLD |
| :--- | :--- | :--- | :--- |
| Engineering | | | |
| Product / owner | | | |

**Decision:** `GO` / `HOLD`  
**Notes:**

---

## Related documents

- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — `main` branch policy  
- [`prd-full-product.md`](prd-full-product.md) — phased roadmap §6  
- [`srs-full-product.md`](srs-full-product.md) — SHALL requirements and §8 verification matrix  
- [`mp1-verification-checklist.md`](mp1-verification-checklist.md) — pre-MP1-code gate (different artifact)
