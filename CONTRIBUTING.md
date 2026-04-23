# Contributing to MemoryAgent

## Pull requests — merge target

**Open pull requests against the `ma-dist` branch** (integration branch for distributed / MP1 work and ongoing features). Merges into `ma-dist` are the default review path.

- When creating a PR on GitHub, set **base** to **`ma-dist`** (not `main`), unless you are explicitly doing a release promotion that the maintainers agreed to target `main`.

From the CLI (example):

```bash
gh pr create --base ma-dist --head your-feature-branch
```

## Checks

- Run **`pytest`** from `services/core` before pushing when you touch Python (`cd services/core && source .venv/bin/activate && pytest tests/ -q`).
- See [`docs/spec/test-plan.md`](docs/spec/test-plan.md) for milestone-related coverage.
