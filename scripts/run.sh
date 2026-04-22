#!/usr/bin/env bash
# One-shot: build web if needed, start MemoryAgent core from repo root.
#
# Usage (from anywhere):
#   /path/to/MemoryAgent/scripts/run.sh
# Or from repo root:
#   ./scripts/run.sh
#
# Env:
#   MEMORYAGENT_DATA_DIR — default: <repo>/.memoryagent
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export MEMORYAGENT_DATA_DIR="${MEMORYAGENT_DATA_DIR:-$ROOT/.memoryagent}"

CORE_DIR="$ROOT/services/core"
WEB_DIR="$ROOT/web"
VENV_PY="$CORE_DIR/.venv/bin/python"
VENV_PIP="$CORE_DIR/.venv/bin/pip"
UVICORN="$CORE_DIR/.venv/bin/memoryagent-core"

have_cmd() { command -v "$1" >/dev/null 2>&1; }

if [[ ! -x "$VENV_PY" ]]; then
  echo "==> Creating Python venv and installing core…"
  (cd "$CORE_DIR" && python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]")
fi

if [[ ! -f "$WEB_DIR/dist/index.html" ]]; then
  echo "==> Building web (no web/dist yet)…"
  if ! have_cmd npm; then
    echo "npm not found. Install Node.js LTS, then re-run: $0" >&2
    exit 1
  fi
  (cd "$WEB_DIR" && npm ci && npm run build)
fi

echo "==> Starting MemoryAgent (data: $MEMORYAGENT_DATA_DIR)"
echo "    UI: http://127.0.0.1:8765/  (copy bearer token from log below)"
exec "$UVICORN"
