"""Procedural vegetation domain pack.

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no Geometry Nodes assets
or external files. All functions run on Blender's main thread, validate
their inputs, are deterministic for a given ``seed`` and return plain
JSON-serializable dictionaries.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

_VALID_TREE_TYPES = ("deciduous", "conifer", "palm")


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _check_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")


def _check_seed(seed):
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")


def _check_positive(label, value, minimum=0.0, maximum=1000.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    value = float(value)
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ValueError(f"{label} must be within [{minimum}, {maximum}]")
    return value


def _check_int(label, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{label} must be within [{minimum}, {maximum}]")
    return value


def _get_or_create_material(name, rgba, roughness=0.8, metallic=0.0):
    """Get or create a simple Principled material (Blender 4.5/5.2 safe)."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    color = list(rgba) if len(rgba) == 4 else list(rgba) + [1.0]
    if "Base Color" in bsdf.inputs:
        bsdf.inputs["Base Color"].default_value = color
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = float(roughness)
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = float(metallic)
    return mat


def _new_faces(bm, before):
    """Faces added to *bm* since *before* (a set snapshot)."""
    bm.faces.ensure_lookup_table()
    current = set(bm.faces)
    return current - before


def _tracked(bm, material_index):
    """Snapshot faces, to be diffed after an operator via _new_faces."""
    bm.faces.ensure_lookup_table()
    return set(bm.faces), material_index


def _tag(bm, snapshot, material_index):
    for face in _new_faces(bm, snapshot):
        face.material_index = material_index


def _create_object(bm, name, materials):
    """Build mesh + object from *bm*, link it, return (object, dims, polys)."""
    _check_name(name)
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    for mat in materials:
        mesh.materials.append(mat)
    collection = bpy.context.collection or bpy.context.scene.collection
    collection.objects.link(obj)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    verts = mesh.vertices
    xs = [v.co.x for v in verts]
    ys = [v.co.y for v in verts]
    zs = [v.co.z for v in verts]
    dims = [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)]
    return obj, dims, len(mesh.polygons)


def _displace_blob(bm, verts, center, rng, jitter):
    for v in verts:
        direction = v.co - center
        if direction.length < 1e-6:
            direction = Vector((0.0, 0.0, 1.0))
        direction.normalize()
        v.co += direction * rng.uniform(-jitter, jitter)


def _add_trunk(bm, rng, trunk_height, trunk_radius, lean=0.0):
    """Tapered trunk cylinder, base at z=0. Returns top-center vector."""
    snap, _ = _tracked(bm, 0)
    geo = bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        segments=9,
        radius1=trunk_radius,
        radius2=trunk_radius * 0.65,
        depth=trunk_height,
    )
    verts = geo["verts"]
    bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, trunk_height / 2.0)), verts=verts)
    if lean:
        bmesh.ops.rotate(
            bm,
            cent=Vector((0.0, 0.0, 0.0)),
            matrix=Matrix.Rotation(lean, 3, "Y"),
            verts=verts,
        )
    _tag(bm, snap, 0)
    top = Vector((0.0, 0.0, trunk_height))
    if lean:
        top.rotate(Matrix.Rotation(lean, 3, "Y"))
    return top


# ---------------------------------------------------------------------------
# public functions
# ---------------------------------------------------------------------------

