"""Contract tests for the domain packs and the add-on loader."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = ROOT / "pro" / "domain"
ADDON = ROOT / "pro" / "blender_mcp.py"

EXPECTED = {
    "terrain": {"create_terrain", "sculpt_terrain_region", "scatter_objects", "create_rock"},
    "vegetation": {"create_tree", "create_bush", "create_grass_patch", "create_flower_patch"},
    "water": {"create_water_plane", "create_river", "create_pond", "create_water_material"},
    "materials_uv": {"create_procedural_material", "smart_uv_unwrap", "pack_uv_islands", "list_materials"},
    "lighting": {"create_light", "create_camera", "setup_world_background", "render_still"},
    "physics": {"add_rigid_body", "add_collision", "add_cloth", "bake_simulation"},
}


def _functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_every_domain_module_exposes_its_contract() -> None:
    for module, expected in EXPECTED.items():
        path = DOMAIN / f"{module}.py"
        assert path.is_file(), f"missing domain module {path}"
        assert expected <= _functions(path), f"{module} is missing functions"


def test_domain_packs_have_no_placeholders() -> None:
    for path in DOMAIN.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "TODO" not in text, f"TODO left in {path}"
        assert "NotImplementedError" not in text, f"stub left in {path}"
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in EXPECTED.get(path.stem, set()):
                body = [item for item in node.body if not isinstance(item, ast.Expr)]
                assert body, f"empty public function {node.name} in {path}"


def test_addon_loads_domain_packs() -> None:
    text = ADDON.read_text(encoding="utf-8")
    assert "def _load_domain_pack" in text
    assert "DOMAIN = _load_domain_pack()" in text
    assert "def _domain_call" in text
    for _module, functions in EXPECTED.items():
        for function in functions:
            assert f'"{function}": lambda p: self.{function}(**p)' in text, (
                f"{function} is not dispatched"
            )
