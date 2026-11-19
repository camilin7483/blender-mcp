"""Headless Blender baseline: import the add-on and verify evaluated geometry.

Run with:
    blender -b --factory-startup --python tests/blender/import_headless.py

This test does not exercise bpy.app.timers. The socket round-trip lives in
smoke_gui.py because --background never pumps the event loop.
"""

from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "pro"))

import bmesh  # noqa: E402
import bpy  # noqa: E402


def fail(message: str) -> None:
    print(f"BLENDER_HEADLESS_TEST_FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    try:
        import blender_mcp as bm  # noqa: F401

        if tuple(bm.bl_info.get("version", ())) != (3, 0, 0):
            fail(f"unexpected add-on version: {bm.bl_info.get('version')}")

        if not hasattr(bm, "BlenderMCPServer"):
            fail("BlenderMCPServer is missing")

        for obj in list(bpy.context.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)

        mesh = bpy.data.meshes.new("BaselineCube")
        bm_mesh = bmesh.new()
        bmesh.ops.create_cube(bm_mesh, size=2.0)
        bm_mesh.to_mesh(mesh)
        bm_mesh.free()
        obj = bpy.data.objects.new("BaselineCube", mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.update()

        server = bm.BlenderMCPServer(port=0)
        before = server._get_aabb(obj)
        modifier = obj.modifiers.new("SolidifyOut", "SOLIDIFY")
        modifier.thickness = 0.5
        modifier.offset = 1.0
        bpy.context.view_layer.update()
        after = server._get_aabb(obj)

        if before == after:
            fail("evaluated AABB did not change after an outward modifier")
        if abs(after[0][0] - (-1.28868)) > 1e-3:
            fail(f"unexpected evaluated AABB: {after}")

        scene = server.get_scene_info()
        if scene.get("object_count") != 1:
            fail(f"unexpected scene object count: {scene.get('object_count')}")

    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        fail("exception during headless baseline")

    print("BLENDER_HEADLESS_TEST_OK")


if __name__ == "__main__":
    main()
