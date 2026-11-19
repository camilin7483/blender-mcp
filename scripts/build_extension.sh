#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BLENDER_BIN="${BLENDER_BIN:-blender}"
BUILD_DIR="$ROOT/build"
PKG_DIR="$BUILD_DIR/blender_mcp_pro"

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR"
cp "$ROOT/pro/blender_mcp.py" "$PKG_DIR/blender_mcp.py"
cp "$ROOT/pro/extension/blender_manifest.toml" "$PKG_DIR/blender_manifest.toml"
cat > "$PKG_DIR/__init__.py" <<'PY'
"""Blender MCP Pro extension entry point."""
from .blender_mcp import bl_info, register, unregister

__all__ = ["bl_info", "register", "unregister"]
PY

"$BLENDER_BIN" --factory-startup --command extension build \
    --source-dir "$PKG_DIR" \
    --output-dir "$BUILD_DIR"

echo "Built extension in $BUILD_DIR"