def create_tree(server, name="Tree", height=4.0, trunk_radius=0.15,
                crown_radius=1.5, tree_type="deciduous", seed=0) -> dict:
    """Create a low-poly procedural tree as a single joined mesh object."""
    _check_name(name)
    _check_seed(seed)
    height = _check_positive("height", height, 0.5, 100.0)
    trunk_radius = _check_positive("trunk_radius", trunk_radius, 0.01, 5.0)
    crown_radius = _check_positive("crown_radius", crown_radius, 0.1, 30.0)
    if trunk_radius * 2.0 >= crown_radius * 2.0 and trunk_radius >= crown_radius:
        raise ValueError("trunk_radius must be smaller than crown_radius")
    if tree_type not in _VALID_TREE_TYPES:
        raise ValueError(f"tree_type must be one of {list(_VALID_TREE_TYPES)}")
    if height < trunk_radius * 4.0:
        raise ValueError("height must be at least 4x trunk_radius")

    rng = random.Random(seed)
    bm = bmesh.new()
    if tree_type == "deciduous":
        bark = _get_or_create_material(name + "_Bark", (0.30, 0.20, 0.12, 1.0), 0.95)
        leaf = _get_or_create_material(name + "_Leaf", (0.16, 0.42, 0.12, 1.0), 0.85)
        materials = [bark, leaf]
        trunk_h = height * 0.55
        top = _add_trunk(bm, rng, trunk_h, trunk_radius)
        for _ in range(4):
            center = top + Vector((
                rng.uniform(-0.5, 0.5) * crown_radius,
                rng.uniform(-0.5, 0.5) * crown_radius,
                rng.uniform(0.0, 0.8) * crown_radius,
            ))
            snap, _ = _tracked(bm, 1)
            geo = bmesh.ops.create_icosphere(
                bm, subdivisions=2, radius=crown_radius * 0.62, matrix=Matrix.Translation(center),
            )
            _displace_blob(bm, geo["verts"], center, rng, crown_radius * 0.12)
            _tag(bm, snap, 1)
    elif tree_type == "conifer":
        bark = _get_or_create_material(name + "_Bark", (0.28, 0.19, 0.12, 1.0), 0.95)
        leaf = _get_or_create_material(name + "_Needle", (0.08, 0.30, 0.10, 1.0), 0.9)
        materials = [bark, leaf]
        trunk_h = height * 0.25
        top = _add_trunk(bm, rng, trunk_h, trunk_radius)
        tiers = 3
        foliage_h = height - trunk_h
        for i in range(tiers):
            frac = i / tiers
            tier_r = crown_radius * (1.0 - 0.55 * frac)
            tier_z = top.z + frac * foliage_h
            tier_depth = foliage_h / tiers * 1.6
            snap, _ = _tracked(bm, 1)
            geo = bmesh.ops.create_cone(
                bm, cap_ends=True, segments=10,
                radius1=tier_r, radius2=tier_r * 0.15, depth=tier_depth,
            )
            bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, tier_z + tier_depth / 2.0)), verts=geo["verts"])
            _tag(bm, snap, 1)
    else:  # palm
        bark = _get_or_create_material(name + "_Bark", (0.42, 0.33, 0.22, 1.0), 0.95)
        leaf = _get_or_create_material(name + "_Frond", (0.15, 0.45, 0.15, 1.0), 0.85)
        fruit = _get_or_create_material(name + "_Fruit", (0.45, 0.32, 0.12, 1.0), 0.7)
        materials = [bark, leaf, fruit]
        trunk_h = height * 0.8
        top = _add_trunk(bm, rng, trunk_h, trunk_radius, lean=0.08)
        fronds = 8
        for i in range(fronds):
            angle = (2.0 * math.pi * i / fronds) + rng.uniform(-0.2, 0.2)
            length = crown_radius * rng.uniform(1.1, 1.4)
            snap, _ = _tracked(bm, 1)
            geo = bmesh.ops.create_cube(bm, size=1.0)
            verts = geo["verts"]
            bmesh.ops.scale(bm, vec=Vector((length, 0.16, 0.04)), verts=verts)
            bmesh.ops.translate(bm, vec=Vector((length / 2.0, 0.0, 0.0)), verts=verts)
            bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)),
                             matrix=Matrix.Rotation(rng.uniform(0.35, 0.6), 3, "Y"), verts=verts)
            bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)),
                             matrix=Matrix.Rotation(angle, 3, "Z"), verts=verts)
            bmesh.ops.translate(bm, vec=top, verts=verts)
            _tag(bm, snap, 1)
        for _ in range(3):
            snap, _ = _tracked(bm, 2)
            off = Vector((rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), -0.12))
            bmesh.ops.create_uvsphere(
                bm, u_segments=10, v_segments=8, radius=trunk_radius * 1.1,
                matrix=Matrix.Translation(top + off),
            )
            _tag(bm, snap, 2)

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "object": obj.name,
        "tree_type": tree_type,
        "height": height,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [m.name for m in materials],
        "seed": seed,
    }


