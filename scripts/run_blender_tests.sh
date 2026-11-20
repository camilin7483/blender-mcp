#!/usr/bin/env bash
# Runs the real-Blender baseline tests.
#
# BLENDER_BIN   Path to a Blender 4.5 LTS executable.
#               If unset, common local locations are tried.
# DISPLAY       When unset, the GUI smoke test runs under xvfb-run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BLENDER_BIN="${BLENDER_BIN:-}"

if [[ -z "$BLENDER_BIN" ]]; then
  for candidate in \
    "$HOME/Documents/blender-4.5.4-linux-x64/blender" \
    "$HOME/Videos/blender-4.5.4-linux-x64/blender" \
    "/opt/blender/blender" \
    "/usr/bin/blender"; do
    if [[ -x "$candidate" ]]; then
      BLENDER_BIN="$candidate"
      break
    fi
  done
fi

if [[ -z "$BLENDER_BIN" ]]; then
  echo "ERROR: BLENDER_BIN is not set and no Blender 4.5 build was found." >&2
  echo "Download Blender 4.5 LTS or set BLENDER_BIN explicitly." >&2
  exit 1
fi

echo "Using Blender: $BLENDER_BIN"
"$BLENDER_BIN" --version | head -1

echo "--- headless import and evaluated geometry ---"
"$BLENDER_BIN" -b --factory-startup --python-exit-code 1 --python "$ROOT/tests/blender/import_headless.py"

echo "--- GUI socket round-trip ---"
GUI_LOG="$(mktemp)"
trap 'rm -f "$GUI_LOG"' EXIT

if [[ -z "${DISPLAY:-}" ]]; then
  if ! command -v xvfb-run >/dev/null 2>&1; then
    echo "ERROR: the GUI test needs DISPLAY or xvfb-run." >&2
    exit 1
  fi
  xvfb-run -a "$BLENDER_BIN" --factory-startup --python-exit-code 1 --python "$ROOT/tests/blender/smoke_gui.py" | tee "$GUI_LOG"
else
  "$BLENDER_BIN" --factory-startup --python-exit-code 1 --python "$ROOT/tests/blender/smoke_gui.py" | tee "$GUI_LOG"
fi

if ! grep -q "BLENDER_GUI_TEST_OK" "$GUI_LOG"; then
  echo "ERROR: GUI smoke test did not report BLENDER_GUI_TEST_OK." >&2
  exit 1
fi

echo "ALL BLENDER BASELINE TESTS PASSED"
