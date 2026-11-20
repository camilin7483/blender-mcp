"""Reopen the documented scenes and check the saved geometry and pilot pose rig."""

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "showcase"
sys.path.insert(0, str(ROOT / "scripts"))

from render_pilot_showcase import RIG_NAME, verify_rig  # noqa: E402
from render_showcase import GeometryService  # noqa: E402


def check_scene(stem):
    report = json.loads((ASSETS / f"{stem}.json").read_text(encoding="utf-8"))
    scene_path = ASSETS / f"{stem}.blend"
    assert "FINISHED" in bpy.ops.wm.open_mainfile(filepath=str(scene_path), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    assert scene.camera and scene.camera.name.startswith("Hero")
    assert len(scene.objects) == report["objects"]
    assert sum(obj.type == "MESH" for obj in scene.objects) == report["meshes"]

    for name in report["evaluated_topology"]:
        metrics = GeometryService.topology_metrics(scene.objects[name])
        assert metrics["non_manifold_edges"] == 0 and metrics["disconnected_components"] == 1, (name, metrics)

    if stem == "nereid-07":
        rig = scene.objects[RIG_NAME]
        assert rig.type == "ARMATURE" and len(rig.data.bones) == report["bones"] == 35
        assert sum(obj.parent == rig and obj.parent_type == "BONE" for obj in scene.objects) == report[
            "bone_parented_parts"
        ]
        print(f"NEREID_REOPEN_POSE_OK: {verify_rig(rig)}")

    print(f"SHOWCASE_REOPEN_OK: {stem} ({len(scene.objects)} objects)")


if __name__ == "__main__":
    for model in ("pelagos-07", "nereid-07"):
        check_scene(model)
