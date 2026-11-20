#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BLENDER_BIN="${BLENDER_BIN:-blender}"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
PKG_DIR="$BUILD_DIR/blender_mcp_pro"

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR"
cp "$ROOT/pro/blender_mcp.py" "$PKG_DIR/blender_mcp.py"
mkdir -p "$PKG_DIR/domain"
cp "$ROOT"/pro/domain/*.py "$PKG_DIR/domain/"
cp "$ROOT/pro/extension/blender_manifest.toml" "$PKG_DIR/blender_manifest.toml"
cat > "$PKG_DIR/__init__.py" <<'PY'
"""Blender MCP Pro extension entry point."""
from .blender_mcp import bl_info, register, unregister

__all__ = ["bl_info", "register", "unregister"]
PY

"$BLENDER_BIN" --factory-startup --command extension build \
    --source-dir "$PKG_DIR" \
    --output-dir "$BUILD_DIR"

archive="$(python3 - "$PKG_DIR/blender_manifest.toml" <<'PYZIP'
import sys
import tomllib
with open(sys.argv[1], "rb") as source:
    manifest = tomllib.load(source)
print(f"{manifest['id']}-{manifest['version']}.zip")
PYZIP
)"
python3 "$ROOT/scripts/normalize_extension.py" "$BUILD_DIR/$archive"
echo "Built extension in $BUILD_DIR"
