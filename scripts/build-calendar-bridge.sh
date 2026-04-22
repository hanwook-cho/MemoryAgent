#!/usr/bin/env bash
# Build the EventKit calendar helper (macOS only).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/native-bridge/macos-calendar"
swift build -c release
echo "Built: $ROOT/native-bridge/macos-calendar/.build/*/release/memoryagent-calendar"
