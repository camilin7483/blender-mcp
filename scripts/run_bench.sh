#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BLENDER_BIN="${BLENDER_BIN:-blender}"

exec "$BLENDER_BIN" -b --factory-startup --python-exit-code 1 \
    --python "$ROOT/bench/runner.py" -- "$@"
