"""Extra architecture domain pack.

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no external assets.
Every function builds ONE joined mesh object grounded at Z=0, assigns
sensible Principled materials per part, and returns a JSON-serializable
dict. Blender 4.5 / 5.2 compatible.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _check_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")


def _check_positive(label, value, minimum, maximum):
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


def _get_or_create_material(name, rgba, roughness=0.8, metallic=0.0,
                            transmission=0.0, emission=None):
    """Get or create a Principled material (Blender 4.5/5.2 safe)."""
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
    if transmission:
        sock = bsdf.inputs.get("Transmission Weight",
                               bsdf.inputs.get("Transmission"))
        if sock is not None:
            sock.default_value = float(transmission)
    if emission is not None:
        sock = bsdf.inputs.get("Emission Color")
        if sock is not None:
            sock.default_value = list(emission)
        strength = bsdf.inputs.get("Emission Strength")
        if strength is not None:
            strength.default_value = 3.0
    return mat


def _box(bm, size, center, material_index):
    """Append an axis-aligned box of *size* (sx, sy, sz) at *center*."""
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_cube(bm, size=1.0)
    verts = geo["verts"]
    bmesh.ops.scale(bm, vec=Vector((size[0], size[1], size[2])), verts=verts)
    bmesh.ops.translate(bm, vec=Vector((center[0], center[1], center[2])), verts=verts)
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - before:
        face.material_index = material_index


def _cylinder(bm, radius, depth, center, segments, material_index, axis="Z"):
    """Append a capped cylinder of *radius*/*depth* at *center*.

    *axis* is the cylinder axis: ``"X"``, ``"Y"`` or ``"Z"``.
    """
    if axis not in ("X", "Y", "Z"):
        raise ValueError("axis must be one of 'X', 'Y', 'Z'")
    if isinstance(segments, bool) or not isinstance(segments, int) or segments < 3:
        raise ValueError("segments must be an integer >= 3")
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segments,
        radius1=radius, radius2=radius, depth=depth,
    )
    verts = geo["verts"]
    if axis == "X":
        bmesh.ops.rotate(bm, cent=(0.0, 0.0, 0.0),
                         matrix=Matrix.Rotation(math.radians(90.0), 3, "Y"),
                         verts=verts)
    elif axis == "Y":
        bmesh.ops.rotate(bm, cent=(0.0, 0.0, 0.0),
                         matrix=Matrix.Rotation(math.radians(90.0), 3, "X"),
                         verts=verts)
    bmesh.ops.translate(
        bm, vec=Vector((center[0], center[1], center[2])), verts=verts)
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - before:
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


def _mats(base, defs):
    return [_get_or_create_material(f"{base}_{label}", rgba, rough, metal,
                                    trans, emis)
            for label, rgba, rough, metal, trans, emis in defs]


def _result(obj, dims, polys, materials, **extra):
    out = {
        "success": True,
        "object": obj.name,
        "name": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [m.name for m in materials],
    }
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# public functions
# ---------------------------------------------------------------------------

def create_bathroom_set(server, name="Bathroom", width=2.4,
                        depth=2.0) -> dict:
    """Create a bathroom set: bathtub + toilet + pedestal sink, grounded."""
    _ = server
    _check_name(name)
    width = _check_positive("width", width, 1.5, 10.0)
    depth = _check_positive("depth", depth, 1.5, 10.0)

    bm = bmesh.new()
    ceramic, chrome, water = _mats(name, [
        ("Ceramic", (0.92, 0.92, 0.90, 1.0), 0.25, 0.0, 0.0, None),
        ("Chrome", (0.75, 0.76, 0.78, 1.0), 0.25, 0.9, 0.0, None),
        ("Water", (0.10, 0.35, 0.50, 1.0), 0.1, 0.0, 0.6, None),
    ])

    # Bathtub on the left: bottom slab + four rim walls + water sheet.
    tub_w = min(0.85, width * 0.35)
    tub_l = min(depth * 0.75, depth - 0.3)
    tub_h = 0.56
    wall_t = 0.07
    tx = -width / 2.0 + 0.05 + tub_w / 2.0
    _box(bm, (tub_w, tub_l, 0.07), (tx, 0.0, 0.035), 0)
    rim_h = tub_h - 0.07
    rz = 0.07 + rim_h / 2.0
    _box(bm, (tub_w, wall_t, rim_h), (tx, tub_l / 2.0 - wall_t / 2.0, rz), 0)
    _box(bm, (tub_w, wall_t, rim_h), (tx, -tub_l / 2.0 + wall_t / 2.0, rz), 0)
    _box(bm, (wall_t, tub_l - 2.0 * wall_t, rim_h),
         (tx - tub_w / 2.0 + wall_t / 2.0, 0.0, rz), 0)
    _box(bm, (wall_t, tub_l - 2.0 * wall_t, rim_h),
         (tx + tub_w / 2.0 - wall_t / 2.0, 0.0, rz), 0)
    _box(bm, (tub_w - 2.0 * wall_t, tub_l - 2.0 * wall_t, 0.03),
         (tx, 0.0, tub_h - 0.13), 2)

    # Toilet on the right-back: bowl pedestal + seat ring + tank.
    tcx = width / 2.0 - 0.32
    tcy = -depth / 2.0 + 0.48
    _box(bm, (0.38, 0.50, 0.38), (tcx, tcy, 0.19), 0)
    _cylinder(bm, 0.21, 0.06, (tcx, tcy + 0.02, 0.41), 24, 0)
    _box(bm, (0.44, 0.16, 0.50), (tcx, tcy - 0.31, 0.55), 0)
    _box(bm, (0.10, 0.04, 0.03), (tcx, tcy - 0.31, 0.82), 1)

    # Pedestal sink on the right-front: pedestal + round basin + faucet.
    scx = width / 2.0 - 0.32
    scy = depth / 2.0 - 0.38
    _box(bm, (0.18, 0.18, 0.55), (scx, scy, 0.275), 0)
    _cylinder(bm, 0.26, 0.13, (scx, scy, 0.615), 24, 0)
    _box(bm, (0.05, 0.05, 0.22), (scx, scy - 0.24, 0.75), 1)
    _box(bm, (0.05, 0.16, 0.04), (scx, scy - 0.17, 0.85), 1)

    obj, dims, polys = _create_object(bm, name, [ceramic, chrome, water])
    return _result(obj, dims, polys, [ceramic, chrome, water],
                   width=width, depth=depth,
                   fixtures=["bathtub", "toilet", "sink"])


def create_kitchen_island(server, name="KitchenIsland", width=2.0,
                          depth=1.0, height=0.9) -> dict:
    """Create a freestanding kitchen island: body + doors/drawers + top."""
    _ = server
    _check_name(name)
    width = _check_positive("width", width, 0.6, 6.0)
    depth = _check_positive("depth", depth, 0.5, 3.0)
    height = _check_positive("height", height, 0.5, 1.5)
    counter_t = 0.05
    if counter_t >= height:
        raise ValueError("height must be larger than the 0.05m countertop")

    bm = bmesh.new()
    cabinet, door, counter, steel = _mats(name, [
        ("Cabinet", (0.72, 0.68, 0.62, 1.0), 0.6, 0.0, 0.0, None),
        ("Door", (0.52, 0.46, 0.40, 1.0), 0.55, 0.0, 0.0, None),
        ("Counter", (0.85, 0.84, 0.82, 1.0), 0.3, 0.0, 0.0, None),
        ("Steel", (0.70, 0.71, 0.73, 1.0), 0.3, 0.9, 0.0, None),
    ])
    body_h = height - counter_t
    kick_h = min(0.10, body_h * 0.15)
    # Carcass with toe-kick recessed on both long faces.
    _box(bm, (width, depth - 0.12, body_h - kick_h),
         (0.0, 0.0, kick_h + (body_h - kick_h) / 2.0), 0)
    _box(bm, (width - 0.06, depth - 0.18, kick_h),
         (0.0, 0.0, kick_h / 2.0), 0)
    # Door/drawer fronts on both faces (+Y and -Y).
    n = max(1, min(6, int(round(width / 0.6))))
    door_w = width / n
    gap = min(0.015, door_w * 0.05)
    drawer_h = min(0.18, (body_h - kick_h) * 0.25)
    below_h = body_h - kick_h - drawer_h - 0.02
    if below_h < 0.15:
        raise ValueError("height must allow drawers plus 0.15m doors")
    for face in (1.0, -1.0):
        fy = face * ((depth - 0.12) / 2.0 + 0.01)
        for i in range(n):
            cx = -width / 2.0 + door_w * (i + 0.5)
            _box(bm, (door_w - gap, 0.02, drawer_h),
                 (cx, fy, body_h - drawer_h / 2.0), 1)
            _box(bm, (min(0.16, door_w * 0.4), 0.025, 0.025),
                 (cx, fy + face * 0.022,
                  body_h - 0.05), 3)
            _box(bm, (door_w - gap, 0.02, below_h),
                 (cx, fy, kick_h + below_h / 2.0), 1)
            hx = cx + (door_w - gap) / 2.0 - 0.06
            _box(bm, (0.025, 0.025, 0.18),
                 (hx, fy + face * 0.022, kick_h + below_h - 0.15), 3)
    # Countertop with overhang on all sides.
    _box(bm, (width + 0.06, depth + 0.06, counter_t),
         (0.0, 0.0, body_h + counter_t / 2.0), 2)

    obj, dims, polys = _create_object(bm, name, [cabinet, door, counter, steel])
    return _result(obj, dims, polys, [cabinet, door, counter, steel],
                   width=width, depth=depth, height=height,
                   section_count=n)


def create_fireplace(server, name="Fireplace", width=1.6,
                     height=1.2, depth=0.4) -> dict:
    """Create a fireplace: stone surround + mantel + firebox with logs."""
    _ = server
    _check_name(name)
    width = _check_positive("width", width, 0.8, 5.0)
    height = _check_positive("height", height, 0.6, 3.0)
    depth = _check_positive("depth", depth, 0.3, 1.5)

    bm = bmesh.new()
    stone, wood, char, log, ember = _mats(name, [
        ("Stone", (0.55, 0.53, 0.50, 1.0), 0.9, 0.0, 0.0, None),
        ("Wood", (0.40, 0.26, 0.13, 1.0), 0.7, 0.0, 0.0, None),
        ("Charcoal", (0.08, 0.07, 0.07, 1.0), 0.95, 0.0, 0.0, None),
        ("Log", (0.30, 0.18, 0.09, 1.0), 0.9, 0.0, 0.0, None),
        ("Ember", (0.90, 0.30, 0.05, 1.0), 0.8, 0.0, 0.0,
         (1.0, 0.35, 0.05, 1.0)),
    ])
    opening_w = width * 0.55
    opening_h = height * 0.55
    pillar_w = (width - opening_w) / 2.0
    # Side pillars + lintel above the opening.
    for s in (-1.0, 1.0):
        _box(bm, (pillar_w, depth, height),
             (s * (opening_w / 2.0 + pillar_w / 2.0), 0.0, height / 2.0), 0)
    _box(bm, (width, depth, height - opening_h),
         (0.0, 0.0, opening_h + (height - opening_h) / 2.0), 0)
    # Firebox back panel + floor.
    _box(bm, (opening_w, 0.06, opening_h),
         (0.0, -depth / 2.0 + 0.03, opening_h / 2.0), 2)
    _box(bm, (opening_w, depth, 0.05),
         (0.0, 0.0, 0.025), 2)
    # Hearth slab extending forward (+Y).
    _box(bm, (width * 0.9, 0.5, 0.06),
         (0.0, depth / 2.0 + 0.2, 0.03), 0)
    # Logs: three horizontal cylinders + glowing ember blocks.
    log_len = opening_w * 0.7
    _cylinder(bm, 0.05, log_len, (0.0, 0.0, 0.13), 12, 3, axis="X")
    _cylinder(bm, 0.045, log_len * 0.85, (0.05, 0.06, 0.21), 12, 3, axis="X")
    _cylinder(bm, 0.04, log_len * 0.7, (-0.06, -0.05, 0.29), 10, 3, axis="X")
    for i, ex in enumerate((-0.15, 0.0, 0.15, 0.07)):
        _box(bm, (0.09, 0.09, 0.05),
             (ex, 0.02 * (i % 2), 0.075), 4)
    # Wooden mantel shelf capping the surround.
    _box(bm, (width + 0.15, depth + 0.12, 0.07),
         (0.0, 0.02, height + 0.035), 1)

    obj, dims, polys = _create_object(bm, name, [stone, wood, char, log, ember])
    return _result(obj, dims, polys, [stone, wood, char, log, ember],
                   width=width, height=height, depth=depth,
                   opening_width=opening_w, opening_height=opening_h)


def create_balcony(server, name="Balcony", width=3.0, depth=1.2,
                   height=1.0) -> dict:
    """Create a balcony: floor slab + posts/rails + side knee walls."""
    _ = server
    _check_name(name)
    width = _check_positive("width", width, 1.0, 10.0)
    depth = _check_positive("depth", depth, 0.6, 5.0)
    height = _check_positive("height", height, 0.5, 1.5)

    bm = bmesh.new()
    concrete, metal, wood = _mats(name, [
        ("Concrete", (0.60, 0.59, 0.57, 1.0), 0.9, 0.0, 0.0, None),
        ("Metal", (0.30, 0.31, 0.33, 1.0), 0.4, 0.8, 0.0, None),
        ("Wood", (0.45, 0.30, 0.16, 1.0), 0.7, 0.0, 0.0, None),
    ])
    slab_t = 0.12
    post_s = 0.06
    # Floor slab, top at slab_t.
    _box(bm, (width, depth, slab_t), (0.0, 0.0, slab_t / 2.0), 0)
    front_y = depth / 2.0 - post_s / 2.0
    # Front railing: full-height posts + top/mid rails.
    n_front = max(2, min(9, int(round(width / 0.9)) + 1))
    for i in range(n_front):
        px = -width / 2.0 + post_s / 2.0 + i * (width - post_s) / (n_front - 1)
        _box(bm, (post_s, post_s, height),
             (px, front_y, slab_t + height / 2.0), 1)
    _box(bm, (width, 0.07, 0.07),
         (0.0, front_y, slab_t + height - 0.035), 2)
    _box(bm, (width, 0.05, 0.05),
         (0.0, front_y, slab_t + height / 2.0), 1)
    # Sides: solid knee wall + interior short posts + top rail.
    # (Corners already have full-height front posts; only add interior
    # side posts to avoid coincident duplicate geometry.)
    knee_h = height * 0.35
    n_side = max(2, min(5, int(round(depth / 0.9)) + 1))
    for s in (-1.0, 1.0):
        sx = s * (width / 2.0 - 0.03)
        _box(bm, (0.06, depth, knee_h),
             (sx, 0.0, slab_t + knee_h / 2.0), 0)
        for i in range(1, n_side):
            py = -front_y + i * (2.0 * front_y) / n_side
            _box(bm, (post_s, post_s, height - knee_h),
                 (sx, py, slab_t + knee_h + (height - knee_h) / 2.0), 1)
        _box(bm, (0.07, depth, 0.07),
             (sx, 0.0, slab_t + height - 0.035), 2)

    obj, dims, polys = _create_object(bm, name, [concrete, metal, wood])
    return _result(obj, dims, polys, [concrete, metal, wood],
                   width=width, depth=depth, railing_height=height,
                   slab_thickness=slab_t, front_post_count=n_front)


def create_fence(server, name="Fence", length=6.0, height=1.2,
                 post_count=8) -> dict:
    """Create a fence: posts with caps + two rails along its length."""
    _ = server
    _check_name(name)
    length = _check_positive("length", length, 1.0, 60.0)
    height = _check_positive("height", height, 0.4, 2.5)
    post_count = _check_int("post_count", post_count, 2, 60)
    spacing = length / (post_count - 1)
    if spacing < 0.25:
        raise ValueError(
            f"post_count ({post_count}) gives spacing ({spacing:.3f}m) "
            f"below 0.25m for length ({length})"
        )

    bm = bmesh.new()
    (wood,) = _mats(name, [
        ("Wood", (0.48, 0.34, 0.19, 1.0), 0.8, 0.0, 0.0, None),
    ])
    post_s = 0.12
    # Posts with cap blocks.
    for i in range(post_count):
        px = -length / 2.0 + i * spacing
        _box(bm, (post_s, post_s, height + 0.05),
             (px, 0.0, (height + 0.05) / 2.0), 0)
        _box(bm, (post_s + 0.05, post_s + 0.05, 0.04),
             (px, 0.0, height + 0.05 + 0.02), 0)
    # Two horizontal rails spanning the full length.
    _box(bm, (length, 0.05, 0.09), (0.0, 0.0, height - 0.15), 0)
    _box(bm, (length, 0.05, 0.09), (0.0, 0.0, 0.30), 0)

    obj, dims, polys = _create_object(bm, name, [wood])
    return _result(obj, dims, polys, [wood],
                   length=length, height=height, post_count=post_count,
                   post_spacing=spacing)


def create_gate(server, name="Gate", width=3.0, height=2.0) -> dict:
    """Create a double gate: two barred leaves + frame posts."""
    _ = server
    _check_name(name)
    width = _check_positive("width", width, 0.8, 10.0)
    height = _check_positive("height", height, 0.8, 3.0)

    bm = bmesh.new()
    metal, stone = _mats(name, [
        ("Metal", (0.22, 0.23, 0.25, 1.0), 0.45, 0.85, 0.0, None),
        ("Stone", (0.55, 0.53, 0.50, 1.0), 0.9, 0.0, 0.0, None),
    ])
    post_s = 0.18
    post_h = height + 0.15
    for s in (-1.0, 1.0):
        _box(bm, (post_s, post_s, post_h),
             (s * (width / 2.0 + post_s / 2.0 + 0.02), 0.0, post_h / 2.0), 1)
    # Two leaves; each leaf: side stiles + top/bottom rails + bars.
    leaf_w = width / 2.0 - 0.05
    bottom_gap = 0.12
    leaf_h = height - bottom_gap
    lz = bottom_gap + leaf_h / 2.0
    bars_per_leaf = 4
    for s in (-1.0, 1.0):
        cx = s * (width / 4.0)
        for ex in (-leaf_w / 2.0 + 0.03, leaf_w / 2.0 - 0.03):
            _box(bm, (0.06, 0.06, leaf_h), (cx + ex, 0.0, lz), 0)
        _box(bm, (leaf_w, 0.06, 0.08),
             (cx, 0.0, bottom_gap + leaf_h - 0.04), 0)
        _box(bm, (leaf_w, 0.06, 0.08), (cx, 0.0, bottom_gap + 0.04), 0)
        for i in range(bars_per_leaf):
            bx = cx - leaf_w / 2.0 + (i + 1) * leaf_w / (bars_per_leaf + 1)
            _box(bm, (0.04, 0.04, leaf_h - 0.16), (bx, 0.0, lz), 0)

    obj, dims, polys = _create_object(bm, name, [metal, stone])
    return _result(obj, dims, polys, [metal, stone],
                   width=width, height=height,
                   leaf_width=leaf_w, bars_per_leaf=bars_per_leaf)


def create_garage(server, name="Garage", width=6.0, depth=6.0,
                  height=2.8) -> dict:
    """Create a garage: floor + walls with a door opening + roof slab."""
    _ = server
    _check_name(name)
    width = _check_positive("width", width, 2.5, 15.0)
    depth = _check_positive("depth", depth, 2.5, 15.0)
    height = _check_positive("height", height, 2.0, 5.0)

    bm = bmesh.new()
    wall, floor, roof = _mats(name, [
        ("Wall", (0.80, 0.78, 0.72, 1.0), 0.9, 0.0, 0.0, None),
        ("Floor", (0.45, 0.44, 0.43, 1.0), 0.95, 0.0, 0.0, None),
        ("Roof", (0.30, 0.30, 0.32, 1.0), 0.7, 0.0, 0.0, None),
    ])
    t = 0.15
    slab_t = 0.12
    roof_t = 0.12
    if 2.0 * t >= min(width, depth):
        raise ValueError(
            f"0.15m walls need width/depth above 0.3m "
            f"(got width={width}, depth={depth})"
        )
    door_w = width * 0.7
    door_h = height * 0.8
    if door_w >= width - 2.0 * t:
        raise ValueError(
            f"door opening ({door_w}) must fit within the front wall "
            f"(width={width})"
        )
    hx, hy = width / 2.0, depth / 2.0
    base = slab_t
    top = slab_t + height
    # Floor slab + flat roof slab.
    _box(bm, (width, depth, slab_t), (0.0, 0.0, slab_t / 2.0), 1)
    _box(bm, (width, depth, roof_t), (0.0, 0.0, top + roof_t / 2.0), 2)
    # Back wall (+Y) solid.
    _box(bm, (width, t, height), (0.0, hy - t / 2.0, base + height / 2.0), 0)
    # Side walls solid between front and back.
    for s in (-1.0, 1.0):
        _box(bm, (t, depth - 2.0 * t, height),
             (s * (hx - t / 2.0), 0.0, base + height / 2.0), 0)
    # Front wall (-Y) with a centered door opening + lintel.
    dx = door_w / 2.0
    _box(bm, (hx - dx, t, height),
         (-(dx + hx) / 2.0, -hy + t / 2.0, base + height / 2.0), 0)
    _box(bm, (hx - dx, t, height),
         ((dx + hx) / 2.0, -hy + t / 2.0, base + height / 2.0), 0)
    _box(bm, (door_w, t, height - door_h),
         (0.0, -hy + t / 2.0, base + door_h + (height - door_h) / 2.0), 0)

    obj, dims, polys = _create_object(bm, name, [wall, floor, roof])
    return _result(obj, dims, polys, [wall, floor, roof],
                   width=width, depth=depth, height=height,
                   door_opening={"width": door_w, "height": door_h,
                                 "wall": "front", "wall_axis": "-Y"})


def create_pool(server, name="Pool", width=6.0, depth=3.0,
                water_depth=1.2) -> dict:
    """Create a pool: basin walls + water surface + coping rim."""
    _ = server
    _check_name(name)
    width = _check_positive("width", width, 2.0, 20.0)
    depth = _check_positive("depth", depth, 2.0, 20.0)
    water_depth = _check_positive("water_depth", water_depth, 0.4, 2.5)

    bm = bmesh.new()
    basin, water, coping = _mats(name, [
        ("Basin", (0.65, 0.70, 0.72, 1.0), 0.6, 0.0, 0.0, None),
        ("Water", (0.08, 0.35, 0.55, 1.0), 0.1, 0.0, 0.7, None),
        ("Coping", (0.85, 0.83, 0.78, 1.0), 0.8, 0.0, 0.0, None),
    ])
    freeboard = 0.35
    wall_t = 0.25
    floor_t = 0.15
    wall_h = water_depth + freeboard
    # Basin floor + four walls (raised basin, water contained inside).
    _box(bm, (width + 2.0 * wall_t, depth + 2.0 * wall_t, floor_t),
         (0.0, 0.0, floor_t / 2.0), 0)
    for s in (-1.0, 1.0):
        _box(bm, (width + 2.0 * wall_t, wall_t, wall_h),
             (0.0, s * (depth / 2.0 + wall_t / 2.0),
              floor_t + wall_h / 2.0), 0)
        _box(bm, (wall_t, depth, wall_h),
             (s * (width / 2.0 + wall_t / 2.0), 0.0,
              floor_t + wall_h / 2.0), 0)
    # Water surface: thin slab with its top exactly at water_depth.
    _box(bm, (width - 0.02, depth - 0.02, 0.04),
         (0.0, 0.0, floor_t + water_depth - 0.02), 1)
    # Coping rim overhanging the walls.
    rim_w = wall_t + 0.15
    rim_t = 0.08
    rz = floor_t + wall_h + rim_t / 2.0
    for s in (-1.0, 1.0):
        _box(bm, (width + 2.0 * wall_t + 0.1, rim_w, rim_t),
             (0.0, s * (depth / 2.0 + wall_t / 2.0), rz), 2)
        _box(bm, (rim_w, depth, rim_t),
             (s * (width / 2.0 + wall_t / 2.0), 0.0, rz), 2)

    obj, dims, polys = _create_object(bm, name, [basin, water, coping])
    return _result(obj, dims, polys, [basin, water, coping],
                   width=width, depth=depth, water_depth=water_depth,
                   wall_height=wall_h,
                   water_level=floor_t + water_depth)
