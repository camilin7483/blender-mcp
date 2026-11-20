"""Scene QA, material/texture audits and export readiness checks.

Runs on Blender's main thread. Uses only ``bpy``, ``bmesh``,
``mathutils`` and the standard library. All functions are read-only:
they never create, modify or delete data. Compatible with Blender 4.5
LTS and 5.2 LTS.
"""

import math
import os

import bmesh
import bpy
from mathutils import Vector

_OVERSIZE_LIMIT = 2048
_NON_MANIFOLD_SAMPLE_LIMIT = 50
_DUPLICATE_GROUP_SAMPLE = 20


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_bool(value, label):
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a bool (got {value!r}).")
    return value


def _validate_non_negative_float(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number (got {value!r}).")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite (got {value!r}).")
    if result < 0.0:
        raise ValueError(f"{label} must be >= 0 (got {value!r}).")
    return result


def _validate_positive_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number (got {value!r}).")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite (got {value!r}).")
    if result <= 0.0:
        raise ValueError(f"{label} must be > 0 (got {value!r}).")
    return result


def _validate_max_triangles(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"max_triangles must be a number (got {value!r}).")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"max_triangles must be an integer (got {value!r}).")
    result = int(value)
    if result < 1:
        raise ValueError(f"max_triangles must be >= 1 (got {value!r}).")
    return result


def _validate_profile(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"profile must be a non-empty string (got {value!r}).")
    return value.strip().lower()


# ---------------------------------------------------------------------------
# Internal inspection helpers (read-only)
# ---------------------------------------------------------------------------

