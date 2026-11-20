#!/bin/bash
# Syncs pro/blender_mcp.py into Blender's installed add-on copies.
# Blender loads the installed copy, NOT the repository file: run this after
# every edit, then toggle the add-on off/on (or restart Blender).
#
# Override the destination with BLENDER_ADDONS_DIR when using another
# Blender version or a portable build.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/blender_mcp.py"
ADDONS_DIR="${BLENDER_ADDONS_DIR:-$HOME/.config/blender/4.5/scripts/addons}"

python3 -m py_compile "$SRC"
python3 -c "import sys; d=open('$SRC','rb').read(); sys.exit(1 if d.count(b'\x00') else 0)" \
  || { echo "ABORT: null bytes in $SRC"; exit 1; }

mkdir -p "$ADDONS_DIR"
for name in blender_mcp_pro.py blender_mcp.py; do
  dst="$ADDONS_DIR/$name"
  if [ -f "$dst" ]; then cp "$dst" "$dst.bak"; fi
  cp "$SRC" "$dst"
  rm -rf "$ADDONS_DIR/domain"
  cp -R "$SCRIPT_DIR/domain" "$ADDONS_DIR/domain"
  echo "synced: $dst (+ domain/)"
done
echo "DONE. Toggle the add-on off/on in Blender (or restart it)."
