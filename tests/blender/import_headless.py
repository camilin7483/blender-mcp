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
from unittest.mock import Mock, patch

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

        if tuple(bm.bl_info.get("version", ())) != (4, 9, 0):
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
        public_address = (bm.socket.AF_INET, bm.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        private_address = (bm.socket.AF_INET, bm.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        with patch.object(bm.socket, "getaddrinfo", return_value=[public_address]) as resolve:
            connection = Mock()
            with patch.object(bm.socket, "socket", return_value=connection):
                assert bm._connect_public_download(("api.polyhaven.com", 443), 5.0) is connection
            resolve.assert_called_once_with("api.polyhaven.com", 443, type=bm.socket.SOCK_STREAM)
            connection.connect.assert_called_once_with(("8.8.8.8", 443))
        fallback_address = (bm.socket.AF_INET, bm.socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))
        stalled_connection = Mock()
        stalled_connection.connect.side_effect = TimeoutError
        fallback_connection = Mock()
        with patch.object(bm.socket, "getaddrinfo", return_value=[public_address, fallback_address]):
            with patch.object(bm.socket, "socket", side_effect=[stalled_connection, fallback_connection]):
                assert bm._connect_public_download(("api.polyhaven.com", 443), 5.0) is fallback_connection
        stalled_connection.close.assert_called_once_with()
        fallback_connection.connect.assert_called_once_with(("1.1.1.1", 443))
        with patch.object(bm.socket, "getaddrinfo", return_value=[public_address, private_address]):
            with patch.object(bm.socket, "socket") as connect:
                try:
                    bm._connect_public_download(("api.polyhaven.com", 443), 5.0)
                except ValueError:
                    pass
                else:
                    fail("download accepted a non-public DNS answer")
                connect.assert_not_called()
        redirect_handler = bm._SafeRedirectHandler()
        original = bm.urllib.request.Request(
            "https://api.sketchfab.com/v3/models", headers={"Authorization": "test-token"}
        )
        redirect = redirect_handler.redirect_request(
            original, None, 302, "", {}, "https://api.polyhaven.com/assets"
        )
        assert not redirect.has_header("Authorization")
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

        # --- export profiles, validation and reimport ---
        profile_dir = tempfile.mkdtemp(prefix="blendermcp_profiles_")
        os.environ["BLENDER_MCP_OUTPUT_DIR"] = profile_dir
        try:
            for item in list(bpy.context.scene.objects):
                if item.type == "MESH":
                    bpy.data.objects.remove(item, do_unlink=True)
            profile_cube = make_cube("ProfileCube", 0.5)
            profile_cube.location = (0.0, 0.0, 0.25)
            profile_cube.data.uv_layers.new(name="UVMap")
            profile_material = bpy.data.materials.new("ProfileMaterial")
            profile_material.use_nodes = True
            profile_cube.data.materials.append(profile_material)
            bpy.context.view_layer.update()

            godot = server.export_scene("godot_cube.glb", format="GLB", profile="godot")
            if not godot.get("success") or not godot.get("reimport", {}).get("checked"):
                fail(f"godot export/reimport failed: {godot}")
            if not godot["reimport"].get("passed"):
                fail(f"godot reimport did not match dimensions: {godot['reimport']}")
            if godot.get("file_size", 0) <= 0:
                fail("godot export wrote an empty file")

            unreal = server.export_scene("unreal_cube.fbx", format="FBX", profile="unreal")
            if not unreal.get("success") or not unreal.get("reimport", {}).get("checked"):
                fail(f"unreal export/reimport failed: {unreal}")

            try:
                server.export_scene("bad.glb", format="GLB", profile="unreal")
            except ValueError:
                pass
            else:
                fail("unreal accepted a GLB format")

            profile_cube.scale = (1.0, 2.0, 1.0)
            bpy.context.view_layer.update()
            blocked = server.export_scene(
                "blocked.glb", format="GLB", profile="generic-gltf"
            )
            if blocked.get("success") or blocked["validation"]["passed"]:
                fail(f"validation did not block a non-uniform scale: {blocked}")
            forced = server.export_scene(
                "forced.glb", format="GLB", profile="generic-gltf", force=True
            )
            if not forced.get("success"):
                fail(f"force=True did not export: {forced}")
        finally:
            os.environ.pop("BLENDER_MCP_OUTPUT_DIR", None)
            shutil.rmtree(profile_dir, ignore_errors=True)

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

        # Solid containment, empty cavities and strict support.
        clear_scene()
        outer = make_cube("SolidOuter", 2)
        outer.location.z = 1
        inner = make_cube("SolidInner", 0.25)
        inner.location.z = 1
        names = [outer.name, inner.name]
        collision = server.audit_3d_model(object_names=names, topology_policy="strict")
        assert not collision["passed"] and collision["collisions"][0]["enclosed_volume_overlap"], collision
        assert not server.validate_constraints([{"type": "no_intersection", "objects": names}])["passed"]
        inside = {"type": "inside", "inner": inner.name, "outer": outer.name}
        assert server.validate_constraints([inside])["passed"]
        inner.location.z = 1.875  # Face contact with a closed convex container.
        assert server.validate_constraints([inside])["passed"]
        inner.location = (0, 0, 3)
        audit = server.audit_3d_model(object_names=names, topology_policy="strict")
        assert audit["requirements"]["ground_support"]["objects"] == [inner.name]
        assert server.audit_3d_model(object_names=names, topology_policy="report")["passed"]
        assert server.audit_3d_model(object_names=names, suspended=[inner.name], topology_policy="strict")["passed"]
        inner.location.z = 2.125
        third = make_cube("IndirectSupport", 0.25)
        third.location.z = 2.375
        assert server.audit_3d_model(object_names=[*names, third.name], topology_policy="strict")["passed"]

        clear_scene()
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 1))
        sphere = bpy.context.object
        corner = make_cube("OutsideSphere", 0.1)
        corner.location = (0.82, 0.82, 1.0)
        constraint = {"type": "inside", "inner": corner.name, "outer": sphere.name}
        assert not server.validate_constraints([constraint])["passed"]

        clear_scene()
        shell = make_cube("ClosedShell", 2)
        cavity = make_cube("CavityBoundary", 0.5)
        bpy.ops.object.select_all(action="DESELECT")
        shell.select_set(True)
        cavity.select_set(True)
        bpy.context.view_layer.objects.active = shell
        bpy.ops.object.join()
        probe = make_cube("CavityProbe", 0.1)
        assert server.validate_constraints([{"type": "no_intersection", "objects": [shell.name, probe.name]}])["passed"]
        assert not server.validate_constraints([{"type": "inside", "inner": probe.name, "outer": shell.name}])["passed"]
        probe = make_cube("EnclosesCavity", 1.0)
        assert not server.validate_constraints([{"type": "inside", "inner": probe.name, "outer": shell.name}])["passed"]

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

        # --- semantic anchors and operations ---
        clear_scene()
        anchor_target = make_cube("AnchorTarget", 1.0)
        anchor_target.location = (0.0, 0.0, 0.5)
        anchor_part = make_cube("AnchorPart", 0.2)
        anchor_part.location = (2.0, 0.0, 0.1)
        bpy.context.view_layer.update()

        anchor_data = server.list_semantic_anchors("AnchorTarget")
        anchors = {item["name"]: item for item in anchor_data["anchors"]}
        if "TOP_CENTER" not in anchors:
            fail(f"missing TOP_CENTER; keys={sorted(anchors)}")
        if anchor_data["count"] < 30:
            fail(f"too few semantic anchors: {anchor_data['count']}")
        top = anchors["TOP_CENTER"]
        if top["position"] != [0.0, 0.0, 1.0] or top["normal"] != [0.0, 0.0, 1.0]:
            fail(f"TOP_CENTER is wrong: {top}")
        if top["type"] != "face_center" or top["source"] != "evaluated_aabb":
            fail(f"TOP_CENTER metadata is wrong: {top}")
        surface = anchors["SURFACE_+Z"]
        if surface["source"] != "bvh_raycast" or surface["position"][2] < 0.99:
            fail(f"SURFACE_+Z is wrong: {surface}")
        if anchors["CORNER_X0Y0Z0"]["position"] != [-0.5, -0.5, 0.0]:
            fail(f"CORNER_X0Y0Z0 is wrong: {anchors['CORNER_X0Y0Z0']}")
        if anchors["EDGE_X0Y0"]["position"] != [-0.5, -0.5, 0.5]:
            fail(f"EDGE_X0Y0 is wrong: {anchors['EDGE_X0Y0']}")

        aligned = server.anchor_operation(
            "align", part_name="AnchorPart", part_anchor="BOTTOM_CENTER",
            target_name="AnchorTarget", target_anchor="TOP_CENTER",
        )
        if not aligned["passed"] or aligned["distance"] > 0.001:
            fail(f"align failed: {aligned}")
        if abs(anchor_part.location.z - 1.1) > 0.001:
            fail(f"align placed the part at z={anchor_part.location.z}")

        mated = server.anchor_operation(
            "mate", part_name="AnchorPart", part_anchor="BOTTOM_CENTER",
            target_name="AnchorTarget", target_anchor="TOP_CENTER", gap=0.01,
        )
        if not mated["passed"] or mated["normal_dot"] < 0.999:
            fail(f"mate failed: {mated}")
        if abs(anchor_part.location.z - 1.11) > 0.001:
            fail(f"mate placed the part at z={anchor_part.location.z}")

        offset = server.anchor_operation(
            "offset", part_name="AnchorPart", part_anchor="CENTER",
            offset=[0.0, 0.5, 0.0],
        )
        if abs(offset["part_anchor"]["position"][1] - 0.5) > 0.001:
            fail(f"offset failed: {offset}")

        oriented = server.anchor_operation(
            "orient_normal", part_name="AnchorPart", part_anchor="CENTER",
            normal=[1.0, 0.0, 0.0],
        )
        if not oriented["passed"] or oriented["dot"] < 0.999:
            fail(f"orient_normal failed: {oriented}")

        clear_scene()
        distributed_objects = []
        for index in range(3):
            item = make_cube(f"Dist{index}", 0.2)
            item.location = (float(index), 0.0, 0.1)
            distributed_objects.append(item)
        bpy.context.view_layer.update()
        distributed = server.anchor_operation(
            "distribute", object_names=[item.name for item in distributed_objects],
            axis="X", spacing=0.5,
        )
        if not distributed["passed"]:
            fail(f"distribute failed: {distributed}")
        positions = sorted(item.location.x for item in distributed_objects)
        expected_positions = [0.0, 0.5, 1.0]
        if any(abs(actual - expected) > 0.001 for actual, expected in zip(positions, expected_positions, strict=False)):
            fail(f"distribute positions are wrong: {positions}")

        clear_scene()
        mirror_source = make_cube("MirrorA", 0.4)
        mirror_source.location = (1.0, 0.0, 0.2)
        bpy.context.view_layer.update()
        mirrored = server.anchor_operation(
            "mirror", object_names=["MirrorA"], axis="X", plane=0.0, duplicate=True,
        )
        if not mirrored["created"]:
            fail(f"mirror did not create a copy: {mirrored}")
        mirror_copy = bpy.data.objects.get(mirrored["created"][0])
        if not mirror_copy or abs(mirror_copy.location.x + 1.0) > 0.001:
            fail(f"mirror copy is in the wrong place: {mirrored}")
        mirror_audit = server.audit_3d_model(
            object_names=["MirrorA", mirrored["created"][0]]
        )
        if not mirror_audit["requirements"]["normalized_scale"]["passed"]:
            fail("mirror negative scale failed normalized_scale")

        # --- constraint validation ---
        clear_scene()
        constraint_base = make_cube("ConstraintBase", 1.0)
        constraint_base.location = (0.0, 0.0, 0.5)
        constraint_top = make_cube("ConstraintTop", 0.2)
        constraint_top.location = (0.0, 0.0, 1.1)
        constraint_inside = make_cube("ConstraintInside", 0.2)
        constraint_inside.location = (0.0, 0.0, 0.5)
        bpy.context.view_layer.update()

        constraints = [
            {
                "type": "mate", "a": "ConstraintTop", "b": "ConstraintBase",
                "a_anchor": "BOTTOM_CENTER", "b_anchor": "TOP_CENTER",
                "gap": 0.0, "tolerance": 0.001,
            },
            {
                "type": "align", "a": "ConstraintTop", "b": "ConstraintBase",
                "a_anchor": "BOTTOM_CENTER", "b_anchor": "TOP_CENTER",
                "tolerance": 0.001,
            },
            {
                "type": "distance", "a": "ConstraintTop", "b": "ConstraintBase",
                "a_anchor": "BOTTOM_CENTER", "b_anchor": "TOP_CENTER",
                "distance": 0.0, "tolerance": 0.001,
            },
            {
                "type": "offset", "a": "ConstraintTop", "b": "ConstraintBase",
                "a_anchor": "BOTTOM_CENTER", "b_anchor": "TOP_CENTER",
                "offset": [0.0, 0.0, 0.0], "tolerance": 0.001,
            },
            {
                "type": "flush", "a": "ConstraintTop", "b": "ConstraintBase",
                "a_anchor": "BOTTOM_CENTER", "b_anchor": "TOP_CENTER",
                "tolerance": 0.001,
            },
            {
                "type": "parallel", "a": "ConstraintBase", "a_anchor": "TOP_CENTER",
                "b": "ConstraintTop", "b_anchor": "BOTTOM_CENTER",
                "tolerance": 0.001,
            },
            {
                "type": "perpendicular", "a": "ConstraintBase", "a_anchor": "TOP_CENTER",
                "b": "ConstraintBase", "b_anchor": "RIGHT_CENTER",
                "tolerance": 0.001,
            },
            {
                "type": "center", "objects": ["ConstraintTop", "ConstraintBase"],
                "axes": ["X", "Y"], "tolerance": 0.001,
            },
            {
                "type": "ground_contact",
                "objects": ["ConstraintBase", "ConstraintTop"],
                "tolerance": 0.005,
            },
            {
                "type": "no_intersection",
                "objects": ["ConstraintTop", "ConstraintBase"],
                "tolerance": 0.001,
            },
            {
                "type": "surface_contact", "a": "ConstraintTop", "b": "ConstraintBase",
                "tolerance": 0.001,
            },
            {
                "type": "inside", "inner": "ConstraintInside", "outer": "ConstraintBase",
                "tolerance": 0.001,
            },
        ]
        constraint_result = server.validate_constraints(constraints)
        if not constraint_result["passed"]:
            fail(f"constraint validation failed: {constraint_result['results']}")

        failed_constraint = server.validate_constraints([{
            "type": "distance", "a": "ConstraintTop", "b": "ConstraintBase",
            "a_anchor": "BOTTOM_CENTER", "b_anchor": "TOP_CENTER",
            "distance": 1.0, "tolerance": 0.001,
        }])
        if failed_constraint["passed"] or failed_constraint["failed_count"] != 1:
            fail(f"constraint validator accepted a wrong distance: {failed_constraint}")

        unknown_constraint = server.validate_constraints([{"type": "does_not_exist"}])
        if unknown_constraint["passed"] or not unknown_constraint["results"][0].get("error"):
            fail(f"constraint validator accepted an unknown type: {unknown_constraint}")

        clear_scene()
        apply_target = make_cube("ApplyTarget", 1.0)
        apply_target.location = (0.0, 0.0, 0.5)
        apply_part = make_cube("ApplyPart", 0.2)
        apply_part.location = (2.0, 0.0, 0.1)
        bpy.context.view_layer.update()
        applied = server.apply_constraints([
            {
                "type": "align", "a": "ApplyPart", "b": "ApplyTarget",
                "a_anchor": "BOTTOM_CENTER", "b_anchor": "TOP_CENTER",
            },
            {
                "type": "ground_contact", "objects": ["ApplyTarget"],
            },
            {
                "type": "no_intersection", "objects": ["ApplyPart", "ApplyTarget"],
            },
        ])
        if not applied["passed"]:
            fail(f"apply_constraints failed: {applied['report']}")
        if abs(apply_part.location.z - 1.1) > 0.001:
            fail(f"apply_constraints placed the part at z={apply_part.location.z}")

        # --- declarative assemblies ---
        clear_scene()
        desk_spec = {
            "name": "ParamDesk",
            "type": "desk",
            "dimensions_mm": {"width": 1600, "depth": 800, "height": 750},
            "materials": {
                "top": [0.45, 0.30, 0.20],
                "legs": [0.20, 0.20, 0.20],
            },
            "constraints": [
                {
                    "type": "ground_contact",
                    "objects": ["Leg_FL", "Leg_FR", "Leg_BL", "Leg_BR"],
                    "tolerance": 0.005,
                },
                {
                    "type": "no_intersection",
                    "objects": ["Top", "Leg_FL"],
                    "tolerance": 0.001,
                },
            ],
        }
        desk = server.create_assembly(desk_spec)
        if not desk.get("success") or desk.get("passed") is not True:
            fail(
                "desk assembly failed: "
                f"{desk.get('audit', {}).get('failures')} {desk.get('constraints')}"
            )
        desk_dims = desk["audit"]["dimensions"]["objects"]["ParamDesk_Top"]["dimensions"]
        if any(
            abs(actual - expected) > 0.005
            for actual, expected in zip(desk_dims, [1.6, 0.8, 0.03], strict=False)
        ):
            fail(f"desk top dimensions are wrong: {desk_dims}")
        desk_top = bpy.data.objects.get("ParamDesk_Top")
        if not desk_top or abs(desk_top.location.z - 0.72) > 0.001:
            fail("desk top is not at leg height")
        desk_leg = bpy.data.objects.get("ParamDesk_Leg_FL")
        if not desk_leg or abs(desk_leg.location.x + 0.72) > 0.001:
            fail("desk leg is not at the expected inset")

        for shape in ("CAPSULE", "TORUS", "TUBE"):
            dimensions = [0.6, 0.4, 0.2] if shape == "TORUS" else [0.6, 0.4, 0.8]
            part = server.create_parametric_part(
                name=f"Audit_{shape}", shape=shape, dimensions=dimensions, bevel_width=0,
            )
            if part["dimensions"] != dimensions:
                fail(f"{shape} dimensions {part['dimensions']} != {dimensions}")
            metrics = bm.GeometryService.topology_metrics(bpy.data.objects[part["name"]])
            if metrics["non_manifold_edges"] or metrics["zero_area_faces"]:
                fail(f"{shape} is not a clean closed mesh: {metrics}")

        names_before = set(bpy.data.objects.keys())
        invalid_components = [
            {"name": "Valid", "color": [0.1, 0.2, 0.3, 1.0]},
            {"name": "Invalid", "material_name": "MissingAssemblyMaterial"},
        ]
        try:
            server.update_assembly("ParamDesk", spec={"components": invalid_components})
        except ValueError:
            pass
        else:
            fail("Invalid assembly update returned successfully")
        if bpy.data.objects.get("ParamDesk_Top") != desk_top or set(bpy.data.objects.keys()) != names_before:
            fail("Failed assembly update changed scene objects")
        if bpy.data.materials.get("Mat_ParamDesk_Valid") or bpy.data.meshes.get("ParamDesk_Valid_Mesh"):
            fail("Failed assembly update left unused data")

        for kwargs in (
            {"object_names": ["ParamDesk_Leg_FL", "MissingPart"]},
            {"blueprint_name": "missing_blueprint"},
            {"symmetry_axis": "invalid"},
            {"topology_policy": "invalid"},
        ):
            arguments = {"object_names": desk["components"]}
            arguments.update(kwargs)
            try:
                report = server.audit_3d_model(**arguments)
            except ValueError:
                continue
            if report["passed"]:
                fail(f"Audit approved an unverifiable requirement: {kwargs}")

        updated_desk = server.update_assembly(
            "ParamDesk",
            changes={"dimensions_mm": {"width": 1200}},
        )
        if not updated_desk.get("passed"):
            fail(f"updated desk failed: {updated_desk.get('audit', {}).get('failures')}")
        updated_dims = updated_desk["audit"]["dimensions"]["objects"]["ParamDesk_Top"]["dimensions"]
        if abs(updated_dims[0] - 1.2) > 0.005:
            fail(f"updated desk width is wrong: {updated_dims}")
        if bpy.data.objects.get("ParamDesk_Top.001") is not None:
            fail("update_assembly left duplicate components")
        updated_leg = bpy.data.objects.get("ParamDesk_Leg_FL")
        if not updated_leg or abs(updated_leg.location.x + 0.528) > 0.005:
            fail("updated desk leg did not move with the width")

        clear_scene()
        bracket = server.create_assembly({
            "name": "BracketAssembly",
            "components": [
                {
                    "name": "Plate",
                    "shape": "BOX",
                    "dimensions": [0.2, 0.2, 0.01],
                    "location": [0.0, 0.0, 0.0],
                    "origin": "BOTTOM",
                },
                {
                    "name": "Post",
                    "shape": "CYLINDER",
                    "dimensions": [0.02, 0.02, 0.1],
                    "location": [0.0, 0.0, 0.01],
                    "origin": "BOTTOM",
                },
            ],
            "constraints": [
                {"type": "ground_contact", "objects": ["Plate"], "tolerance": 0.005},
            ],
        })
        if not bracket.get("success") or not bracket.get("passed"):
            fail(
                "custom component assembly failed: "
                f"{bracket.get('audit', {}).get('failures')} {bracket.get('constraints')}"
            )

        # --- domain packs: terrain, vegetation, water, materials, lighting, physics ---
        clear_scene()
        domain_dir = tempfile.mkdtemp(prefix="blendermcp_domain_")
        os.environ["BLENDER_MCP_OUTPUT_DIR"] = domain_dir
        try:
            terrain = server.create_terrain(
                "DomainTerrain", size=4.0, subdivisions=16, height=0.5, seed=2
            )
            assert terrain["success"] and terrain["dimensions"][0] == 4.0, terrain
            sculpted = server.sculpt_terrain_region(
                "DomainTerrain", center=[0.0, 0.0, 0.0], radius=1.0,
                strength=0.1, direction="UP",
            )
            assert sculpted["success"] and sculpted["moved_count"] > 0, sculpted
            rock = server.create_rock("DomainRock", size=0.5, subdivisions=1, seed=2)
            assert rock["success"] and max(rock["dimensions"]) > 0.0, rock
            scattered = server.scatter_objects(
                "DomainRock", "DomainTerrain", count=4, seed=2
            )
            assert scattered["success"] and scattered["count"] == 4, scattered
            tree = server.create_tree("DomainTree", height=2.0, crown_radius=0.5, seed=2)
            assert tree["success"] and tree["polygon_count"] > 0, tree
            bush = server.create_bush("DomainBush", radius=0.3, height=0.3, seed=2)
            assert bush["success"] and bush["polygon_count"] > 0, bush
            grass = server.create_grass_patch(
                "DomainGrass", radius=0.3, blade_count=10, seed=2
            )
            assert grass["success"] and grass["polygon_count"] > 0, grass
            flowers = server.create_flower_patch(
                "DomainFlowers", radius=0.3, count=3, seed=2
            )
            assert flowers["success"] and flowers["polygon_count"] > 0, flowers
            water = server.create_water_plane("DomainWater", size=3.0, subdivisions=8)
            assert water["success"] and water["dimensions"] == [3.0, 3.0], water
            river = server.create_river("DomainRiver", width=0.5, segments=4)
            assert river["success"] and river["length"] > 0.0, river
            pond = server.create_pond("DomainPond", radius=1.0, segments=12)
            assert pond["success"] and pond["face_count"] > 0, pond
            water_material = server.create_water_material("DomainWaterMaterial")
            assert water_material["success"], water_material
            procedural = server.create_procedural_material("DomainProcedural")
            assert procedural["success"], procedural

            server.create_parametric_part(
                "DomainCube", shape="BOX", dimensions=[0.5, 0.5, 0.5],
                location=[0.0, 0.0, 0.25],
            )
            uv = server.smart_uv_unwrap("DomainCube")
            assert uv["success"] and uv["uv_layer"], uv
            packed = server.pack_uv_islands("DomainCube")
            assert packed["success"], packed
            materials = server.list_materials()
            assert materials["success"] and materials["count"] > 0, materials

            light = server.create_light("DomainLight", energy=50.0)
            assert light["success"] and light["type"] == "POINT", light
            camera = server.create_camera(
                "DomainCamera", location=[3.0, -3.0, 2.0], look_at=[0.0, 0.0, 0.5]
            )
            assert camera["success"] and camera["type"] == "PERSP", camera
            world = server.setup_world_background(color=[0.05, 0.05, 0.05])
            assert world["success"], world
            render = server.render_still(
                "domain.png", camera_name="DomainCamera",
                resolution_x=64, resolution_y=64, samples=4,
            )
            assert render["success"] and os.path.exists(render["filepath"]), render

            rigid = server.add_rigid_body("DomainCube", body_type="ACTIVE")
            assert rigid["success"], rigid
            collision = server.add_collision("DomainCube")
            assert collision["success"], collision
            server.create_parametric_part(
                "DomainCloth", shape="ROUNDED_BOX", dimensions=[0.5, 0.5, 0.02],
                location=[0.0, 0.0, 1.0],
            )
            cloth = server.add_cloth("DomainCloth")
            assert cloth["success"], cloth
            baked = server.bake_simulation(1, 1)
            assert baked["success"] and baked["baked"], baked
        finally:
            os.environ.pop("BLENDER_MCP_OUTPUT_DIR", None)
            shutil.rmtree(domain_dir, ignore_errors=True)

        # --- v4.2 architecture and hard-surface packs ---
        clear_scene()
        room = server.create_room_shell(
            "V42Room", width=5.0, depth=4.0, height=3.0
        )
        assert room["success"] and bpy.data.objects.get("V42Room_Floor"), room
        assert bpy.data.objects.get("V42Room_Walls"), room
        door = server.create_door("V42Door", location=[0.0, -2.0, 0.0])
        assert door["success"] and bpy.data.objects.get("V42Door"), door
        window = server.create_window("V42Window", location=[2.5, 0.0, 1.0])
        assert window["success"] and bpy.data.objects.get("V42Window"), window
        for name, factory in (
            ("V42Table", server.create_table),
            ("V42Chair", server.create_chair),
            ("V42Shelf", server.create_shelf),
            ("V42Bed", server.create_bed),
            ("V42Sofa", server.create_sofa),
            ("V42Kitchen", server.create_kitchen_block),
        ):
            result = factory(name)
            assert result["success"] and bpy.data.objects.get(name), result
            assert result["polygon_count"] > 0, result

        server.create_parametric_part(
            "V42Hard", shape="BOX", dimensions=[0.5, 0.5, 0.5],
            location=[0.0, 0.0, 0.25],
        )
        for modifier in (
            server.add_bevel_modifier("V42Hard", width=0.01),
            server.add_solidify_modifier("V42Hard", thickness=0.01),
            server.add_array_modifier("V42Hard", count=2, offset=[0.6, 0.0, 0.0]),
            server.add_mirror_modifier("V42Hard", axis="X"),
        ):
            assert modifier["success"], modifier
        applied = server.apply_all_modifiers("V42Hard")
        assert applied["success"] and len(applied["applied"]) == 4, applied

        text = server.create_text_object("V42", name="V42Text", size=0.5)
        assert text["success"] and bpy.data.objects.get("V42Text"), text
        tube = server.create_curve_tube(
            "V42Tube", points=[[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]], radius=0.05
        )
        assert tube["success"] and bpy.data.objects.get("V42Tube"), tube
        meta = server.create_metaball("V42Meta", radius=0.4)
        assert meta["success"] and bpy.data.objects.get("V42Meta"), meta
        converted_tube = server.convert_to_mesh("V42Tube")
        assert converted_tube["success"] and converted_tube["type"] == "MESH", converted_tube
        converted_meta = server.convert_to_mesh("V42Meta")
        assert converted_meta["success"] and converted_meta["type"] == "MESH", converted_meta

        # --- v4.3 environment, character, PBR and animation packs ---
        clear_scene()
        sky = server.create_sky_lighting("V43Sky", sun_elevation=30.0)
        assert sky["success"] and bpy.data.objects.get("V43Sky_Sun"), sky
        fog = server.create_fog_volume("V43Fog", size=5.0, density=0.01)
        assert fog["success"] and bpy.data.objects.get("V43Fog"), fog
        clouds = server.create_cloud_layer("V43Clouds", size=5.0, altitude=3.0)
        assert clouds["success"] and bpy.data.objects.get("V43Clouds"), clouds
        ground = server.create_ground(
            "V43Ground", size=6.0, subdivisions=8, style="grass"
        )
        assert ground["success"] and bpy.data.objects.get("V43Ground"), ground
        cliff = server.create_cliff(
            "V43Cliff", width=2.0, height=1.5, depth=1.0
        )
        assert cliff["success"] and bpy.data.objects.get("V43Cliff"), cliff
        beach = server.create_beach("V43Beach", width=5.0, depth=3.0)
        assert beach["success"] and bpy.data.objects.get("V43Beach"), beach
        shore = server.create_water_shore("V43Shore", radius=2.0)
        assert shore["success"] and bpy.data.objects.get("V43Shore"), shore
        server.create_tree("V43Tree", height=2.0, crown_radius=0.5, seed=3)
        server.create_bush("V43Bush", radius=0.3, height=0.3, seed=3)
        biome = server.create_biome_scatter(
            "V43Ground", "V43Tree", "V43Bush", count=4, seed=3
        )
        assert biome["success"] and biome["count"] == 4, biome

        humanoid = server.create_humanoid_blockout(
            "V43Human", height=1.75, build="average"
        )
        assert humanoid["success"] and humanoid["actual_height"] == 1.75, humanoid
        eyes = server.create_eye_pair("V43Eyes", height=1.62)
        assert eyes["success"] and len(eyes["eyes"]) == 2, eyes
        teeth = server.create_teeth_set("V43Teeth")
        assert teeth["success"] and teeth["tooth_count"] == 16, teeth
        hair = server.create_hair_cap(
            "V43Hair", head_object="V43Human", radius=0.10,
            strand_count=10, seed=3,
        )
        assert hair["success"] and bpy.data.objects.get("V43Hair"), hair
        garment = server.create_garment("V43Shirt", garment_type="shirt")
        assert garment["success"] and bpy.data.objects.get("V43Shirt"), garment
        landmarks = server.create_face_landmarks("V43Human")
        assert landmarks["success"] and len(landmarks["landmarks"]) == 7, landmarks
        hand = server.create_hand_blockout("V43Hand", side="L")
        assert hand["success"] and bpy.data.objects.get("V43Hand_L"), hand
        foot = server.create_foot_blockout("V43Foot", side="L")
        assert foot["success"] and bpy.data.objects.get("V43Foot_L"), foot

        for material_name, factory in (
            ("V43Metal", server.create_metal_material),
            ("V43Wood", server.create_wood_material),
            ("V43Fabric", server.create_fabric_material),
            ("V43Glass", server.create_glass_material),
            ("V43Skin", server.create_skin_material),
            ("V43Concrete", server.create_concrete_material),
            ("V43Emission", server.create_emission_material),
        ):
            material = factory(material_name)
            assert material["success"] and bpy.data.materials.get(material_name), material
        assigned = server.assign_material_to_faces("V43Human", "V43Metal")
        assert assigned["success"] and assigned["assigned_count"] > 0, assigned

        frame = server.set_frame_range(1, 60, 24)
        assert frame["success"] and frame["frame_end"] == 60, frame
        path = server.keyframe_path(
            "V43Human", points=[[0, 0, 0], [1, 0, 0], [2, 0, 0]],
            frame_start=1, frame_end=30,
        )
        assert path["success"] and path["keyframes"] > 0, path
        turntable = server.create_turntable_animation("V43Human", frames=60)
        assert turntable["success"], turntable
        rig = server.create_camera_rig(
            "V43CamRig", target=[0.0, 0.0, 1.0], distance=4.0, height=2.0
        )
        assert rig["success"] and bpy.data.objects.get("V43CamRig_Camera"), rig
        server.create_curve_tube(
            "V43AnimPath", points=[[0, 0, 0], [0, 2, 0], [0, 4, 0]],
            radius=0.03,
        )
        follow = server.add_follow_path_constraint(
            "V43Human", "V43AnimPath", offset=0.0
        )
        assert follow["success"], follow
        interpolation = server.set_keyframe_interpolation("V43Human", "LINEAR")
        assert interpolation["success"], interpolation
        action = server.create_action("V43Human", "V43Action")
        assert action["success"] and action["action"] == "V43Action", action
        cleared = server.clear_animation("V43Human")
        assert cleared["success"], cleared

        # --- v4.4 pipeline, render QA, rigging and texture packs ---
        clear_scene()
        v44_dir = tempfile.mkdtemp(prefix="blendermcp_v44_")
        os.environ["BLENDER_MCP_OUTPUT_DIR"] = v44_dir
        try:
            server.create_parametric_part(
                "V44Cube", shape="BOX", dimensions=[1.0, 1.0, 1.0],
                location=[0.0, 0.0, 0.5],
            )
            bpy.ops.object.select_all(action="DESELECT")
            bpy.data.objects["V44Cube"].select_set(True)
            bpy.context.view_layer.objects.active = bpy.data.objects["V44Cube"]
            exported = server.export_selected("exports/v44_cube.glb", "GLB")
            assert exported["success"] and os.path.exists(exported["filepath"]), exported
            imported = server.import_model(exported["filepath"], "AUTO")
            assert imported["success"] and imported["object_count"] >= 1, imported
            batch = server.batch_export(["V44Cube"], "batch", "GLB")
            assert batch["success"] and batch["count"] == 1, batch
            lod = server.create_lod_chain("V44Cube", [1.0, 0.5, 0.25])
            assert lod["success"] and len(lod["lod_names"]) == 3, lod
            lod_check = server.validate_lod_chain("V44Cube")
            assert lod_check["success"] and isinstance(lod_check["passed"], bool), lod_check
            manifest = server.generate_asset_manifest(
                ["V44Cube"], "v44_manifest.json"
            )
            assert manifest["success"] and os.path.exists(manifest["filepath"]), manifest

            image = server.create_image(
                "V44Solid", 64, 64, [0.8, 0.2, 0.2, 1.0], False
            )
            assert image["success"], image
            checker = server.create_checker_texture("V44Checker", 64, 64, cells=8)
            assert checker["success"], checker
            material = server.image_to_material("V44Checker", "V44CheckMat", 0.4)
            assert material["success"], material
            image_node = server.add_image_texture_node("V44CheckMat", "V44Checker")
            assert image_node["success"], image_node
            resized = server.resize_image("V44Solid", 32, 32)
            assert resized["success"], resized
            colorspace = server.set_image_colorspace("V44Solid", "sRGB")
            assert colorspace["success"], colorspace
            packed = server.pack_image("V44Solid")
            assert packed["success"], packed
            saved_image = server.save_image(
                "V44Checker", "textures/v44_checker.png", "PNG"
            )
            assert saved_image["success"] and os.path.exists(saved_image["filepath"]), saved_image
            packed_all = server.pack_images()
            assert packed_all["success"], packed_all
            saved_all = server.save_images("textures/all", "PNG")
            assert saved_all["success"], saved_all

            backdrop = server.create_studio_backdrop("V44Backdrop")
            assert backdrop["success"], backdrop
            configured = server.configure_render(
                "BLENDER_EEVEE_NEXT", 2, 64, 64, False, 24
            )
            assert configured["success"], configured
            render_pass = server.enable_render_pass("AO", True)
            assert render_pass["success"], render_pass
            glare = server.setup_compositor_glare(1.0, 6, 0.0)
            assert glare["success"], glare
            turntable = server.render_turntable(
                "turntable", frames=1, resolution_x=64, resolution_y=64, samples=2
            )
            assert turntable["success"] and len(turntable["files"]) == 1, turntable
            turntable_file = turntable["files"][0]
            sheet = server.render_contact_sheet(
                [turntable_file, turntable_file], "v44_contact.png", 2
            )
            assert sheet["success"] and os.path.exists(sheet["filepath"]), sheet
            render_valid = server.validate_render("v44_contact.png", 64, 64)
            assert render_valid["success"] and render_valid["valid"], render_valid
            compared = server.compare_renders(turntable_file, turntable_file)
            assert compared["success"] and compared["identical"], compared

            rig = server.create_armature("V44Rig", [
                {"name": "Root", "head": [0.0, 0.0, 0.2], "tail": [0.0, 0.0, 0.8]}
            ])
            assert rig["success"], rig
            bone = server.create_bone(
                "V44Rig", "Tip", [0.0, 0.0, 0.8], [0.0, 0.0, 1.0], "Root", False
            )
            assert bone["success"], bone
            bones = server.list_bones("V44Rig")
            assert bones["success"] and bones["bone_count"] == 2, bones
            ik = server.create_ik_chain("V44Rig", "Tip", "V44Cube", 2)
            assert ik["success"], ik
            copy_rotation = server.add_copy_rotation_constraint(
                "V44Rig", "Tip", "V44Cube", 0.5
            )
            assert copy_rotation["success"], copy_rotation
            limit_rotation = server.add_limit_rotation_constraint(
                "V44Rig", "Tip", ["X", "Y", "Z"], [-45.0, 45.0]
            )
            assert limit_rotation["success"], limit_rotation
            bone_rotation = server.set_bone_rotation("V44Rig", "Tip", [10.0, 0.0, 0.0])
            assert bone_rotation["success"], bone_rotation
            bone_location = server.set_bone_location("V44Rig", "Tip", [0.1, 0.0, 0.0])
            assert bone_location["success"], bone_location
            skinned = server.skin_mesh_to_armature("V44Cube", "V44Rig", True)
            assert skinned["success"] and skinned["vertex_group_count"] > 0, skinned
        finally:
            os.environ.pop("BLENDER_MCP_OUTPUT_DIR", None)
            shutil.rmtree(v44_dir, ignore_errors=True)

        # --- v4.5 props, furniture, vehicles and character detail ---
        clear_scene()
        for name, factory in (
            ("V45Barrel", server.create_barrel),
            ("V45Crate", server.create_crate),
            ("V45Chest", server.create_chest),
            ("V45Lantern", server.create_lantern),
            ("V45Lamp", server.create_streetlamp),
            ("V45Sword", server.create_sword),
            ("V45Shield", server.create_shield),
            ("V45Potion", server.create_potion_bottle),
            ("V45Desk", server.create_desk),
            ("V45Wardrobe", server.create_wardrobe),
            ("V45Dresser", server.create_dresser),
            ("V45Nightstand", server.create_nightstand),
            ("V45Coffee", server.create_coffee_table),
            ("V45Bench", server.create_bench),
            ("V45Stool", server.create_bar_stool),
            ("V45Bookshelf", server.create_bookshelf),
            ("V45Wheel", server.create_wheel),
            ("V45Car", server.create_car_blockout),
            ("V45Bicycle", server.create_bicycle_blockout),
            ("V45Motorcycle", server.create_motorcycle_blockout),
            ("V45Boat", server.create_boat_blockout),
            ("V45Aircraft", server.create_aircraft_blockout),
            ("V45Robot", server.create_robot_blockout),
            ("V45Drone", server.create_drone_blockout),
        ):
            result = factory(name)
            assert result["success"] and bpy.data.objects.get(name), result
            assert result["polygon_count"] > 0, result
        for name, factory in (
            ("V45Nose", server.create_nose),
            ("V45Ears", server.create_ear_pair),
            ("V45Mouth", server.create_mouth),
            ("V45Brows", server.create_brow_pair),
            ("V45Lashes", server.create_eyelash_pair),
            ("V45Hair", server.create_hair_strands),
            ("V45Nails", server.create_fingernails),
        ):
            kwargs = {"strand_count": 8} if name in {"V45Lashes", "V45Hair"} else {}
            result = factory(name, **kwargs)
            assert result["success"], result
        server.create_humanoid_blockout("V45Char", height=1.75)
        proportions = server.create_face_proportions("V45Char")
        assert proportions["success"] and len(proportions["landmarks"]) == 8, proportions

        # --- v4.6 advanced materials, nature, architecture and rigging ---
        clear_scene()
        server.create_parametric_part(
            "V46Bake", shape="BOX", dimensions=[1.0, 1.0, 1.0],
            location=[0.0, 0.0, 0.5],
        )
        server.create_material("V46BakeMat", [0.8, 0.3, 0.2, 1.0], 0.0, 0.5)
        server.assign_material("V46Bake", "V46BakeMat")
        for _bake_name, bake_call in (
            ("V46AO", lambda: server.bake_ambient_occlusion("V46Bake", 32, 1)),
            ("V46Normal", lambda: server.bake_normal_map("V46Bake", 32)),
            ("V46Diffuse", lambda: server.bake_diffuse("V46Bake", 32)),
        ):
            baked = bake_call()
            assert baked["success"] and baked["baked"], baked
        udim = server.create_udim_tiles("V46UDIM", [1001, 1002], 32)
        assert udim["success"] and udim["tile_count"] == 2, udim
        displacement = server.add_displacement("V46BakeMat", 0.1, 0.5)
        assert displacement["success"], displacement
        layer_mix = server.create_layer_weight_mix("V46LayerMix")
        assert layer_mix["success"], layer_mix
        parallax = server.create_parallax_bump("V46LayerMix", 0.05)
        assert parallax["success"], parallax
        optimized = server.optimize_material("V46LayerMix")
        assert optimized["success"], optimized

        forest = server.create_forest("V46Forest", radius=3.0, tree_count=3)
        assert forest["success"] and forest["count"] == 3, forest
        grass = server.create_grass_field("V46Grass", size=3.0, blade_count=10)
        assert grass["success"], grass
        rocks = server.create_rock_cluster("V46Rocks", radius=2.0, count=3)
        assert rocks["success"], rocks
        mountain = server.create_mountain_range(
            "V46Mountains", width=6.0, depth=3.0, peak_height=1.5
        )
        assert mountain["success"], mountain
        cave = server.create_cave("V46Cave", width=3.0, depth=2.0, height=2.0)
        assert cave["success"], cave
        island = server.create_island("V46Island", radius=3.0)
        assert island["success"], island
        waterfall = server.create_waterfall("V46Waterfall", width=1.0, height=2.0)
        assert waterfall["success"], waterfall
        biome = server.create_biome("V46Biome", size=4.0)
        assert biome["success"], biome

        bathroom = server.create_bathroom_set("V46Bathroom", 2.0, 2.0)
        assert bathroom["success"], bathroom
        kitchen = server.create_kitchen_island("V46Kitchen", 1.5, 0.8, 0.9)
        assert kitchen["success"], kitchen
        fireplace = server.create_fireplace("V46Fireplace", 1.2, 1.0, 0.3)
        assert fireplace["success"], fireplace
        balcony = server.create_balcony("V46Balcony", 2.5, 1.0, 1.0)
        assert balcony["success"], balcony
        fence = server.create_fence("V46Fence", 4.0, 1.0, 5)
        assert fence["success"], fence
        gate = server.create_gate("V46Gate", 2.5, 1.8)
        assert gate["success"], gate
        garage = server.create_garage("V46Garage", 4.0, 4.0, 2.5)
        assert garage["success"], garage
        pool = server.create_pool("V46Pool", 4.0, 2.0, 1.0)
        assert pool["success"], pool

        server.create_armature("V46Rig", [
            {"name": "Root", "head": [0.0, 0.0, 0.2], "tail": [0.0, 0.0, 0.8]}
        ])
        server.create_bone(
            "V46Rig", "Tip", [0.0, 0.0, 0.8], [0.0, 0.0, 1.0], "Root", False
        )
        server.create_parametric_part(
            "V46Target", shape="BOX", dimensions=[0.1, 0.1, 0.1],
            location=[0.0, 0.0, 1.0],
        )
        for _constraint_name, constraint_call in (
            ("V46ChildOf", lambda: server.add_child_of_constraint(
                "V46Rig", "Tip", "V46Target"
            )),
            ("V46CopyLoc", lambda: server.add_copy_location_constraint(
                "V46Rig", "Tip", "V46Target", 0.5
            )),
            ("V46Damped", lambda: server.add_damped_track_constraint(
                "V46Rig", "Tip", "V46Target"
            )),
            ("V46Stretch", lambda: server.add_stretch_to_constraint(
                "V46Rig", "Tip", "V46Target"
            )),
        ):
            constraint = constraint_call()
            assert constraint["success"], constraint
        shape = server.set_bone_custom_shape("V46Rig", "Tip", "V46Target")
        assert shape["success"], shape
        pose = server.create_pose_library_action("V46Rig", "V46Pose")
        assert pose["success"] and pose["keyframed_bones"] == 2, pose
        mirrored = server.mirror_pose("V46Rig", "X")
        assert mirrored["success"], mirrored
        rig_check = server.validate_rig("V46Rig")
        assert rig_check["success"], rig_check

        # --- v4.7 advanced animation, physics, QA and weather ---
        clear_scene()
        server.create_parametric_part(
            "V47Cube", shape="BOX", dimensions=[1.0, 1.0, 1.0],
            location=[0.0, 0.0, 0.5],
        )
        server.create_action("V47Cube", "V47Action")
        server.keyframe_object("V47Cube", "location", 1, [0.0, 0.0, 0.5])
        server.keyframe_object("V47Cube", "location", 10, [1.0, 0.0, 0.5])
        server.create_camera("V47Cam1", location=[4.0, -4.0, 3.0], look_at=[0.0, 0.0, 0.5])
        server.create_camera("V47Cam2", location=[-4.0, -4.0, 3.0], look_at=[0.0, 0.0, 0.5])
        nla = server.create_nla_track("V47Cube", "V47Action", 1)
        assert nla["success"], nla
        shake = server.add_camera_shake("V47Cam1", 0.03, 1, 5, 2)
        assert shake["success"], shake
        marker = server.add_timeline_marker("V47Start", 1)
        assert marker["success"], marker
        motion = server.set_motion_paths("V47Cube", True)
        assert motion["success"] and motion["curve"], motion
        preset = server.set_animation_curve_preset("V47Cube", "ease_in_out")
        assert preset["success"], preset
        retime = server.retime_action("V47Cube", 1.2)
        assert retime["success"], retime
        cut = server.create_camera_cut(
            ["V47Cam1", "V47Cam2"], [[1, 5], [6, 10]]
        )
        assert cut["success"] and cut["cut_count"] == 2, cut
        animation_check = server.validate_animation("V47Cube")
        assert animation_check["success"], animation_check

        force = server.add_force_field("V47Wind", "WIND", 2.0, [0.0, 0.0, 0.0])
        assert force["success"], force
        rigid = server.create_rigid_body_chain(["V47Cube"], 1.0)
        assert rigid["success"] and rigid["count"] == 1, rigid
        server.create_parametric_part(
            "V47Cloth", shape="BOX", dimensions=[1.0, 1.0, 0.01],
            location=[0.0, 0.0, 1.0],
        )
        cloth = server.create_cloth_preset("V47Cloth", "silk")
        assert cloth["success"], cloth
        domain = server.create_fluid_domain("V47Fluid", [2.0, 2.0, 2.0], 16)
        assert domain["success"], domain
        inflow = server.create_fluid_inflow(
            "V47Cube", "V47Fluid", [0.0, 0.0, -1.0]
        )
        assert inflow["success"], inflow
        collision = server.create_collision_object("V47Cloth", 0.02)
        assert collision["success"], collision
        baked = server.bake_physics(2)
        assert baked["success"], baked
        physics_check = server.validate_physics("V47Cube")
        assert physics_check["success"], physics_check

        scene_audit = server.scene_audit(False)
        assert scene_audit["success"], scene_audit
        material_audit = server.material_audit()
        assert material_audit["success"], material_audit
        texture_audit = server.texture_audit()
        assert texture_audit["success"], texture_audit
        budget = server.performance_budget(100000, 256.0)
        assert budget["success"], budget
        preflight = server.export_preflight("generic-gltf")
        assert preflight["success"], preflight
        floating = server.detect_floating_objects(0.001)
        assert floating["success"], floating
        duplicates = server.detect_duplicate_geometry(0.0001)
        assert duplicates["success"], duplicates
        repair = server.scene_repair_plan()
        assert repair["success"], repair

        rain = server.create_rain_system("V47Rain", 50, 5.0, 1)
        assert rain["success"], rain
        snow = server.create_snow_system("V47Snow", 50, 5.0, 1)
        assert snow["success"], snow
        lightning = server.create_lightning_rig("V47Lightning", [0.0, 0.0, 4.0], 500.0)
        assert lightning["success"], lightning
        wind = server.create_wind_field("V47WindField", 2.0, [1.0, 0.0, 0.0])
        assert wind["success"], wind
        haze = server.create_atmospheric_haze(0.01, [0.8, 0.85, 0.9])
        assert haze["success"], haze
        sunset = server.create_sunset_lighting()
        assert sunset["success"], sunset
        night = server.create_night_lighting(0.5)
        assert night["success"], night
        weather = server.create_weather_scene("rain", 6.0, 1)
        assert weather["success"], weather

        # --- v4.8 character rig, world, material library and FX ---
        clear_scene()
        server.create_humanoid_blockout("V48Char", height=1.75)
        face_rig = server.create_face_rig("V48Char", "V48FaceRig")
        assert face_rig["success"] and face_rig["bone_count"] >= 10, face_rig
        server.create_armature("V48JawRig", [
            {"name": "Root", "head": [0.0, 0.0, 0.0], "tail": [0.0, 0.0, 0.5]}
        ])
        jaw = server.create_jaw_bone(
            "V48JawRig", [0.0, -0.05, 1.6], [0.0, -0.05, 1.5]
        )
        assert jaw["success"], jaw
        eyelids = server.create_eyelid_bones("V48JawRig", 0.065, 0.22)
        assert eyelids["success"], eyelids
        fingers = server.create_finger_rig("V48JawRig", "L", 1.0)
        assert fingers["success"] and fingers["bone_count"] == 15, fingers
        server.create_parametric_part(
            "V48Target", shape="BOX", dimensions=[0.1, 0.1, 0.1],
            location=[0.0, 0.0, 1.0],
        )
        leg_ik = server.create_ik_leg_rig(
            "V48JawRig", [0.1, 0.0, 0.9], [0.1, 0.1, 0.5],
            [0.1, 0.2, 0.1], "V48Target",
        )
        assert leg_ik["success"], leg_ik
        arm_ik = server.create_ik_arm_rig(
            "V48JawRig", [0.2, 0.0, 1.4], [0.4, 0.0, 1.1],
            [0.6, 0.0, 0.8], "V48Target",
        )
        assert arm_ik["success"], arm_ik
        shape_keys = server.add_face_shape_keys("V48Char")
        assert shape_keys["success"] and len(shape_keys["created"]) >= 4, shape_keys
        character_check = server.validate_character_rig("V48FaceRig", "V48Char")
        assert character_check["success"], character_check

        for name, factory, args in (
            ("V48City", server.create_city_block, (20.0, 20.0, 4, 1)),
            ("V48Road", server.create_road, (20.0, 7.0, 2)),
            ("V48Street", server.create_street, (20.0, 8.0, 1)),
            ("V48Bridge", server.create_bridge, (10.0, 6.0, 3.0)),
            ("V48Tunnel", server.create_tunnel, (10.0, 4.0, 3.0)),
            ("V48Tower", server.create_skyscraper, (8.0, 8.0, 30.0, 10)),
            ("V48Park", server.create_park, (15.0, 15.0, 4, 1)),
            ("V48Plaza", server.create_plaza, (15.0, 15.0, 1)),
        ):
            result = factory(name, *args)
            assert result["success"] and bpy.data.objects.get(name), result

        for name, factory in (
            ("V48Marble", server.create_marble_material),
            ("V48Brick", server.create_brick_material),
            ("V48Asphalt", server.create_asphalt_material),
            ("V48GrassMat", server.create_grass_material),
            ("V48SandMat", server.create_sand_material),
            ("V48Rust", server.create_rust_material),
            ("V48Chrome", server.create_chrome_material),
            ("V48Ceramic", server.create_ceramic_material),
        ):
            result = factory(name)
            assert result["success"] and bpy.data.materials.get(name), result

        server.create_parametric_part(
            "V48Emitter", shape="BOX", dimensions=[0.2, 0.2, 0.2],
            location=[0.0, 0.0, 0.1],
        )
        particles = server.create_particle_system("V48Emitter", "V48Particles", 50, 20)
        assert particles["success"], particles
        server.create_parametric_part(
            "V48TrailObj", shape="BOX", dimensions=[0.1, 0.1, 0.1],
            location=[0.0, 0.0, 0.5],
        )
        server.keyframe_object("V48TrailObj", "location", 1, [0.0, 0.0, 0.5])
        server.keyframe_object("V48TrailObj", "location", 10, [1.0, 0.0, 0.5])
        trail = server.create_trail("V48TrailObj", "V48Trail", 10)
        assert trail["success"], trail
        for name, factory, args in (
            ("V48Muzzle", server.create_muzzle_flash, ([0.0, 0.0, 1.0], 200.0)),
            ("V48Explosion", server.create_explosion, ([0.0, 0.0, 1.0], 2.0)),
            ("V48Smoke", server.create_smoke_plume, ([0.0, 0.0, 0.0], 3.0, 1)),
            ("V48Fire", server.create_fire_effect, (0.5, 1.5)),
            ("V48Sparks", server.create_spark_burst, ([0.0, 0.0, 1.0], 50, 1)),
            ("V48Shockwave", server.create_shockwave, ([0.0, 0.0, 1.0], 3.0)),
        ):
            result = factory(name, *args)
            assert result["success"], result
        project = server.project_info()
        assert project["success"] and project["object_count"] > 0, project
        health = server.health_check()
        assert health["success"] and health["passed"], health

        # --- v4.9 high-detail character base, grooming and quality gate ---
        clear_scene()
        head = server.create_anatomical_head("V49Head")
        assert head["success"] and head["polygon_count"] > 500, head
        eye = server.create_eye_assembly("V49Eye")
        assert eye["success"] and len(eye["parts"]) == 5, eye
        skin = server.create_skin_material_pro("V49Skin")
        assert skin["success"] and "ShaderNodeBsdfPrincipled" in skin["nodes"].values(), skin
        dental = server.create_dental_arch("V49Dental", tooth_count=16)
        assert dental["success"] and dental["tooth_count"] == 16, dental
        body = server.create_character_body_pro("V49Body", 1.75, "average", 1)
        assert body["success"] and abs(body["actual_height"] - 1.75) < 0.001, body
        garment = server.create_garment_shell_pro("V49Garment", 0.4, 0.22, 0.55)
        assert garment["success"], garment
        hair = server.create_hair_groom("V49Hair", "V49Head", 100, 0.15, 1)
        assert hair["success"] and hair["spline_count"] == 100, hair
        brows = server.create_eyebrow_groom("V49Brows", "V49Head", 30, 1)
        assert brows["success"] and brows["spline_count"] == 30, brows
        lashes = server.create_eyelash_groom("V49Lashes", "V49Head", 30, 0.014, 1)
        assert lashes["success"] and lashes["spline_count"] == 30, lashes
        rig = server.create_character_rig_pro("V49Body", "V49Rig")
        assert rig["success"] and rig["bone_count"] >= 39, rig
        studio = server.create_character_studio("V49Studio", [0.0, 0.0, 0.9])
        assert studio["success"] and len(studio["lights"]) == 3, studio
        quality = server.character_quality_report(
            "V49Body", "V49Rig", ["V49Hair", "V49Brows", "V49Lashes"]
        )
        assert quality["success"] and quality["aaa_certified"] is False, quality
        assert quality["tier"] == "procedural_high_detail", quality

        # --- animation and rigging primitives ---
        clear_scene()
        anim_cube = make_cube("AnimCube", 0.5)
        anim_cube.location = (0.0, 0.0, 0.0)
        server.keyframe_object("AnimCube", "location", 1, [0.0, 0.0, 0.0])
        second_keyframe = server.keyframe_object(
            "AnimCube", "location", 20, [1.0, 0.0, 0.0]
        )
        if not anim_cube.animation_data or not anim_cube.animation_data.action:
            fail("keyframe_object did not create an action")
        if second_keyframe["keyframe_count"] < 6:
            fail(f"keyframe count is wrong: {second_keyframe}")
        if second_keyframe["frame_range"] != [1.0, 20.0]:
            fail(f"keyframe frame range is wrong: {second_keyframe}")

        rig = server.create_armature("BenchRig", [
            {"name": "Root", "head": [0.0, 0.0, 0.0], "tail": [0.0, 0.0, 0.5]},
            {
                "name": "Tip", "head": [0.0, 0.0, 0.5], "tail": [0.0, 0.0, 1.0],
                "parent": "Root",
            },
        ])
        armature = bpy.data.objects.get("BenchRig")
        if rig["bone_count"] != 2 or not armature:
            fail(f"armature creation failed: {rig}")
        if armature.data.bones["Tip"].parent is None or armature.data.bones["Tip"].parent.name != "Root":
            fail("armature parent relationship is wrong")

        # --- deterministic inspection renders ---
        clear_scene()
        render_cube = make_cube("RenderCube", 1.0)
        render_cube.location = (0.0, 0.0, 0.5)
        original_material = bpy.data.materials.new("OriginalMaterial")
        render_cube.data.materials.append(original_material)
        bpy.context.view_layer.update()
        old_engine = bpy.context.scene.render.engine
        old_camera = bpy.context.scene.camera
        render_dir = tempfile.mkdtemp(prefix="blendermcp_render_")
        os.environ["BLENDER_MCP_OUTPUT_DIR"] = render_dir
        try:
            quad = server.render_multiview_inspection(
                object_names=["RenderCube"],
                resolution=96,
                mode="quad",
                include_overlays=True,
                return_base64=False,
            )
            if not quad.get("success"):
                fail("quad inspection did not succeed")
            if bpy.context.scene.render.engine != old_engine:
                fail("inspection render did not restore the render engine")
            if bpy.context.scene.camera != old_camera:
                fail("inspection render did not restore the scene camera")
            if render_cube.data.materials[0] != original_material:
                fail("inspection render did not restore object materials")
            if not os.path.exists(quad["quad_image_path"]):
                fail("quad inspection image was not written")
            metadata = quad["metadata"]
            if metadata["resolution"] != [96, 96]:
                fail(f"unexpected render resolution: {metadata['resolution']}")
            if len(metadata["views"]) != 4:
                fail(f"unexpected view count: {len(metadata['views'])}")
            if [view["camera_type"] for view in metadata["views"][:3]] != [
                "ORTHO", "ORTHO", "ORTHO"
            ]:
                fail("FRONT/RIGHT/TOP are not orthographic")
            if metadata["views"][3]["camera_type"] != "PERSP":
                fail("ISO view is not perspective")
            if not metadata["render_id"] or not metadata["deterministic_settings"]:
                fail("render metadata is missing deterministic settings")
            if metadata["overlays"]["bounding_box"] is not True:
                fail("bounding box overlay was not requested")

            normals = server.render_multiview_inspection(
                object_names=["RenderCube"], resolution=64, mode="normals",
                return_base64=False,
            )
            if not os.path.exists(normals["quad_image_path"]):
                fail("normals inspection image was not written")

            wireframe = server.render_multiview_inspection(
                object_names=["RenderCube"], resolution=64, mode="wireframe",
                return_base64=False,
            )
            if not os.path.exists(wireframe["quad_image_path"]):
                fail("wireframe inspection image was not written")
        finally:
            os.environ.pop("BLENDER_MCP_OUTPUT_DIR", None)
            shutil.rmtree(render_dir, ignore_errors=True)

    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        fail("exception during headless baseline")

    print("BLENDER_HEADLESS_TEST_OK")


if __name__ == "__main__":
    main()
