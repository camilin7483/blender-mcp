"""Headless Blender baseline: import the add-on and verify evaluated geometry.

Run with:
    blender -b --factory-startup --python tests/blender/import_headless.py

This test does not exercise bpy.app.timers. The socket round-trip lives in
smoke_gui.py because --background never pumps the event loop.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
import zipfile

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


def make_ring(name: str, outer: float = 2.0, inner: float = 1.0, height: float = 0.2):
    mesh = bpy.data.meshes.new(name)
    bm_mesh = bmesh.new()
    half_outer, half_inner = outer / 2.0, inner / 2.0
    corners = [
        (-half_outer, -half_outer),
        (half_outer, -half_outer),
        (half_outer, half_outer),
        (-half_outer, half_outer),
    ]
    inner_corners = [
        (-half_inner, -half_inner),
        (half_inner, -half_inner),
        (half_inner, half_inner),
        (-half_inner, half_inner),
    ]
    outer_bottom, inner_bottom, outer_top, inner_top = [], [], [], []
    for x, y in corners:
        outer_bottom.append(bm_mesh.verts.new((x, y, 0.0)))
        outer_top.append(bm_mesh.verts.new((x, y, height)))
    for x, y in inner_corners:
        inner_bottom.append(bm_mesh.verts.new((x, y, 0.0)))
        inner_top.append(bm_mesh.verts.new((x, y, height)))
    for index in range(4):
        nxt = (index + 1) % 4
        bm_mesh.faces.new([outer_bottom[index], outer_bottom[nxt], outer_top[nxt], outer_top[index]])
        bm_mesh.faces.new([inner_bottom[nxt], inner_bottom[index], inner_top[index], inner_top[nxt]])
        bm_mesh.faces.new([outer_bottom[nxt], outer_bottom[index], inner_bottom[index], inner_bottom[nxt]])
        bm_mesh.faces.new([outer_top[index], outer_top[nxt], inner_top[nxt], inner_top[index]])
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

        for bad_url in (
            "http://api.polyhaven.com/assets",
            "https://evil.example.com/model.glb",
            "https://localhost/model.glb",
            "https://127.0.0.1/model.glb",
        ):
            try:
                bm.validate_download_url(bad_url, resolve=False)
            except ValueError:
                pass
            else:
                fail(f"validate_download_url accepted {bad_url}")

        if bm.validate_download_url("https://api.polyhaven.com/assets", resolve=False) != "https://api.polyhaven.com/assets":
            fail("validate_download_url rejected a provider URL")
        if not bm._is_private_ip("127.0.0.1") or not bm._is_private_ip("10.0.0.1"):
            fail("_is_private_ip missed a private address")
        if bm._is_private_ip("8.8.8.8"):
            fail("_is_private_ip rejected a public address")
        if "/" in bm.sanitize_asset_id("../../etc/passwd"):
            fail("sanitize_asset_id kept a path separator")
        try:
            bm.sanitize_asset_id("")
        except ValueError:
            pass
        else:
            fail("sanitize_asset_id accepted an empty value")

        zip_root = tempfile.mkdtemp(prefix="blendermcp_zip_")
        try:
            evil_zip = os.path.join(zip_root, "evil.zip")
            with zipfile.ZipFile(evil_zip, "w") as archive:
                archive.writestr("../evil.txt", "owned")
            try:
                bm.safe_extract_zip(evil_zip, os.path.join(zip_root, "evil-out"))
            except ValueError:
                pass
            else:
                fail("safe_extract_zip allowed zip slip")
            if os.path.exists(os.path.join(zip_root, "evil.txt")):
                fail("safe_extract_zip wrote outside the destination")

            good_zip = os.path.join(zip_root, "good.zip")
            with zipfile.ZipFile(good_zip, "w") as archive:
                archive.writestr("nested/a.txt", "ok")
            good_out = os.path.join(zip_root, "good-out")
            bm.safe_extract_zip(good_zip, good_out)
            with open(os.path.join(good_out, "nested", "a.txt"), "r", encoding="utf-8") as handle:
                if handle.read() != "ok":
                    fail("safe_extract_zip corrupted the extracted file")

            try:
                bm.safe_extract_zip(good_zip, os.path.join(zip_root, "limit-out"), max_files=0)
            except ValueError:
                pass
            else:
                fail("safe_extract_zip ignored max_files")

            try:
                bm.safe_extract_zip(good_zip, os.path.join(zip_root, "bytes-out"), max_bytes=1)
            except ValueError:
                pass
            else:
                fail("safe_extract_zip ignored max_bytes")
        finally:
            shutil.rmtree(zip_root, ignore_errors=True)

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

        export_dir = tempfile.mkdtemp(prefix="blendermcp_export_")
        os.environ["BLENDER_MCP_OUTPUT_DIR"] = export_dir
        try:
            make_cube("ExportMe", 1.0)
            exported = server.export_scene("cube.glb", "GLB")
            if not exported.get("success") or not os.path.exists(os.path.join(export_dir, "cube.glb")):
                fail(f"GLB export failed: {exported}")

            server.export_scene("nested/cube.glb", "GLB")
            if not os.path.exists(os.path.join(export_dir, "nested", "cube.glb")):
                fail("nested GLB export did not create the directory")

            server.export_scene("noext", "GLB")
            if not os.path.exists(os.path.join(export_dir, "noext.glb")):
                fail("export did not append the expected extension")

            try:
                server.export_scene("../escape.glb", "GLB")
            except PermissionError:
                pass
            else:
                fail("export_scene allowed path traversal")

            try:
                server.export_scene(os.path.join(tempfile.gettempdir(), "outside.glb"), "GLB")
            except PermissionError:
                pass
            else:
                fail("export_scene allowed an absolute path outside the sandbox")

            try:
                server.export_scene("cube.xyz", "XYZ")
            except ValueError:
                pass
            else:
                fail("export_scene accepted an invalid format")
        finally:
            os.environ.pop("BLENDER_MCP_OUTPUT_DIR", None)
            shutil.rmtree(export_dir, ignore_errors=True)

        any_dir = tempfile.mkdtemp(prefix="blendermcp_any_")
        os.environ["BLENDER_MCP_ALLOW_ANY_PATH"] = "1"
        try:
            any_path = os.path.join(any_dir, "any.glb")
            server.export_scene(any_path, "GLB")
            if not os.path.exists(any_path):
                fail("BLENDER_MCP_ALLOW_ANY_PATH=1 did not allow the export")
        finally:
            os.environ.pop("BLENDER_MCP_ALLOW_ANY_PATH", None)
            shutil.rmtree(any_dir, ignore_errors=True)

        # --- evaluated geometry engine ---
        for item in list(bpy.context.scene.objects):
            bpy.data.objects.remove(item, do_unlink=True)

        geo_a = make_cube("GeoA", 1.0)
        geo_a.location = (0.0, 0.0, 0.5)
        geo_b = make_cube("GeoB", 1.0)
        geo_b.location = (0.0, 0.0, 1.5)
        bpy.context.view_layer.update()

        snapshot = bm.GeometryService.snapshot(geo_a)
        if snapshot.world_aabb != [[-0.5, -0.5, 0.0], [0.5, 0.5, 1.0]]:
            fail(f"unexpected snapshot AABB: {snapshot.world_aabb}")

        graph = bm.GeometryService.contact_graph([geo_a, geo_b], tolerance=0.001)
        pair = graph["pairs"][0]
        if not pair["surface_intersection"] or pair["min_distance"] != 0.0:
            fail(f"stacked cubes were not detected as surface contact: {pair}")

        for item in list(bpy.context.scene.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        ring = make_ring("Ring")
        hole_cube = make_cube("HoleCube", 0.6)
        hole_cube.location = (0.0, 0.0, 0.3)
        bpy.context.view_layer.update()
        graph = bm.GeometryService.contact_graph([ring, hole_cube], tolerance=0.001)
        pair = graph["pairs"][0]
        if pair["surface_intersection"] or pair["contact"] or pair["min_distance"] < 0.1:
            fail(f"AABB-only overlap leaked into the contact graph: {pair}")

        hole_cube.location.x = 0.85
        bpy.context.view_layer.update()
        graph = bm.GeometryService.contact_graph([ring, hole_cube], tolerance=0.001)
        pair = graph["pairs"][0]
        if not pair["surface_intersection"]:
            fail(f"true interpenetration was not detected: {pair}")

        for item in list(bpy.context.scene.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        left = make_cube("Left", 1.0)
        left.location = (-1.0, 0.0, 0.5)
        right = make_cube("Right", 1.0)
        right.location = (1.0, 0.0, 0.5)
        bpy.context.view_layer.update()
        symmetry = bm.GeometryService.symmetry_error([left, right], axis="X", tolerance=0.001)
        if not symmetry["passed"] or symmetry["max_error"] > 0.001:
            fail(f"symmetric pair failed symmetry: {symmetry}")

        bpy.data.objects.remove(right, do_unlink=True)
        bpy.context.view_layer.update()
        symmetry = bm.GeometryService.symmetry_error([left], axis="X", tolerance=0.001)
        if symmetry["passed"]:
            fail(f"asymmetric pair passed symmetry: {symmetry}")

        ground = bm.GeometryService.ground_contact(
            [bm.GeometryService.snapshot(left)], tolerance=0.005
        )
        if not ground["passed"]:
            fail(f"grounded cube failed ground contact: {ground}")
        left.location.z = 0.6
        bpy.context.view_layer.update()
        ground = bm.GeometryService.ground_contact(
            [bm.GeometryService.snapshot(left)], tolerance=0.005
        )
        if ground["passed"]:
            fail(f"floating cube passed ground contact: {ground}")

        topology = bm.GeometryService.topology_metrics(left)
        if topology["non_manifold_edges"] != 0 or topology["disconnected_components"] != 1:
            fail(f"unexpected cube topology: {topology}")

        loose_mesh = bpy.data.meshes.new("Loose")
        loose_bm = bmesh.new()
        bmesh.ops.create_cube(loose_bm, size=1.0)
        loose_bm.verts.new((5.0, 5.0, 5.0))
        loose_bm.to_mesh(loose_mesh)
        loose_bm.free()
        loose = bpy.data.objects.new("Loose", loose_mesh)
        bpy.context.collection.objects.link(loose)
        bpy.context.view_layer.update()
        topology = bm.GeometryService.topology_metrics(loose)
        if topology["loose_vertices"] != 1 or topology["disconnected_components"] != 2:
            fail(f"loose vertex metrics failed: {topology}")

        # --- audit contract and regressions ---
        def clear_scene() -> None:
            for item in list(bpy.context.scene.objects):
                bpy.data.objects.remove(item, do_unlink=True)

        clear_scene()
        blueprint_cube = make_cube("BlueprintCube", 1.0)
        blueprint_cube.location = (0.0, 0.0, 0.5)
        bpy.context.view_layer.update()
        audit = server.audit_3d_model(
            object_names=["BlueprintCube"], blueprint_name="table"
        )
        if audit["passed"]:
            fail("audit passed a table blueprint mismatch")
        if not any(failure["rule"] == "blueprint_dimensions" for failure in audit["failures"]):
            fail("audit did not report a structured blueprint failure")
        for key in ("requirements", "dimensions", "topology", "contacts", "collisions", "failures"):
            if key not in audit:
                fail(f"audit contract is missing '{key}'")

        clear_scene()
        ring = make_ring("AuditRing")
        hole = make_cube("AuditHole", 0.6)
        hole.location = (0.0, 0.0, 0.3)
        bpy.context.view_layer.update()
        audit = server.audit_3d_model(object_names=["AuditRing", "AuditHole"])
        if not audit["passed"] or audit["collisions"]:
            fail(f"audit false-positive on ring-in-hole: {audit['failures']}")

        hole.location.x = 0.85
        bpy.context.view_layer.update()
        audit = server.audit_3d_model(object_names=["AuditRing", "AuditHole"])
        if audit["passed"] or not audit["collisions"]:
            fail("audit missed a true interpenetration")

        clear_scene()
        gn_mesh = bpy.data.meshes.new("GNBase")
        gn_obj = bpy.data.objects.new("GNOnly", gn_mesh)
        bpy.context.collection.objects.link(gn_obj)
        node_group = bpy.data.node_groups.new("GNAudit", "GeometryNodeTree")
        node_group.interface.new_socket(
            name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
        )
        output_node = node_group.nodes.new("NodeGroupOutput")
        cube_node = node_group.nodes.new("GeometryNodeMeshCube")
        node_group.links.new(cube_node.outputs["Mesh"], output_node.inputs["Geometry"])
        gn_modifier = gn_obj.modifiers.new("GN", "NODES")
        gn_modifier.node_group = node_group
        bpy.context.view_layer.update()
        audit = server.audit_3d_model(object_names=["GNOnly"])
        if audit["object_count_audited"] != 1:
            fail("audit skipped a Geometry Nodes-only object")
        if "GNOnly" not in audit["dimensions"]["objects"]:
            fail("audit did not measure a Geometry Nodes-only object")

        clear_scene()
        sym_left = make_cube("SymL", 1.0)
        sym_left.location = (-1.0, 0.0, 0.5)
        sym_right = make_cube("SymR", 1.0)
        sym_right.location = (1.0, 0.0, 0.5)
        bpy.context.view_layer.update()
        audit = server.audit_3d_model(
            object_names=["SymL", "SymR"], symmetry_axis="X"
        )
        if not audit["passed"] or not audit["symmetry"]["passed"]:
            fail(f"symmetric audit failed: {audit['failures']}")

        bpy.data.objects.remove(sym_right, do_unlink=True)
        bpy.context.view_layer.update()
        audit = server.audit_3d_model(object_names=["SymL"], symmetry_axis="X")
        if audit["passed"] or audit["requirements"]["symmetry"]["passed"]:
            fail("asymmetric audit passed the symmetry requirement")

        clear_scene()
        strict_mesh = bpy.data.meshes.new("StrictLoose")
        strict_bm = bmesh.new()
        bmesh.ops.create_cube(strict_bm, size=1.0)
        strict_bm.verts.new((5.0, 5.0, 5.0))
        strict_bm.to_mesh(strict_mesh)
        strict_bm.free()
        strict_obj = bpy.data.objects.new("StrictLoose", strict_mesh)
        bpy.context.collection.objects.link(strict_obj)
        strict_obj.location = (0.0, 0.0, 0.5)
        bpy.context.view_layer.update()
        audit = server.audit_3d_model(
            object_names=["StrictLoose"], topology_policy="strict"
        )
        if audit["passed"] or not any(
            failure["rule"] == "loose_vertices" for failure in audit["failures"]
        ):
            fail(f"strict topology did not fail a loose vertex: {audit['failures']}")
        audit = server.audit_3d_model(
            object_names=["StrictLoose"], topology_policy="report"
        )
        if not audit["requirements"]["topology"]["passed"]:
            fail("report topology policy did not pass")

    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        fail("exception during headless baseline")

    print("BLENDER_HEADLESS_TEST_OK")


if __name__ == "__main__":
    main()
