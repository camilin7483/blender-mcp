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


def make_cube(name: str, size: float = 1.0):
    mesh = bpy.data.meshes.new(name)
    bm_mesh = bmesh.new()
    bmesh.ops.create_cube(bm_mesh, size=size)
    bm_mesh.to_mesh(mesh)
    bm_mesh.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def main() -> None:
    try:
        import blender_mcp as bm  # noqa: F401

        if tuple(bm.bl_info.get("version", ())) != (3, 0, 0):
            fail(f"unexpected add-on version: {bm.bl_info.get('version')}")

        if not hasattr(bm, "BlenderMCPServer"):
            fail("BlenderMCPServer is missing")

        background_server = bm.BlenderMCPServer(port=0)
        if background_server.start():
            fail("server started in Blender background mode; timers cannot run")

        if background_server._execute_code_allowed():
            fail("execute_code is enabled by default")
        try:
            background_server.execute_code("raise RuntimeError('must not run')", auto_audit=False)
        except PermissionError:
            pass
        else:
            fail("execute_code did not refuse the default policy")

        os.environ["BLENDER_MCP_ALLOW_EXECUTE_CODE"] = "1"
        try:
            result = background_server.execute_code("x = 1", auto_audit=False)
            if not result.get("success"):
                fail(f"execute_code failed with explicit opt-in: {result}")
        finally:
            os.environ.pop("BLENDER_MCP_ALLOW_EXECUTE_CODE", None)
        if background_server._execute_code_allowed():
            fail("execute_code stayed enabled after removing the env opt-in")

        for obj in list(bpy.context.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)

        obj = make_cube("BaselineCube", 2.0)
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

        dry = server.clear_scene(confirm=False)
        if not dry.get("dry_run") or bpy.data.objects.get("BaselineCube") is None:
            fail("clear_scene did not dry-run")
        dry = server.delete_object("BaselineCube", confirm=False)
        if not dry.get("dry_run") or bpy.data.objects.get("BaselineCube") is None:
            fail("delete_object did not dry-run")
        dry = server.setup_studio_lighting(confirm=False)
        if not dry.get("dry_run"):
            fail("setup_studio_lighting did not dry-run")

        server.create_checkpoint("dryrun")
        dry = server.rollback_checkpoint("dryrun", confirm=False)
        if not dry.get("dry_run"):
            fail("rollback_checkpoint did not dry-run")

        os.environ["BLENDER_MCP_ALLOW_UNSAFE_OPS"] = "1"
        try:
            deleted = server.delete_object("BaselineCube")
            if not deleted.get("success") or bpy.data.objects.get("BaselineCube") is not None:
                fail("unsafe-ops bypass did not delete the object")
        finally:
            os.environ.pop("BLENDER_MCP_ALLOW_UNSAFE_OPS", None)

        make_cube("ClearMe", 1.0)
        cleared = server.clear_scene(confirm=True)
        if not cleared.get("success") or bpy.data.objects.get("ClearMe") is not None:
            fail("confirmed clear_scene did not remove the object")

        lights = server.setup_studio_lighting(confirm=True)
        if not lights.get("success") or len(lights.get("lights", [])) != 3:
            fail(f"setup_studio_lighting failed with confirm=true: {lights}")

    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        fail("exception during headless baseline")

    print("BLENDER_HEADLESS_TEST_OK")


if __name__ == "__main__":
    main()
