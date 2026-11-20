"""Extension manifest and add-on version contract.

Blender reads ``blender_manifest.toml``; ``bl_info`` is still used when the
add-on is installed as a legacy single file. Keep both versions aligned.
"""

from __future__ import annotations

import ast
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "pro" / "extension" / "blender_manifest.toml"
ADDON = ROOT / "pro" / "blender_mcp.py"


def test_manifest_is_valid_toml() -> None:
    data = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0.0"
    assert data["id"] == "blender_mcp_pro"
    assert data["version"] == "4.2.0"
    assert data["type"] == "add-on"
    assert data["blender_version_min"] == "4.5.0"
    assert data["license"] == ["SPDX:MIT"]
    assert "network" in data["permissions"]
    assert len(data["permissions"]["network"]) <= 64


def test_addon_version_matches_manifest() -> None:
    tree = ast.parse(ADDON.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "bl_info"
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        assert value["version"] == (4, 2, 0)
        assert value["blender"] == (4, 5, 0)
        return
    raise AssertionError("bl_info not found")
