# M5 — Packaging and distribution decision

| Field | Value |
| :--- | :--- |
| **Status** | Adopted |
| **Scope** | Phase 1 (M5) install story vs retail bundle ([`prd-full-product.md`](prd-full-product.md) §6 Phase 1, [`milestones.md`](milestones.md) M5) |

## Decision

1. **Current stage — no product bundle.** Distribution is **documented source + scripts**: repository `README.md`, `services/core` venv install, `./scripts/setup-dev.sh` and `./scripts/run.sh` per [`prerequisites.md`](prerequisites.md) §7. There is **no** signed `.app`, **no** `launchd` plist shipped as a first-class artifact, and **no** installer PKG/DMG for end users at this time.

2. **After substantive product development is complete**, the project **may** move to a **signed macOS application** (Developer ID + notarization, or App Store only if requirements allow) as the primary consumer install. That work is **explicitly deferred** until then.

3. **Optional later** (not committed): a **documented `launchd` LaunchAgent** for power users or home-server installs remains a valid **add-on** without replacing the “no bundle until signed app” stance.

## Rationale

- Shipping a bundle early duplicates effort (signing, TCC host identity, updates) while the core product and APIs are still moving quickly on **`ma-dist`**.
- Developer install already satisfies **scriptable / documented** smoke paths for engineering and QA ([`test-plan.md`](test-plan.md) MT-M5-04 can be run against this path until a retail installer exists).
- A **signed .app** gives the best long-term **privacy prompt identity** and user experience on macOS; deferring it avoids premature lock-in to a thin launcher before the runtime layout is stable.

## Related

- [`milestones.md`](milestones.md) — M5 packaging line  
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — branch and integration policy  
- [`prerequisites.md`](prerequisites.md) §7 — one-shot dev scripts vs future end-user packaging