def create_bush(server, name="Bush", radius=0.8, height=0.6, seed=0) -> dict:
    """Create a bush as one joined mesh of displaced blobs, ~radius x radius x height."""
    _check_name(name)
    _check_seed(seed)
    radius = _check_positive("radius", radius, 0.1, 30.0)
    height = _check_positive("height", height, 0.1, 30.0)

    rng = random.Random(seed)
    bm = bmesh.new()
    leaf = _get_or_create_material(name + "_Leaf", (0.14, 0.38, 0.12, 1.0), 0.9)
    blobs = 5
    for _ in range(blobs):
        ang = rng.uniform(0.0, 2.0 * math.pi)
        dist = rng.uniform(0.0, 0.4) * radius
        center = Vector((math.cos(ang) * dist, math.sin(ang) * dist,
                         rng.uniform(0.25, 0.55) * height / max(height, 0.001) * radius * 0.5))
        blob_r = radius * rng.uniform(0.35, 0.5)
        snap, _ = _tracked(bm, 0)
        geo = bmesh.ops.create_icosphere(
            bm, subdivisions=2, radius=blob_r, matrix=Matrix.Translation(center),
        )
        _displace_blob(bm, geo["verts"], center, rng, blob_r * 0.18)
        _tag(bm, snap, 0)
    # Normalize bounds so footprint is ~radius x radius and height ~height.
    bm.verts.ensure_lookup_table()
    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    size_x = max(max(xs) - min(xs), 1e-6)
    size_y = max(max(ys) - min(ys), 1e-6)
    size_z = max(max(zs) - min(zs), 1e-6)
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    bmesh.ops.translate(bm, vec=Vector((-cx, -cy, -min(zs))), verts=list(bm.verts))
    bmesh.ops.scale(bm, vec=Vector((radius / size_x, radius / size_y, height / size_z)),
                    verts=list(bm.verts))

    obj, dims, polys = _create_object(bm, name, [leaf])
    return {
        "success": True,
        "object": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [leaf.name],
        "seed": seed,
    }


def create_grass_patch(server, name="GrassPatch", radius=1.0, blade_count=100,
                       blade_height=0.15, seed=0) -> dict:
    """Create one mesh of tapered grass blades scattered in a disk of *radius*."""
    _check_name(name)
    _check_seed(seed)
    radius = _check_positive("radius", radius, 0.1, 50.0)
    blade_count = _check_int("blade_count", blade_count, 1, 10000)
    blade_height = _check_positive("blade_height", blade_height, 0.01, 5.0)

    rng = random.Random(seed)
    bm = bmesh.new()
    green = _get_or_create_material(name + "_Blade", (0.20, 0.48, 0.12, 1.0), 0.9)
    snap, _ = _tracked(bm, 0)
    for _ in range(blade_count):
        ang = rng.uniform(0.0, 2.0 * math.pi)
        dist = radius * math.sqrt(rng.uniform(0.0, 1.0))
        bx, by = math.cos(ang) * dist, math.sin(ang) * dist
        h = blade_height * rng.uniform(0.7, 1.3)
        w = blade_height * 0.12
        lean_ang = rng.uniform(0.0, 2.0 * math.pi)
        lean = blade_height * rng.uniform(0.05, 0.35)
        dx, dy = math.cos(lean_ang) * lean, math.sin(lean_ang) * lean
        twist = rng.uniform(0.0, math.pi)
        ca, sa = math.cos(twist), math.sin(twist)
        px, py = ca * w / 2.0, sa * w / 2.0
        levels = [(0.0, 1.0), (0.45, 0.75), (0.8, 0.45)]
        ring = []
        for frac, wf in levels:
            ox, oy = dx * frac, dy * frac
            ring.append(bm.verts.new(Vector((bx - px * wf + ox, by - py * wf + oy, frac * h))))
            ring.append(bm.verts.new(Vector((bx + px * wf + ox, by + py * wf + oy, frac * h))))
        tip = bm.verts.new(Vector((bx + dx, by + dy, h)))
        l0, r0, l1, r1, l2, r2 = ring
        for quad in ((l0, r0, r1, l1), (l1, r1, r2, l2)):
            try:
                bm.faces.new(list(quad))
            except ValueError:
                pass
        try:
            bm.faces.new([l2, r2, tip])
        except ValueError:
            pass
    _tag(bm, snap, 0)

    obj, dims, polys = _create_object(bm, name, [green])
    return {
        "success": True,
        "object": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "blade_count": blade_count,
        "materials": [green.name],
        "seed": seed,
    }


