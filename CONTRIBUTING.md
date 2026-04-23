# Contributing to MemoryAgent

## Pull requests — merge target

**Open pull requests against the `ma-dist` branch** — the project’s default **Git integration** branch for ongoing work (including **MP1 / distributed** specs and code).

**`ma-dist` is not macOS-only.** The name reflects **MemoryAgent + distributed** integration, not “Macintosh exclusive.” Cross-platform **host** work, shared core, and documentation land here too; mac-specific behavior (for example EventKit) lives behind **adapters** per [`docs/spec/architecture.md`](docs/spec/architecture.md).

- When creating a PR on GitHub, set **base** to **`ma-dist`** (not `main`).

From the CLI (example):

```bash
gh pr create --base ma-dist --head your-feature-branch
```

## `main` branch policy

**`ma-dist` → `main` merges are gated:** do **not** merge **`ma-dist` into `main`** until **all product phases 0–8** in [`docs/spec/prd-full-product.md`](docs/spec/prd-full-product.md) are **verified complete** (or explicitly waived where marked N/A), per [`docs/spec/ma-dist-promotion-checklist.md`](docs/spec/ma-dist-promotion-checklist.md) **§0.1**.

Until then:

- Treat **`ma-dist`** as the **source of truth** for ongoing integration.
- Treat **`main`** as a **stable snapshot** line; it may **lag** `ma-dist` on purpose.
- On **GitHub**, use the branch selector (**`ma-dist`**) to browse the latest **README** and **`docs/spec/`** tree.

When `ma-dist` **is** ready for promotion, complete **[`docs/spec/ma-dist-promotion-checklist.md`](docs/spec/ma-dist-promotion-checklist.md)**, then merge to **`main`** in a deliberate step (pull request or controlled merge) and record the promotion in **§0** of that checklist.

## Checks

- Run **`pytest`** from `services/core` before pushing when you touch Python (`cd services/core && source .venv/bin/activate && pytest tests/ -q`).
- See [`docs/spec/test-plan.md`](docs/spec/test-plan.md) for milestone-related coverage.
