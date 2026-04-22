#!/usr/bin/env bash
# One-shot developer setup for MemoryAgent on macOS.
# Idempotent: safe to run again after partial success.
#
# See: docs/spec/prerequisites.md
#
# Usage:
#   ./scripts/setup-dev.sh
#   CHAT_MODEL=llama3.2 EMBED_MODEL=nomic-embed-text ./scripts/setup-dev.sh
#
# Checks: Homebrew → `ollama` CLI (install via brew if missing) → Ollama HTTP API
#         at http://127.0.0.1:11434 → `ollama pull` for chat + embedding models.
#         Align CHAT_MODEL / EMBED_MODEL with services/core `AppConfig` defaults.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CHAT_MODEL="${CHAT_MODEL:-llama3.2}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"

echo "==> MemoryAgent setup-dev (${ROOT})"
echo "    CHAT_MODEL=${CHAT_MODEL}"
echo "    EMBED_MODEL=${EMBED_MODEL}"
echo ""

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script targets macOS. On other systems, install equivalents manually (see docs/spec/prerequisites.md)." >&2
  exit 1
fi

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# --- Homebrew (recommended path for Ollama on dev machines) ---
if ! have_cmd brew; then
  echo "Homebrew not found. Install from https://brew.sh then re-run:"
  echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
  echo ""
  echo "Or install Ollama manually from https://ollama.com and re-run this script."
  exit 1
fi

# --- Ollama ---
if ! have_cmd ollama; then
  echo "==> Installing Ollama via Homebrew..."
  brew install ollama
else
  echo "==> Ollama already present: $(command -v ollama)"
fi

# Ensure the daemon can serve (user may need to start the app once from /Applications)
if ! curl -fsS "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  echo ""
  echo "Ollama API not reachable at http://127.0.0.1:11434."
  echo "Start Ollama (menu bar app or: ollama serve) and re-run this script to pull models."
  echo ""
  NEEDS_PULL=0
else
  NEEDS_PULL=1
fi

if [[ "${NEEDS_PULL:-0}" -eq 1 ]]; then
  echo "==> Pulling chat model: ${CHAT_MODEL}"
  ollama pull "${CHAT_MODEL}"
  echo "==> Pulling embedding model: ${EMBED_MODEL}"
  ollama pull "${EMBED_MODEL}"
else
  echo "==> Skipping model pull (Ollama not running). After starting Ollama, run:"
  echo "    ollama pull ${CHAT_MODEL}"
  echo "    ollama pull ${EMBED_MODEL}"
fi

echo ""
if curl -fsS "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  echo "==> Installed Ollama models (ollama list):"
  ollama list
else
  echo "==> Ollama API not up — run \`ollama list\` after starting the Ollama app."
fi

echo ""
echo "==> Done (Ollama path)."
echo "    When the MemoryAgent core service exists: start it from the repo README, then open the local web UI."
echo "    Native Swift bridge / Python venv: add steps to this script or scripts/setup-dev-extra.sh as the stack lands."
