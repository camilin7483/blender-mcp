#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BLENDER_BIN="${BLENDER_BIN:-blender}"
BLENDER_52_BIN="${BLENDER_52_BIN:-}"
VERSION="4.9.0"
OUT="$ROOT/bench/results/release-gate"
LOGS="$OUT/logs"
mkdir -p "$LOGS"

cd "$ROOT"

echo "== host tests =="
python3 -m pytest tests/contracts tests/unit tests/integration -q | tee "$LOGS/pytest.log"

echo "== lint =="
uvx ruff check tests scripts bench src | tee "$LOGS/ruff.log"

echo "== Blender 4.5 =="
BLENDER_BIN="$BLENDER_BIN" ./scripts/run_blender_tests.sh | tee "$LOGS/blender-4.5.log"

if [ -n "$BLENDER_52_BIN" ]; then
    echo "== Blender 5.2 =="
    BLENDER_BIN="$BLENDER_52_BIN" ./scripts/run_blender_tests.sh | tee "$LOGS/blender-5.2.log"
else
    echo "Blender 5.2 skipped: BLENDER_52_BIN is empty" | tee "$LOGS/blender-5.2.log"
fi

echo "== benchmark (3 runs) =="
BLENDER_BIN="$BLENDER_BIN" ./scripts/run_bench.sh \
    --runs 3 --output "$OUT/bench" | tee "$LOGS/bench.log"

echo "== extension =="
BLENDER_BIN="$BLENDER_BIN" ./scripts/build_extension.sh | tee "$LOGS/extension-build.log"
"$BLENDER_BIN" --factory-startup --command extension validate \
    "build/blender_mcp_pro-$VERSION.zip" | tee "$LOGS/extension-validate.log"

if [ -n "$BLENDER_52_BIN" ]; then
    BLENDER_BIN="$BLENDER_52_BIN" ./scripts/build_extension.sh | tee "$LOGS/extension-build-5.2.log"
    "$BLENDER_52_BIN" --factory-startup --command extension validate \
        "build/blender_mcp_pro-$VERSION.zip" | tee "$LOGS/extension-validate-5.2.log"
fi

sha256sum "build/blender_mcp_pro-$VERSION.zip" > "$OUT/SHA256SUMS"
python3 scripts/generate_sbom.py > "$OUT/sbom.json"

python3 - "$OUT" <<'PY'
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
bench = json.loads((out / "bench" / "summary.json").read_text())
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
report = {
    "release": "4.9.0-alpha.1",
    "commit": commit,
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "host_tests": "pass",
    "blender_4_5": "pass",
    "blender_5_2": "pass" if (out / "logs" / "blender-5.2.log").read_text().find("PASSED") >= 0 else "not_run",
    "bench": {
        "passed_tasks": bench["passed_tasks"],
        "total_tasks": bench["total_tasks"],
        "runs": bench["runs"],
    },
    "extension_sha256": (out / "SHA256SUMS").read_text().split()[0],
    "external_blockers": [
        "GitHub Actions not executed: gh token invalid in this environment",
        "Windows/macOS Blender headless not validated on those OSes",
        "External benchmark comparison against another server not performed",
    ],
}
(out / "gate.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
PY

echo "Release gate evidence: $OUT/gate.json"
