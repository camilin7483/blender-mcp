#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BLENDER_BIN="${BLENDER_BIN:-blender}"
BLENDER_52_BIN="${BLENDER_52_BIN:-}"
OUT="${RELEASE_GATE_OUT:-$ROOT/bench/results/release-gate}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
LOGS="$OUT/logs"
mkdir -p "$LOGS"

cd "$ROOT"
rm -f "$OUT/gate.json" "$OUT/SHA256SUMS" "$OUT/sbom.json"
version_45="$("$BLENDER_BIN" --version | sed -n '1p')"
[[ "$version_45" == "Blender 4.5."* ]] || { echo "Expected Blender 4.5: $version_45" >&2; exit 1; }
if [[ -n "$BLENDER_52_BIN" ]]; then
    version_52="$("$BLENDER_52_BIN" --version | sed -n '1p')"
    [[ "$version_52" == "Blender 5.2."* ]] || { echo "Expected Blender 5.2: $version_52" >&2; exit 1; }
else
    version_52=""
fi

python3 -m pytest tests/contracts tests/unit tests/integration -q | tee "$LOGS/pytest.log"
uvx ruff@0.17.6 check tests scripts bench src | tee "$LOGS/ruff.log"

run_blender_gate() {
    local binary="$1" series="$2"
    BLENDER_BIN="$binary" ./scripts/run_blender_tests.sh 2>&1 | tee "$LOGS/blender-$series.log"
    BLENDER_BIN="$binary" ./scripts/run_bench.sh --runs 3 --output "$OUT/bench-$series" 2>&1 | tee "$LOGS/bench-$series.log"
    BUILD_DIR="$OUT/extension-$series" BLENDER_BIN="$binary" ./scripts/build_extension.sh |
        tee "$LOGS/extension-build-$series.log"
    local archive
    local -a archives=("$OUT/extension-$series"/blender_mcp_pro-*.zip)
    [[ ${#archives[@]} -eq 1 && -f "${archives[0]}" ]]
    archive="${archives[0]}"
    "$binary" --factory-startup --command extension validate "$archive" | tee "$LOGS/extension-validate-$series.log"
    sha256sum "$archive" >> "$OUT/SHA256SUMS"
}

run_blender_gate "$BLENDER_BIN" "4.5"
if [[ -n "$version_52" ]]; then
    run_blender_gate "$BLENDER_52_BIN" "5.2"
    cmp "$OUT"/extension-4.5/blender_mcp_pro-*.zip "$OUT"/extension-5.2/blender_mcp_pro-*.zip
else
    echo "Blender 5.2 skipped: BLENDER_52_BIN is empty" | tee "$LOGS/blender-5.2.log"
fi

python3 scripts/generate_sbom.py > "$OUT/sbom.json"
python3 - "$OUT" "$version_45" "$version_52" <<'PY'
import json
import subprocess
import sys
import tomllib
from pathlib import Path

out = Path(sys.argv[1])
report = {
    "release": tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"],
    "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "dirty": bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], text=True)),
    "status": "pass" if sys.argv[3] else "partial",
    "host_tests": "pass",
    "blender": {},
    "extension_sha256": (out / "SHA256SUMS").read_text().split()[0],
    "external_validation": "GitHub Actions, Windows/macOS and third-party comparison are outside this local gate.",
}
for series, version in zip(("4.5", "5.2"), sys.argv[2:], strict=True):
    if not version:
        report["blender"][series] = {"status": "not_run"}
        continue
    summary = json.loads((out / f"bench-{series}" / "summary.json").read_text())
    if not (
        summary["runs"] == 3 and summary["passed_tasks"] == summary["total_tasks"] > 0
        and summary["total_tasks"] == sum((p / "task.json").is_file() for p in Path("bench/tasks").iterdir())
    ):
        raise SystemExit(f"Incomplete benchmark on Blender {series}")
    report["blender"][series] = {
        "status": "pass",
        "version": version,
        "bench": {key: summary[key] for key in ("passed_tasks", "total_tasks", "runs")},
    }
(out / "gate.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
PY
