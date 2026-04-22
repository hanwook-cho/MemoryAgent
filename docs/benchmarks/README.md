# Benchmarks

M5 hardening baseline reports live here.

## Generate baseline report

From repo root, with the core server running:

```bash
export MEMORYAGENT_DATA_DIR="${MEMORYAGENT_DATA_DIR:-$PWD/.memoryagent}"
python scripts/benchmark_m5.py --data-dir "$MEMORYAGENT_DATA_DIR" --out docs/benchmarks/m5-latest.md
```

What it records:

- cold/warm first-token latency (`POST /api/v1/chat/stream`)
- cold/warm full-chat latency (`POST /api/v1/chat`)
- idle process snapshots for CPU % and RSS MiB
- machine summary (macOS / CPU / `sw_vers`)

Use consistent model, prompt, and background load when comparing runs.
