# `ma-dist` → `main` promotion checklist

Purpose: define **when `ma-dist` is “fully complete”** enough to merge into **`main`** ([`CONTRIBUTING.md`](../../CONTRIBUTING.md) `main` branch policy). Complete this checklist **per promotion** (each release or snapshot may tighten or relax items—record the variant in **§0**).

## 0) Record this promotion

| Field | Value |
| :--- | :--- |
| **Promotion name / version** | e.g. `v0.2.0-ma-dist-complete` |
| **Phases in scope** | e.g. PRD Phases 0–3 only, or 0–4, etc. ([`prd-full-product.md`](prd-full-product.md)) |
| **Target `main` commit or tag** | (after merge) |
| **Owner** | |
| **Date** | |

---

## 1) Engineering completeness

- [ ] **`pytest`** (or agreed CI) green on `ma-dist` for `services/core/tests/` at promotion SHA.
- [ ] **Smoke:** `GET /api/v1/health`, config round-trip, one chat path with mock or agreed LLM per [`test-plan.md`](test-plan.md).
- [ ] **No known P0/P1 defects** open for in-scope phases (or each has explicit waiver + owner).

---

## 2) Requirements and specs alignment

- [ ] **[`srs-full-product.md`](srs-full-product.md)** clauses for **in-scope phases** are satisfied or explicitly waived with product sign-off.
- [ ] **[`client-api.md`](client-api.md)** matches shipped behavior for any new/changed routes in this promotion.
- [ ] If Node/edge in scope: **[`node-api.md`](node-api.md)** and integration tests exist or waiver documented.
- [ ] **[`milestones.md`](milestones.md)** checkboxes for in-scope items updated to match reality.

---

## 3) Documentation and discoverability

- [ ] **[`README.md`](../../README.md)** on `ma-dist` reflects install, stack, and “browse `ma-dist` on GitHub” guidance.
- [ ] **[`docs/spec/README.md`](README.md)** lists new normative docs added during this integration line.
- [ ] **OpenAPI** (`/api/v1/openapi.json`) regenerated or verified if routes changed.

---

## 4) Security and privacy (when applicable)

- [ ] No secrets or tokens committed; log redaction rules respected for new features ([`google-calendar-integration.md`](google-calendar-integration.md) if OAuth shipped).
- [ ] **TLS/auth** story documented for any new networked surface ([`distributed-future-plan.md`](distributed-future-plan.md)).

---

## 5) Release mechanics

- [ ] **Merge plan:** single PR `ma-dist` → `main` (or documented merge steps), with no unintended partial merges.
- [ ] **Post-merge:** default branch `main` builds and README render as expected on GitHub; spot-check front page.

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
- [`prd-full-product.md`](prd-full-product.md) — phased roadmap  
- [`srs-full-product.md`](srs-full-product.md) — SHALL requirements by phase  
- [`mp1-verification-checklist.md`](mp1-verification-checklist.md) — pre-MP1-code gate (different artifact)
