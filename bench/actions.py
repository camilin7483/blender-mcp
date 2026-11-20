"""BlenderMCP-Bench task actions.

Each function receives the add-on server and the task artifact directory, runs
the task in an already-cleared scene, and returns observed metrics. The runner
compares the result with the task's expected.json.
"""

from __future__ import annotations

import os

import bpy

from blender_mcp import BlenderMCPServer


def _make_cube(server: BlenderMCPServer, name: str = "BenchCube") -> None:
    server.create_parametric_part(
        name=name,
        shape="BOX",
        dimensions=[1.0, 1.0, 1.0],
        location=[0.0, 0.0, 0.0],
        origin="BOTTOM",
    )


def _desk_spec(width_mm: int) -> dict:
    return {
        "name": "BenchDesk",
        "type": "desk",
        "dimensions_mm": {
            "width": width_mm,
            "depth": 800,
            "height": 750,
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


def cube_1000mm(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    _make_cube(server)
    audit = server.audit_3d_model(object_names=["BenchCube"])
    dimensions = audit["dimensions"]["assembly_dimensions"]
    topology = audit["topology"]["BenchCube"]
    return {
        "dimensions_mm": {
            "width": round(dimensions[0] * 1000.0, 3),
            "depth": round(dimensions[1] * 1000.0, 3),
            "height": round(dimensions[2] * 1000.0, 3),
        },
        "topology": {
            "non_manifold_edges": topology["non_manifold_edges"],
            "loose_vertices": topology["loose_vertices"],
        },
        "passed": audit["passed"],
    }


def desk_1600(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    result = server.create_assembly(_desk_spec(1600))
    dimensions = result["audit"]["dimensions"]["assembly_dimensions"]
    return {
        "dimensions_mm": {
            "width": round(dimensions[0] * 1000.0, 3),
            "depth": round(dimensions[1] * 1000.0, 3),
            "height": round(dimensions[2] * 1000.0, 3),
        },
        "components": len(result["components"]),
        "passed": result["passed"],
    }


def desk_update(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    server.create_assembly(_desk_spec(1600))
    updated = server.update_assembly(
        "BenchDesk",
        changes={"dimensions_mm": {"width": 1200}},
    )
    dimensions = updated["audit"]["dimensions"]["assembly_dimensions"]
    duplicates = [
        obj.name
        for obj in bpy.data.objects
        if obj.name.startswith("BenchDesk_") and ".00" in obj.name
    ]
    return {
        "dimensions_mm": {
            "width": round(dimensions[0] * 1000.0, 3),
            "depth": round(dimensions[1] * 1000.0, 3),
            "height": round(dimensions[2] * 1000.0, 3),
        },
        "components": len(updated["components"]),
        "duplicate_components": len(duplicates),
        "passed": updated["passed"],
    }


def clean_topology(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    _make_cube(server)
    audit = server.audit_3d_model(object_names=["BenchCube"])
    topology = audit["topology"]["BenchCube"]
    return {
        "topology": {
            "non_manifold_edges": topology["non_manifold_edges"],
            "loose_vertices": topology["loose_vertices"],
            "zero_area_faces": topology["zero_area_faces"],
        },
        "passed": audit["passed"],
    }


def front_ortho(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    _make_cube(server)
    result = server.render_multiview_inspection(
        object_names=["BenchCube"],
        resolution=128,
        mode="front",
        include_overlays=True,
        return_base64=False,
    )
    view = result["metadata"]["views"][0]
    return {
        "image_exists": os.path.exists(result["quad_image_path"]),
        "camera_type": view["camera_type"],
        "deterministic": result["metadata"]["deterministic_settings"],
        "view_count": len(result["metadata"]["views"]),
    }


def godot_glb(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    _make_cube(server)
    cube = bpy.data.objects["BenchCube"]
    cube.data.uv_layers.new(name="UVMap")
    material = bpy.data.materials.new("BenchMaterial")
    material.use_nodes = True
    cube.data.materials.append(material)
    result = server.export_scene(
        "bench_cube.glb",
        format="GLB",
        profile="godot",
    )
    reimport = result.get("reimport", {})
    return {
        "success": bool(result.get("success")),
        "reimport_checked": bool(reimport.get("checked")),
        "reimport_passed": bool(reimport.get("passed")),
        "file_exists": os.path.exists(result.get("filepath", "")),
    }


def cube_anchors(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    _make_cube(server)
    data = server.list_semantic_anchors("BenchCube")
    anchors = {anchor["name"]: anchor for anchor in data["anchors"]}
    top = anchors["TOP_CENTER"]
    return {
        "top_position": top["position"],
        "anchor_count_min": data["count"],
        "top_source": top["source"],
    }


def desk_constraints(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    result = server.create_assembly(_desk_spec(1600))
    report = result["constraints"]
    return {
        "passed": bool(result["passed"]),
        "constraint_passed": bool(report["passed"]),
        "failed_count": report["failed_count"],
    }


def pbr_material(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    _make_cube(server)
    server.create_material(
        "BenchMetal",
        color=[0.7, 0.7, 0.75, 1.0],
        metallic=0.8,
        roughness=0.2,
    )
    server.assign_material("BenchCube", "BenchMetal")
    material = bpy.data.materials["BenchMetal"]
    principled = material.node_tree.nodes.get("Principled BSDF")
    return {
        "assigned": bool(bpy.data.objects["BenchCube"].data.materials),
        "metallic": round(float(principled.inputs["Metallic"].default_value), 4),
        "roughness": round(float(principled.inputs["Roughness"].default_value), 4),
    }


def geometry_nodes_cube(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    mesh = bpy.data.meshes.new("BenchGNBase")
    obj = bpy.data.objects.new("BenchGN", mesh)
    bpy.context.collection.objects.link(obj)
    group = bpy.data.node_groups.new("BenchGN", "GeometryNodeTree")
    group.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )
    output = group.nodes.new("NodeGroupOutput")
    cube = group.nodes.new("GeometryNodeMeshCube")
    cube.inputs["Size"].default_value = (1.0, 1.0, 1.0)
    group.links.new(cube.outputs["Mesh"], output.inputs["Geometry"])
    modifier = obj.modifiers.new("GN", "NODES")
    modifier.node_group = group
    obj.location = (0.0, 0.0, 0.5)
    bpy.context.view_layer.update()
    audit = server.audit_3d_model(object_names=["BenchGN"])
    dimensions = audit["dimensions"]["assembly_dimensions"]
    return {
        "object_count": audit["object_count_audited"],
        "dimensions_mm": {
            "width": round(dimensions[0] * 1000.0, 3),
            "depth": round(dimensions[1] * 1000.0, 3),
            "height": round(dimensions[2] * 1000.0, 3),
        },
        "passed": audit["passed"],
    }


def repair_nonuniform_scale(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    _make_cube(server)
    cube = bpy.data.objects["BenchCube"]
    cube.scale = (2.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    server.repair_mesh_geometry(object_names=["BenchCube"], apply_scale=True)
    audit = server.audit_3d_model(object_names=["BenchCube"])
    return {
        "scale_passed": audit["requirements"]["normalized_scale"]["passed"],
        "scale": [round(float(value), 4) for value in cube.scale],
    }


def visual_scene(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    server.create_assembly(_desk_spec(1600))
    server.create_parametric_part(
        "BenchMonitor",
        shape="BOX",
        dimensions=[0.4, 0.05, 0.3],
        location=[0.0, 0.0, 0.75],
        origin="BOTTOM",
    )
    names = [
        "BenchDesk_Top",
        "BenchDesk_Leg_FL",
        "BenchDesk_Leg_FR",
        "BenchDesk_Leg_BL",
        "BenchDesk_Leg_BR",
        "BenchMonitor",
    ]
    audit = server.audit_3d_model(object_names=names)
    return {
        "passed": audit["passed"],
        "collisions": len(audit["collisions"]),
        "contacts": len(audit["contacts"]["pairs"]),
    }


def animation_keyframes(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    _make_cube(server)
    server.keyframe_object("BenchCube", "location", 1, [0.0, 0.0, 0.0])
    second = server.keyframe_object("BenchCube", "location", 20, [1.0, 0.0, 0.0])
    action = second.get("action")
    return {
        "has_action": bool(action),
        "keyframe_count": second.get("keyframe_count", 0),
        "frame_start": second.get("frame_range", [0.0, 0.0])[0],
        "frame_end": second.get("frame_range", [0.0, 0.0])[1],
    }


def rigging_armature(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    result = server.create_armature("BenchRig", [
        {"name": "Root", "head": [0.0, 0.0, 0.0], "tail": [0.0, 0.0, 0.5]},
        {
            "name": "Tip", "head": [0.0, 0.0, 0.5], "tail": [0.0, 0.0, 1.0],
            "parent": "Root",
        },
    ])
    armature = bpy.data.objects.get("BenchRig")
    parent_ok = bool(
        armature
        and armature.data.bones["Tip"].parent
        and armature.data.bones["Tip"].parent.name == "Root"
    )
    return {
        "bone_count": result.get("bone_count", 0),
        "parent_ok": parent_ok,
    }




def terrain_landscape(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    terrain = server.create_terrain(
        "BenchTerrain", size=4.0, subdivisions=16, height=0.5, seed=7
    )
    rock = server.create_rock("BenchRock", size=0.3, seed=7)
    tree = server.create_tree("BenchTree", height=2.0, crown_radius=0.5, seed=7)
    scattered = server.scatter_objects("BenchRock", "BenchTerrain", count=6, seed=7)
    return {
        "terrain_dimensions": terrain["dimensions"][:2],
        "height": terrain["dimensions"][2],
        "rock_vertices": rock["vertex_count"],
        "tree_polygons": tree["polygon_count"],
        "scattered": scattered["count"],
    }


def water_surface(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    water = server.create_water_plane("BenchWater", size=3.0, subdivisions=8)
    river = server.create_river("BenchRiver", width=0.5, segments=4)
    pond = server.create_pond("BenchPond", radius=1.0, segments=12)
    return {
        "water_dimensions": water["dimensions"],
        "has_material": bool(water.get("material")),
        "river_faces": river["face_count"],
        "pond_faces": pond["face_count"],
    }


def vegetation_patch(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    tree = server.create_tree("BenchTree", height=2.0, crown_radius=0.5, seed=8)
    bush = server.create_bush("BenchBush", radius=0.3, height=0.3, seed=8)
    grass = server.create_grass_patch(
        "BenchGrass", radius=0.3, blade_count=10, seed=8
    )
    flowers = server.create_flower_patch(
        "BenchFlowers", radius=0.3, count=3, seed=8
    )
    return {
        "tree_polygons": tree["polygon_count"],
        "bush_polygons": bush["polygon_count"],
        "grass_polygons": grass["polygon_count"],
        "flower_polygons": flowers["polygon_count"],
    }


def materials_uv(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    server.create_parametric_part(
        "BenchUV", shape="BOX", dimensions=[0.5, 0.5, 0.5],
        location=[0.0, 0.0, 0.25],
    )
    server.create_procedural_material("BenchProcedural")
    server.assign_material("BenchUV", "BenchProcedural")
    uv = server.smart_uv_unwrap("BenchUV")
    server.pack_uv_islands("BenchUV")
    materials = server.list_materials()
    mesh = bpy.data.objects["BenchUV"].data
    material_data = bpy.data.materials["BenchProcedural"]
    return {
        "uv_layer_present": bool(uv.get("uv_layer")) and len(mesh.uv_layers) > 0,
        "material_assigned": len(mesh.materials) > 0,
        "material_nodes": len(material_data.node_tree.nodes),
        "materials_count": materials["count"],
    }


def physics_rigid(server: BlenderMCPServer, _artifact_dir: str) -> dict:
    _make_cube(server)
    server.add_rigid_body(
        "BenchCube", body_type="ACTIVE", mass=2.0, friction=0.4
    )
    collision = server.add_collision("BenchCube")
    body = bpy.data.objects["BenchCube"].rigid_body
    return {
        "rigid_body_type": body.type if body else None,
        "mass": float(body.mass) if body else 0.0,
        "collision_modifier": bool(
            bpy.data.objects["BenchCube"].modifiers.get("Collision")
        )
        and collision["success"],
        "friction": float(body.friction) if body else 0.0,
    }


def lighting_render(server: BlenderMCPServer, artifact_dir: str) -> dict:
    _make_cube(server)
    server.create_light("BenchLight", energy=50.0)
    server.create_camera(
        "BenchCamera", location=[3.0, -3.0, 2.0], look_at=[0.0, 0.0, 0.5]
    )
    server.setup_world_background(color=[0.05, 0.05, 0.05], strength=1.0)
    render = server.render_still(
        "bench_render.png", camera_name="BenchCamera",
        resolution_x=64, resolution_y=64, samples=4,
    )
    return {
        "file_exists": os.path.exists(render["filepath"]),
        "resolution": render["resolution"],
        "engine_nonempty": bool(render["engine"]),
    }
