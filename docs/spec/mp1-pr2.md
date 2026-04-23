# MP1 — PR-2 (degraded metadata on health)

## Title

**MP1-PR2: Health exposes deployment mode and degraded flag**

## Goal

Surface **`deployment_mode`** and a **`degraded`** indicator on **`GET /api/v1/health`** so clients can show limited-capacity notices before remote retrieval/ingest is implemented.

## Behavior

- **`deployment_mode` == `standalone`:** `deployment.degraded` is **`false`**; `degraded_reason` is **`null`**.
- **Any other known mode** (`host_edge`, `hybrid`, `ios_companion`): `deployment.degraded` is **`true`** with a stable **reason** string until Node/remote adapters are wired.

Chat payloads are unchanged in PR-2; future PRs may add `meta.degraded` on chat responses per distributed plan.

## References

- [`client-api.md`](client-api.md) — health shape
- [`mp1-pr1.md`](mp1-pr1.md) — prior PR
- [`distributed-future-plan.md`](distributed-future-plan.md) — degraded UX norms