def create_flower_patch(server, name="Flowers", radius=1.0, count=20, seed=0) -> dict:
    """Create one joined mesh of stemmed flowers with colored petals."""
    _check_name(name)
    _check_seed(seed)
    radius = _check_positive("radius", radius, 0.1, 50.0)
    count = _check_int("count", count, 1, 2000)

    rng = random.Random(seed)
    bm = bmesh.new()
    palette = [(0.85, 0.20, 0.30, 1.0), (0.90, 0.55, 0.15, 1.0),
               (0.75, 0.25, 0.65, 1.0), (0.90, 0.85, 0.20, 1.0)]
    petal_color = palette[seed % len(palette)]
    stem_mat = _get_or_create_material(name + "_Stem", (0.12, 0.40, 0.12, 1.0), 0.9)
    petal_mat = _get_or_create_material(name + "_Petal", petal_color, 0.7)
    center_mat = _get_or_create_material(name + "_Center", (0.95, 0.80, 0.10, 1.0), 0.6)
    materials = [stem_mat, petal_mat, center_mat]

    for _ in range(count):
        ang = rng.uniform(0.0, 2.0 * math.pi)
        dist = radius * math.sqrt(rng.uniform(0.0, 1.0))
        base = Vector((math.cos(ang) * dist, math.sin(ang) * dist, 0.0))
        stem_h = rng.uniform(0.15, 0.30)
        # Stem.
        snap, _ = _tracked(bm, 0)
        geo = bmesh.ops.create_cone(
            bm, cap_ends=True, segments=5,
            radius1=0.010, radius2=0.006, depth=stem_h,
        )
        bmesh.ops.translate(bm, vec=base + Vector((0.0, 0.0, stem_h / 2.0)), verts=geo["verts"])
        _tag(bm, snap, 0)
        head = base + Vector((0.0, 0.0, stem_h))
        # Center disk.
        snap, _ = _tracked(bm, 2)
        bmesh.ops.create_uvsphere(
            bm, u_segments=8, v_segments=6, radius=0.022,
            matrix=Matrix.Translation(head),
        )
        _tag(bm, snap, 2)
        # Petal ring.
        petals = 6
        for i in range(petals):
            pang = 2.0 * math.pi * i / petals + rng.uniform(-0.1, 0.1)
            snap, _ = _tracked(bm, 1)
            geo = bmesh.ops.create_uvsphere(
                bm, u_segments=8, v_segments=6, radius=0.035,
            )
            verts = geo["verts"]
            bmesh.ops.scale(bm, vec=Vector((1.0, 0.55, 0.30)), verts=verts)
            bmesh.ops.translate(bm, vec=Vector((0.055, 0.0, 0.0)), verts=verts)
            bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)),
                             matrix=Matrix.Rotation(rng.uniform(-0.15, 0.25), 3, "Y"), verts=verts)
            bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)),
                             matrix=Matrix.Rotation(pang, 3, "Z"), verts=verts)
            bmesh.ops.translate(bm, vec=head, verts=verts)
            _tag(bm, snap, 1)

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "object": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "flower_count": count,
        "materials": [m.name for m in materials],
        "seed": seed,
    }