def _object_counts():
    counts = {}
    for obj in bpy.data.objects:
        key = str(getattr(obj, "type", "UNKNOWN"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _is_hidden(obj):
    try:
        if bool(getattr(obj, "hide_viewport", False)):
            return True
    except (AttributeError, TypeError):
        pass
    try:
        if bool(getattr(obj, "hide_render", False)):
            return True
    except (AttributeError, TypeError):
        pass
    try:
        if bool(obj.hide_get()):
            return True
    except (AttributeError, RuntimeError, TypeError):
        pass
    return False


def _world_corners(obj):
    try:
        bound_box = obj.bound_box
    except (AttributeError, RuntimeError):
        return []
    try:
        matrix = obj.matrix_world
    except (AttributeError, TypeError):
        return []
    corners = []
    for corner in bound_box:
        try:
            corners.append(matrix @ Vector(corner))
        except (ArithmeticError, TypeError, ValueError):
            continue
    return corners


def _world_min_z(obj):
    corners = _world_corners(obj)
    if not corners:
        return None
    return min(float(corner[2]) for corner in corners)


def _local_dimensions(obj):
    try:
        dims = obj.dimensions
        return [round(float(dims[i]), 6) for i in range(3)]
    except (AttributeError, TypeError, ValueError):
        return [0.0, 0.0, 0.0]


def _mesh_stats(mesh):
    try:
        vertices = int(len(mesh.vertices))
    except (AttributeError, TypeError):
        vertices = 0
    triangles = 0
    polygons = 0
    try:
        for poly in mesh.polygons:
            polygons += 1
            loops = len(poly.loop_indices)
            triangles += max(0, loops - 2)
    except (AttributeError, TypeError):
        pass
    return vertices, polygons, triangles


def _non_manifold_edge_count(obj):
    try:
        mesh = obj.data
    except AttributeError:
        return 0
    if mesh is None:
        return 0
    bm = bmesh.new()
    try:
        try:
            bm.from_mesh(mesh)
        except (RuntimeError, TypeError, ValueError):
            return 0
        count = 0
        try:
            edges = list(bm.edges)
        except (AttributeError, ReferenceError):
            return 0
        for edge in edges:
            try:
                if not edge.is_manifold:
                    count += 1
            except (AttributeError, ReferenceError):
                continue
        return count
    finally:
        try:
            bm.free()
        except (AttributeError, RuntimeError):
            pass


def _empty_material_slots(obj):
    if getattr(obj, "type", None) != "MESH":
        return 0
    try:
        slots = list(obj.material_slots)
    except (AttributeError, TypeError):
        return 0
    empty = 0
    for slot in slots:
        try:
            if slot.material is None:
                empty += 1
        except (AttributeError, ReferenceError):
            empty += 1
    return empty


def _material_image_nodes(material):
    results = []
    if not bool(getattr(material, "use_nodes", False)):
        return results
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return results
    try:
        nodes = list(tree.nodes)
    except (AttributeError, TypeError):
        return results
    for node in nodes:
        try:
            if node.type == "TEX_IMAGE":
                results.append(node)
        except (AttributeError, ReferenceError):
            continue
    return results


def _has_principled_bsdf(material):
    if not bool(getattr(material, "use_nodes", False)):
        return False
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return False
    try:
        nodes = list(tree.nodes)
    except (AttributeError, TypeError):
        return False
    for node in nodes:
        try:
            if node.type == "BSDF_PRINCIPLED":
                return True
            if getattr(node, "bl_idname", "") == "ShaderNodeBsdfPrincipled":
                return True
        except (AttributeError, ReferenceError):
            continue
    return False


def _image_details(image):
    try:
        width = int(image.size[0])
    except (AttributeError, TypeError, IndexError):
        width = 0
    try:
        height = int(image.size[1])
    except (AttributeError, TypeError, IndexError):
        height = 0
    try:
        filepath = str(image.filepath or "")
    except (AttributeError, TypeError):
        filepath = ""
    try:
        packed = image.packed_file is not None
    except (AttributeError, TypeError):
        packed = False
    try:
        colorspace = str(image.colorspace_settings.name)
    except (AttributeError, TypeError):
        colorspace = ""
    try:
        users = int(image.users)
    except (AttributeError, TypeError):
        users = 0
    exists = False
    if filepath.strip():
        abs_path = os.path.abspath(
            os.path.expanduser(bpy.path.abspath(filepath)))
        exists = os.path.isfile(abs_path)
    memory_bytes = max(0, width) * max(0, height) * 4
    oversized = max(width, height) > _OVERSIZE_LIMIT
    return {
        "name": image.name,
        "width": width,
        "height": height,
        "filepath": filepath,
        "file_exists": exists,
        "packed": packed,
        "colorspace": colorspace,
        "users": users,
        "oversized": oversized,
        "memory_bytes": memory_bytes,
        "memory_mb": round(memory_bytes / (1024.0 * 1024.0), 6),
    }


def _texture_memory():
    total_bytes = 0
    details = []
    for image in bpy.data.images:
        try:
            info = _image_details(image)
        except (AttributeError, RuntimeError, ReferenceError):
            continue
        details.append(info)
        total_bytes += info["memory_bytes"]
    details.sort(key=lambda entry: entry["name"])
    return details, total_bytes


def _scene_triangle_totals():
    seen_meshes = set()
    total_vertices = 0
    total_polygons = 0
    total_triangles = 0
    mesh_objects = 0
    for obj in bpy.data.objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        mesh = getattr(obj, "data", None)
        if mesh is None:
            continue
        mesh_objects += 1
        if mesh.name in seen_meshes:
            continue
        seen_meshes.add(mesh.name)
        vertices, polygons, triangles = _mesh_stats(mesh)
        total_vertices += vertices
        total_polygons += polygons
        total_triangles += triangles
    return mesh_objects, total_vertices, total_polygons, total_triangles


# ---------------------------------------------------------------------------
# Public QA functions
# ---------------------------------------------------------------------------

def scene_audit(server, include_hidden=False) -> dict:
    """Audit scene objects, orphan data, topology and material slots."""
    _ = server
    include_hidden = _validate_bool(include_hidden, "include_hidden")

    counts = _object_counts()
    object_count = sum(counts.values())

    hidden_objects = sorted(
        obj.name for obj in bpy.data.objects if _is_hidden(obj))

    orphan_meshes = sorted(
        mesh.name for mesh in bpy.data.meshes if int(mesh.users) == 0)
    orphan_materials = sorted(
        mat.name for mat in bpy.data.materials if int(mat.users) == 0)
    orphan_images = sorted(
        img.name for img in bpy.data.images if int(img.users) == 0)

    non_manifold = []
    zero_scale = []
    missing_materials = []
    considered = 0
    for obj in bpy.data.objects:
        if obj.type == "MESH" and not _is_hidden(obj):
            considered += 1
        if obj.type != "MESH":
            continue
        if not include_hidden and _is_hidden(obj):
            continue
        if obj.data is None:
            continue
        try:
            scale = obj.scale
            if (abs(float(scale[0])) <= 1e-9
                    or abs(float(scale[1])) <= 1e-9
                    or abs(float(scale[2])) <= 1e-9):
                zero_scale.append(obj.name)
        except (AttributeError, TypeError, ValueError):
            pass
        bad_edges = _non_manifold_edge_count(obj)
        if bad_edges > 0:
            non_manifold.append({
                "object": obj.name,
                "non_manifold_edges": bad_edges,
            })
        empty = _empty_material_slots(obj)
        if empty > 0:
            missing_materials.append({
                "object": obj.name,
                "empty_slots": empty,
            })

    non_manifold.sort(key=lambda entry: entry["object"])
    zero_scale.sort()
    missing_materials.sort(key=lambda entry: entry["object"])

    findings = []
    if hidden_objects:
        findings.append({
            "check": "hidden_objects",
            "message": f"{len(hidden_objects)} hidden object(s) in the scene.",
            "objects": hidden_objects[:_DUPLICATE_GROUP_SAMPLE],
        })
    if orphan_meshes or orphan_materials or orphan_images:
        findings.append({
            "check": "orphan_data",
            "message": (
                f"{len(orphan_meshes)} orphan mesh(es), "
                f"{len(orphan_materials)} orphan material(s), "
                f"{len(orphan_images)} orphan image(s)."
            ),
            "orphan_meshes": orphan_meshes[:_DUPLICATE_GROUP_SAMPLE],
            "orphan_materials": orphan_materials[:_DUPLICATE_GROUP_SAMPLE],
            "orphan_images": orphan_images[:_DUPLICATE_GROUP_SAMPLE],
        })
    for entry in non_manifold:
        findings.append({
            "check": "non_manifold",
            "message": (
                f"Object '{entry['object']}' has "
                f"{entry['non_manifold_edges']} non-manifold edge(s)."
            ),
            "objects": [entry["object"]],
        })
    if zero_scale:
        findings.append({
            "check": "zero_scale",
            "message": f"{len(zero_scale)} object(s) with a zero scale axis.",
            "objects": zero_scale[:_DUPLICATE_GROUP_SAMPLE],
        })
    for entry in missing_materials:
        findings.append({
            "check": "missing_materials",
            "message": (
                f"Object '{entry['object']}' has "
                f"{entry['empty_slots']} empty material slot(s)."
            ),
            "objects": [entry["object"]],
        })

    return {
        "success": True,
        "object_count": object_count,
        "counts_by_type": counts,
        "meshes_checked": considered,
        "include_hidden": include_hidden,
        "hidden_objects": hidden_objects,
        "hidden_count": len(hidden_objects),
        "orphan_meshes": orphan_meshes,
        "orphan_materials": orphan_materials,
        "orphan_images": orphan_images,
        "orphan_counts": {
            "meshes": len(orphan_meshes),
            "materials": len(orphan_materials),
            "images": len(orphan_images),
        },
        "non_manifold_objects": non_manifold,
        "non_manifold_count": len(non_manifold),
        "zero_scale_objects": zero_scale,
        "zero_scale_count": len(zero_scale),
        "missing_material_objects": missing_materials,
        "missing_material_count": len(missing_materials),
        "issue_count": len(findings),
        "passed": len(findings) == 0,
        "findings": findings,
    }


def material_audit(server) -> dict:
    """Audit materials for node usage, image links and shader types."""
    _ = server

    no_nodes = []
    unused = []
    non_principled = []
    missing_textures = []

    for material in bpy.data.materials:
        try:
            users = int(material.users)
        except (AttributeError, TypeError):
            users = 0
        if users == 0:
            unused.append(material.name)
        has_tree = bool(getattr(material, "use_nodes", False)
                        and getattr(material, "node_tree", None) is not None)
        node_count = 0
        if has_tree:
            try:
                node_count = len(material.node_tree.nodes)
            except (AttributeError, TypeError):
                node_count = 0
        if not has_tree or node_count == 0:
            no_nodes.append(material.name)
            continue
        if not _has_principled_bsdf(material):
            non_principled.append(material.name)
        for node in _material_image_nodes(material):
            try:
                image = node.image
                node_name = node.name
            except (AttributeError, ReferenceError):
                continue
            if image is None:
                missing_textures.append({
                    "material": material.name,
                    "node": node_name,
                    "image": None,
                    "reason": "image slot is empty",
                })
                continue
            try:
                filepath = str(image.filepath or "")
                packed = image.packed_file is not None
            except (AttributeError, TypeError):
                filepath, packed = "", False
            if packed:
                continue
            if not filepath.strip():
                missing_textures.append({
                    "material": material.name,
                    "node": node_name,
                    "image": image.name,
                    "reason": "image has no filepath",
                })
            else:
                abs_path = os.path.abspath(
                    os.path.expanduser(bpy.path.abspath(filepath)))
                if not os.path.isfile(abs_path):
                    missing_textures.append({
                        "material": material.name,
                        "node": node_name,
                        "image": image.name,
                        "reason": f"file not found: '{abs_path}'",
                    })

    no_nodes.sort()
    unused.sort()
    non_principled.sort()
    missing_textures.sort(
        key=lambda entry: (str(entry["material"]), str(entry["node"])))

    issue_count = (len(no_nodes) + len(missing_textures)
                   + len(non_principled))
    return {
        "success": True,
        "material_count": len(bpy.data.materials),
        "no_node_materials": no_nodes,
        "no_node_count": len(no_nodes),
        "unused_materials": unused,
        "unused_count": len(unused),
        "missing_image_textures": missing_textures,
        "missing_image_texture_count": len(missing_textures),
        "non_principled_materials": non_principled,
        "non_principled_count": len(non_principled),
        "issue_count": issue_count,
        "passed": issue_count == 0,
    }


def texture_audit(server) -> dict:
    """Audit images for file links, size, packed state and colorspace."""
    _ = server
    details, total_bytes = _texture_memory()

    missing = sorted(
        info["name"] for info in details
        if not info["packed"] and not info["file_exists"])
    oversized = sorted(info["name"] for info in details if info["oversized"])
    packed = sorted(info["name"] for info in details if info["packed"])
    colorspaces = {}
    for info in details:
        key = info["colorspace"] or "<unknown>"
        colorspaces[key] = colorspaces.get(key, 0) + 1

    return {
        "success": True,
        "image_count": len(details),
        "images": details,
        "missing_filepath_images": missing,
        "missing_filepath_count": len(missing),
        "oversized_images": oversized,
        "oversized_count": len(oversized),
        "oversize_limit": _OVERSIZE_LIMIT,
        "packed_images": packed,
        "packed_count": len(packed),
        "colorspaces": colorspaces,
        "total_memory_bytes": total_bytes,
        "total_memory_mb": round(total_bytes / (1024.0 * 1024.0), 6),
        "issue_count": len(missing) + len(oversized),
        "passed": len(missing) == 0 and len(oversized) == 0,
    }


def performance_budget(server, max_triangles=100000,
                       max_texture_mb=256) -> dict:
    """Check scene totals against triangle and texture-memory budgets."""
    _ = server
    max_triangles = _validate_max_triangles(max_triangles)
    max_texture_mb = _validate_positive_number(max_texture_mb, "max_texture_mb")

    mesh_objects, vertices, polygons, triangles = _scene_triangle_totals()
    _, texture_bytes = _texture_memory()
    texture_mb = round(texture_bytes / (1024.0 * 1024.0), 6)

    failures = []
    if triangles > max_triangles:
        failures.append(
            f"Triangle budget exceeded: {triangles} > {max_triangles}.")
    if texture_mb > max_texture_mb:
        failures.append(
            f"Texture memory budget exceeded: {texture_mb} MB > "
            f"{float(max_texture_mb)} MB.")

    return {
        "success": True,
        "object_count": len(bpy.data.objects),
        "mesh_object_count": mesh_objects,
        "total_vertices": vertices,
        "total_polygons": polygons,
        "total_triangles": triangles,
        "image_count": len(bpy.data.images),
        "texture_memory_bytes": texture_bytes,
        "texture_memory_mb": texture_mb,
        "max_triangles": max_triangles,
        "max_texture_mb": float(max_texture_mb),
        "passed": len(failures) == 0,
        "failures": failures,
    }


def export_preflight(server, profile="generic-gltf") -> dict:
    """Validate meshes, UVs, materials, armatures and actions for export."""
    _ = server
    clean_profile = _validate_profile(profile)

    checks = []

    empty_meshes = []
    for obj in bpy.data.objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        mesh = getattr(obj, "data", None)
        if mesh is None:
            empty_meshes.append(obj.name)
            continue
        try:
            if len(mesh.vertices) == 0 or len(mesh.polygons) == 0:
                empty_meshes.append(obj.name)
        except (AttributeError, TypeError):
            empty_meshes.append(obj.name)
    empty_meshes.sort()
    checks.append({
        "check": "meshes_valid",
        "passed": len(empty_meshes) == 0,
        "message": (
            "All meshes contain geometry." if not empty_meshes
            else f"{len(empty_meshes)} mesh object(s) are empty."
        ),
        "objects": empty_meshes[:_DUPLICATE_GROUP_SAMPLE],
    })

    missing_uvs = []
    for obj in bpy.data.objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        mesh = getattr(obj, "data", None)
        if mesh is None:
            continue
        try:
            if len(mesh.uv_layers) == 0:
                missing_uvs.append(obj.name)
        except (AttributeError, TypeError):
            missing_uvs.append(obj.name)
    missing_uvs.sort()
    uv_required = clean_profile in ("generic-gltf", "gltf", "glb", "unity",
                                    "unreal", "fbx")
    checks.append({
        "check": "uvs_present",
        "passed": len(missing_uvs) == 0 or not uv_required,
        "message": (
            "All meshes define UV layers." if not missing_uvs
            else f"{len(missing_uvs)} mesh object(s) have no UV layers."
        ),
        "objects": missing_uvs[:_DUPLICATE_GROUP_SAMPLE],
    })

    missing_mats = []
    for obj in bpy.data.objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        if _empty_material_slots(obj) > 0:
            missing_mats.append(obj.name)
    missing_mats.sort()
    checks.append({
        "check": "materials_assigned",
        "passed": len(missing_mats) == 0,
        "message": (
            "All material slots reference a material." if not missing_mats
            else f"{len(missing_mats)} object(s) have empty material slots."
        ),
        "objects": missing_mats[:_DUPLICATE_GROUP_SAMPLE],
    })

    bad_armatures = []
    armature_count = 0
    for obj in bpy.data.objects:
        if getattr(obj, "type", None) != "ARMATURE":
            continue
        armature_count += 1
        data = getattr(obj, "data", None)
        try:
            bones = list(data.bones) if data is not None else []
        except (AttributeError, TypeError):
            bones = []
        if not bones:
            bad_armatures.append(obj.name)
    bad_armatures.sort()
    checks.append({
        "check": "armatures_valid",
        "passed": len(bad_armatures) == 0,
        "message": (
            f"{armature_count} armature(s) define bones."
            if not bad_armatures
            else f"{len(bad_armatures)} armature(s) have no bones."
        ),
        "objects": bad_armatures[:_DUPLICATE_GROUP_SAMPLE],
    })

    unused_actions = sorted(
        action.name for action in bpy.data.actions
        if int(getattr(action, "users", 0)) == 0)
    checks.append({
        "check": "actions_valid",
        "passed": len(bpy.data.actions) == 0 or len(unused_actions) == 0,
        "message": (
            f"{len(bpy.data.actions)} action(s) in use."
            if not unused_actions
            else f"{len(unused_actions)} unused action(s) will not export."
        ),
        "objects": unused_actions[:_DUPLICATE_GROUP_SAMPLE],
    })

    if clean_profile in ("generic-gltf", "gltf", "glb"):
        oversized = [
            img.name for img in bpy.data.images
            if max(int(img.size[0]), int(img.size[1])) > 4096
        ]
        oversized.sort()
        checks.append({
            "check": "gltf_texture_size",
            "passed": len(oversized) == 0,
            "message": (
                "All textures fit the glTF 4096px guideline."
                if not oversized
                else f"{len(oversized)} image(s) exceed 4096px."
            ),
            "objects": oversized[:_DUPLICATE_GROUP_SAMPLE],
        })

    passed = all(bool(entry["passed"]) for entry in checks)
    return {
        "success": True,
        "profile": clean_profile,
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": sorted(
            entry["check"] for entry in checks if not entry["passed"]),
        "passed": passed,
    }


def detect_floating_objects(server, tolerance=0.001) -> dict:
    """List objects whose world-space bounding box floats above Z=0."""
    _ = server
    tolerance = _validate_non_negative_float(tolerance, "tolerance")

    floating = []
    checked = 0
    for obj in bpy.data.objects:
        low_z = _world_min_z(obj)
        if low_z is None:
            continue
        checked += 1
        if low_z > tolerance:
            floating.append({
                "object": obj.name,
                "type": str(getattr(obj, "type", "UNKNOWN")),
                "min_z": round(low_z, 6),
            })
    floating.sort(key=lambda entry: entry["object"])

    return {
        "success": True,
        "tolerance": tolerance,
        "checked_count": checked,
        "floating_objects": [entry["object"] for entry in floating],
        "details": floating,
        "count": len(floating),
    }


def detect_duplicate_geometry(server, tolerance=0.0001) -> dict:
    """Group mesh objects sharing identical or near-identical geometry."""
    _ = server
    tolerance = _validate_non_negative_float(tolerance, "tolerance")

    entries = []
    for obj in bpy.data.objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        mesh = getattr(obj, "data", None)
        if mesh is None:
            continue
        vertices, polygons, _ = _mesh_stats(mesh)
        dims = _local_dimensions(obj)
        entries.append({
            "object": obj.name,
            "data": mesh.name,
            "vertices": vertices,
            "polygons": polygons,
            "dimensions": dims,
        })

    groups = []
    by_data = {}
    for entry in entries:
        by_data.setdefault(entry["data"], []).append(entry["object"])
    for data_name, names in by_data.items():
        if len(names) > 1:
            names = sorted(names)
            sample = next(
                entry for entry in entries if entry["object"] == names[0])
            groups.append({
                "objects": names,
                "reason": "shared_mesh_datablock",
                "mesh": data_name,
                "vertices": sample["vertices"],
                "polygons": sample["polygons"],
                "dimensions": sample["dimensions"],
            })

    grouped = {name for group in groups for name in group["objects"]}
    buckets = {}
    for entry in entries:
        if entry["object"] in grouped:
            continue
        dims = entry["dimensions"]
        # Quantize dimensions by tolerance so near-equal sizes bucket
        # together without expensive pairwise comparison.
        if tolerance > 0.0:
            key = (
                entry["vertices"],
                entry["polygons"],
                tuple(int(float(axis) / tolerance) for axis in dims),
            )
        else:
            key = (
                entry["vertices"],
                entry["polygons"],
                tuple(round(float(axis), 6) for axis in dims),
            )
        buckets.setdefault(key, []).append(entry)
    for members in buckets.values():
        if len(members) < 2:
            continue
        names = sorted(member["object"] for member in members)
        first = members[0]
        groups.append({
            "objects": names,
            "reason": "matching_topology_and_size",
            "mesh": None,
            "vertices": first["vertices"],
            "polygons": first["polygons"],
            "dimensions": first["dimensions"],
        })

    groups.sort(key=lambda group: group["objects"])
    duplicates = sum(len(group["objects"]) - 1 for group in groups)
    return {
        "success": True,
        "tolerance": tolerance,
        "checked_count": len(entries),
        "groups": groups,
        "group_count": len(groups),
        "duplicate_object_count": duplicates,
    }


def scene_repair_plan(server) -> dict:
    """Aggregate audit findings into an actionable repair plan (no mutation)."""
    scene = scene_audit(server)
    materials = material_audit(server)
    textures = texture_audit(server)
    performance = performance_budget(server)

    steps = []
    order = 0

    def _add(priority, issue, action, objects=None):
        nonlocal order
        order += 1
        steps.append({
            "order": order,
            "priority": priority,
            "issue": issue,
            "action": action,
            "objects": list(objects or [])[:_DUPLICATE_GROUP_SAMPLE],
            "object_count": len(list(objects or [])),
        })

    if scene["zero_scale_count"]:
        _add("high", f"{scene['zero_scale_count']} object(s) have zero scale.",
             "Reset scale to (1, 1, 1) or delete unused objects.",
             scene["zero_scale_objects"])
    if scene["non_manifold_count"]:
        _add("high",
             f"{scene['non_manifold_count']} object(s) have non-manifold edges.",
             "Enter Edit Mode, select non-manifold geometry and fill, merge "
             "or recalculate normals.",
             [entry["object"] for entry in scene["non_manifold_objects"]])
    if scene["missing_material_count"]:
        _add("high",
             f"{scene['missing_material_count']} object(s) have empty "
             "material slots.",
             "Assign a material to every slot or remove empty slots.",
             [entry["object"] for entry in scene["missing_material_objects"]])
    if materials["missing_image_texture_count"]:
        _add("high",
             f"{materials['missing_image_texture_count']} image node(s) "
             "point at missing files.",
             "Relink image paths, pack images or replace the texture.",
             sorted({entry["material"]
                     for entry in materials["missing_image_textures"]}))
    if not performance["passed"]:
        for failure in performance["failures"]:
            _add("high", failure,
                 "Decimate dense meshes, drop unused subdivision levels and "
                 "downscale oversized textures.")
    if materials["no_node_count"]:
        _add("medium",
             f"{materials['no_node_count']} material(s) do not use nodes.",
             "Enable nodes or convert the material to a Principled BSDF "
             "setup.",
             materials["no_node_materials"])
    if materials["non_principled_count"]:
        _add("medium",
             f"{materials['non_principled_count']} material(s) lack a "
             "Principled BSDF shader.",
             "Rebuild the shader with a Principled BSDF for predictable "
             "export and lighting.",
             materials["non_principled_materials"])
    if textures["oversized_count"]:
        _add("medium",
             f"{textures['oversized_count']} image(s) exceed "
             f"{_OVERSIZE_LIMIT}px.",
             "Downscale hero textures or split tiling detail maps.",
             textures["oversized_images"])
    if textures["missing_filepath_count"]:
        _add("medium",
             f"{textures['missing_filepath_count']} image(s) reference "
             "missing files.",
             "Repack, relink or remove the missing image datablocks.",
             textures["missing_filepath_images"])
    if scene["hidden_count"]:
        _add("low", f"{scene['hidden_count']} hidden object(s) in the scene.",
             "Unhide objects meant for export or delete hidden clutter.",
             scene["hidden_objects"])
    if materials["unused_count"]:
        _add("low",
             f"{materials['unused_count']} unused material(s).",
             "Remove unused materials to shrink the blend file.",
             materials["unused_materials"])
    orphan_total = sum(scene["orphan_counts"].values())
    if orphan_total:
        _add("low", f"{orphan_total} orphan datablock(s).",
             "Run File > Clean Up > Unused Data-Blocks (or purge orphans).")

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    steps.sort(key=lambda step: (priority_rank[step["priority"]], step["order"]))
    for index, step in enumerate(steps, start=1):
        step["order"] = index

    return {
        "success": True,
        "steps": steps,
        "step_count": len(steps),
        "summary": {
            "scene_issues": scene["issue_count"],
            "material_issues": materials["issue_count"],
            "texture_issues": textures["issue_count"],
            "texture_memory_mb": textures["total_memory_mb"],
            "performance_passed": performance["passed"],
            "performance_failures": performance["failures"],
        },
    }
