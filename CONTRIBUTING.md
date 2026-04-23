# Contributing to MemoryAgent

## Pull requests — merge target

**Open pull requests against the `ma-dist` branch** — the project’s default **Git integration** branch for ongoing work (including **MP1 / distributed** specs and code).

**`ma-dist` is not macOS-only.** The name reflects **MemoryAgent + distributed** integration, not “Macintosh exclusive.” Cross-platform **host** work, shared core, and documentation land here too; mac-specific behavior (for example EventKit) lives behind **adapters** per [`docs/spec/architecture.md`](docs/spec/architecture.md).

- When creating a PR on GitHub, set **base** to **`ma-dist`** (not `main`), unless you are explicitly doing a release promotion that the maintainers agreed to target `main`.

From the CLI (example):

```bash
gh pr create --base ma-dist --head your-feature-branch
```

## Checks

- Run **`pytest`** from `services/core` before pushing when you touch Python (`cd services/core && source .venv/bin/activate && pytest tests/ -q`).
- See [`docs/spec/test-plan.md`](docs/spec/test-plan.md) for milestone-related coverage.
