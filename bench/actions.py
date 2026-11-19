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
