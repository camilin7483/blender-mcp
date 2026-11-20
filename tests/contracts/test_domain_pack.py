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
    "architecture_shell": {"create_room_shell", "create_door", "create_window"},
    "architecture_furniture": {
        "create_table", "create_chair", "create_shelf", "create_bed",
        "create_sofa", "create_kitchen_block",
    },
    "hardsurface_modifiers": {
        "add_bevel_modifier", "add_solidify_modifier", "add_array_modifier",
        "add_mirror_modifier", "apply_all_modifiers",
    },
    "hardsurface_primitives": {"create_text_object", "create_curve_tube", "create_metaball", "convert_to_mesh"},
    "environment": {
        "create_sky_lighting", "create_fog_volume", "create_cloud_layer",
        "create_ground", "create_cliff", "create_beach",
        "create_biome_scatter", "create_water_shore",
    },
    "character": {
        "create_humanoid_blockout", "create_eye_pair", "create_teeth_set",
        "create_hair_cap", "create_garment", "create_face_landmarks",
        "create_hand_blockout", "create_foot_blockout",
    },
    "materials_pbr": {
        "create_metal_material", "create_wood_material", "create_fabric_material",
        "create_glass_material", "create_skin_material", "create_concrete_material",
        "create_emission_material", "assign_material_to_faces",
    },
    "animation": {
        "set_frame_range", "keyframe_path", "create_turntable_animation",
        "create_camera_rig", "add_follow_path_constraint",
        "set_keyframe_interpolation", "create_action", "clear_animation",
    },
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
