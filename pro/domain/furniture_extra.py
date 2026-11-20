"""Extra furniture domain pack.

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no external assets.
Every function builds ONE joined mesh object grounded at Z=0, assigns
Principled materials per part, and returns a JSON-serializable dict.
Blender 4.5 / 5.2 compatible.
"""

import math

import bmesh
import bpy
from mathutils import Vector


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


def _cylinder(bm, radius, depth, center, segments, material_index):
    """Append a capped cylinder (axis Z) of *radius*/*depth* at *center*."""
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segments,
        radius1=radius, radius2=radius, depth=depth,
    )
    verts = geo["verts"]
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
    return [_get_or_create_material(f"{base}_{label}", rgba, rough, metal)
            for label, rgba, rough, metal in defs]


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


def _legs4(bm, ox, oy, leg_s, leg_h, mat_idx):
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            _box(bm, (leg_s, leg_s, leg_h),
                 (sx * ox, sy * oy, leg_h / 2.0), mat_idx)


def _drawer_stack(bm, cx, front_y, top_z, stack_w, stack_h,
                  drawer_count, front_idx, handle_idx):
    """Stacked drawer fronts + bar handles below *top_z*; front plane at *front_y*."""
    gap = 0.012
    front_t = 0.02
    avail = stack_h - gap * (drawer_count + 1)
    dh = avail / drawer_count
    for i in range(drawer_count):
        zc = top_z - gap - dh / 2.0 - i * (dh + gap)
        _box(bm, (stack_w - gap * 2.0, front_t, dh),
             (cx, front_y, zc), front_idx)
        # Horizontal bar handle near the top of each front.
        _box(bm, (min(0.16, stack_w * 0.4), 0.025, 0.025),
             (cx, front_y + front_t / 2.0 + 0.025, zc + dh / 2.0 - 0.05),
             handle_idx)


# ---------------------------------------------------------------------------
# public functions
# ---------------------------------------------------------------------------

def create_desk(server, name="Desk", width=1.6, depth=0.8, height=0.75,
                drawer_count=3) -> dict:
    """Create a desk: top slab + four legs + drawer stack with handles."""
    _check_name(name)
    width = _check_positive("width", width, 0.5, 6.0)
    depth = _check_positive("depth", depth, 0.3, 3.0)
    height = _check_positive("height", height, 0.4, 2.0)
    drawer_count = _check_int("drawer_count", drawer_count, 0, 8)
    top_t = 0.04
    if top_t >= height:
        raise ValueError("height must be larger than the 0.04m top slab")

    bm = bmesh.new()
    wood, front, metal = _mats(name, [
        ("Wood", (0.45, 0.30, 0.16, 1.0), 0.7, 0.0),
        ("DrawerFront", (0.55, 0.40, 0.24, 1.0), 0.65, 0.0),
        ("Metal", (0.35, 0.35, 0.38, 1.0), 0.4, 0.8),
    ])
    leg_s = 0.06
    leg_h = height - top_t
    _box(bm, (width, depth, top_t), (0.0, 0.0, height - top_t / 2.0), 0)
    ox, oy = width / 2.0 - leg_s / 2.0, depth / 2.0 - leg_s / 2.0
    _legs4(bm, ox, oy, leg_s, leg_h, 2)
    if drawer_count > 0:
        stack_w = min(width * 0.32, 0.5)
        stack_h = leg_h - 0.06
        cx = width / 2.0 - leg_s - stack_w / 2.0 - 0.02
        # Drawer carcass hanging under the top.
        _box(bm, (stack_w, depth - 2 * leg_s - 0.04, stack_h),
             (cx, 0.0, leg_h - stack_h / 2.0 - 0.02), 0)
        _drawer_stack(bm, cx, (depth - 2 * leg_s - 0.04) / 2.0 + 0.01,
                      leg_h - 0.02 - 0.012, stack_w - 0.02, stack_h - 0.04,
                      drawer_count, 1, 2)

    obj, dims, polys = _create_object(bm, name, [wood, front, metal])
    return _result(obj, dims, polys, [wood, front, metal],
                   width=width, depth=depth, height=height,
                   drawer_count=drawer_count)


def create_wardrobe(server, name="Wardrobe", width=1.2, depth=0.6,
                    height=2.0, door_count=2) -> dict:
    """Create a wardrobe: carcass + doors with handles + feet."""
    _check_name(name)
    width = _check_positive("width", width, 0.4, 4.0)
    depth = _check_positive("depth", depth, 0.3, 2.0)
    height = _check_positive("height", height, 0.8, 3.0)
    door_count = _check_int("door_count", door_count, 1, 4)
    if width / door_count < 0.2:
        raise ValueError("width must allow at least 0.2m per door")

    bm = bmesh.new()
    wood, door_mat, metal = _mats(name, [
        ("Wood", (0.48, 0.33, 0.18, 1.0), 0.7, 0.0),
        ("Door", (0.56, 0.41, 0.24, 1.0), 0.65, 0.0),
        ("Metal", (0.70, 0.71, 0.73, 1.0), 0.3, 0.9),
    ])
    foot_h = 0.08
    wall_t = 0.03
    body_h = height - foot_h
    # Feet.
    _legs4(bm, width / 2.0 - 0.05, depth / 2.0 - 0.05, 0.06, foot_h, 0)
    bz = foot_h + body_h / 2.0
    # Carcass: sides + top + bottom + back.
    sx = width / 2.0 - wall_t / 2.0
    for s in (-1.0, 1.0):
        _box(bm, (wall_t, depth, body_h), (s * sx, 0.0, bz), 0)
    _box(bm, (width, depth, wall_t),
         (0.0, 0.0, foot_h + wall_t / 2.0), 0)
    _box(bm, (width, depth, wall_t),
         (0.0, 0.0, height - wall_t / 2.0), 0)
    _box(bm, (width - 2 * wall_t, 0.02, body_h - 2 * wall_t),
         (0.0, -depth / 2.0 + 0.01, bz), 0)
    # Doors with gaps + vertical handles on the front face.
    door_w = (width - 0.02) / door_count
    gap = min(0.012, door_w * 0.05)
    for i in range(door_count):
        cx = -width / 2.0 + door_w * (i + 0.5)
        _box(bm, (door_w - gap, 0.02, body_h - 2 * wall_t - 0.02),
             (cx, depth / 2.0 + 0.005, bz), 1)
        hx = cx + (door_w - gap) / 2.0 - 0.05
        if i % 2 == 1:
            hx = cx - (door_w - gap) / 2.0 + 0.05
        _box(bm, (0.025, 0.03, 0.22), (hx, depth / 2.0 + 0.03, bz), 2)

    obj, dims, polys = _create_object(bm, name, [wood, door_mat, metal])
    return _result(obj, dims, polys, [wood, door_mat, metal],
                   width=width, depth=depth, height=height,
                   door_count=door_count)


def create_dresser(server, name="Dresser", width=1.0, depth=0.5,
                   height=0.9, drawer_count=4) -> dict:
    """Create a dresser: carcass + drawer fronts with handles + plinth."""
    _check_name(name)
    width = _check_positive("width", width, 0.4, 4.0)
    depth = _check_positive("depth", depth, 0.3, 2.0)
    height = _check_positive("height", height, 0.4, 2.0)
    drawer_count = _check_int("drawer_count", drawer_count, 1, 8)

    bm = bmesh.new()
    wood, front, metal = _mats(name, [
        ("Wood", (0.50, 0.36, 0.20, 1.0), 0.7, 0.0),
        ("DrawerFront", (0.60, 0.45, 0.27, 1.0), 0.65, 0.0),
        ("Metal", (0.70, 0.71, 0.73, 1.0), 0.3, 0.9),
    ])
    plinth_h = min(0.08, height * 0.15)
    wall_t = 0.025
    # Plinth + carcass.
    _box(bm, (width - 0.06, depth - 0.06, plinth_h),
         (0.0, -0.01, plinth_h / 2.0), 0)
    _box(bm, (width, depth - 0.02, height - plinth_h),
         (0.0, -0.01, plinth_h + (height - plinth_h) / 2.0), 0)
    # Drawer fronts + handles across the full width.
    gap = 0.012
    front_t = 0.02
    front_y = depth / 2.0 - 0.02 + front_t / 2.0
    avail = height - plinth_h - wall_t - gap * (drawer_count + 1)
    if avail <= drawer_count * 0.06:
        raise ValueError("height must allow at least 0.06m per drawer")
    dh = avail / drawer_count
    for i in range(drawer_count):
        zc = height - wall_t / 2.0 - gap - dh / 2.0 - i * (dh + gap)
        _box(bm, (width - 2 * wall_t - gap, front_t, dh),
             (0.0, front_y, zc), 1)
        _box(bm, (min(0.18, width * 0.3), 0.025, 0.025),
             (0.0, front_y + front_t / 2.0 + 0.02, zc + dh / 2.0 - 0.05), 2)

    obj, dims, polys = _create_object(bm, name, [wood, front, metal])
    return _result(obj, dims, polys, [wood, front, metal],
                   width=width, depth=depth, height=height,
                   drawer_count=drawer_count)


def create_nightstand(server, name="Nightstand", width=0.5, depth=0.4,
                      height=0.55) -> dict:
    """Create a nightstand: body + one drawer with handle + four legs."""
    _check_name(name)
    width = _check_positive("width", width, 0.25, 2.0)
    depth = _check_positive("depth", depth, 0.25, 2.0)
    height = _check_positive("height", height, 0.3, 1.5)

    bm = bmesh.new()
    wood, front, metal = _mats(name, [
        ("Wood", (0.46, 0.31, 0.17, 1.0), 0.7, 0.0),
        ("DrawerFront", (0.56, 0.41, 0.24, 1.0), 0.65, 0.0),
        ("Metal", (0.70, 0.71, 0.73, 1.0), 0.3, 0.9),
    ])
    leg_h = min(0.15, height * 0.3)
    leg_s = 0.04
    top_t = 0.03
    _legs4(bm, width / 2.0 - leg_s / 2.0, depth / 2.0 - leg_s / 2.0,
           leg_s, leg_h, 0)
    # Body carcass + top slab.
    body_h = height - leg_h
    _box(bm, (width, depth, body_h - top_t),
         (0.0, 0.0, leg_h + (body_h - top_t) / 2.0), 0)
    _box(bm, (width + 0.02, depth + 0.02, top_t),
         (0.0, 0.0, height - top_t / 2.0), 0)
    # Single drawer front + knob handle.
    front_t = 0.02
    front_y = depth / 2.0 + front_t / 2.0 - 0.005
    dh = min(0.16, body_h - top_t - 0.06)
    zc = height - top_t - 0.03 - dh / 2.0
    _box(bm, (width - 0.06, front_t, dh), (0.0, front_y, zc), 1)
    _cylinder(bm, 0.018, 0.04, (0.0, front_y + front_t / 2.0 + 0.02, zc),
              12, 2)

    obj, dims, polys = _create_object(bm, name, [wood, front, metal])
    return _result(obj, dims, polys, [wood, front, metal],
                   width=width, depth=depth, height=height)


def create_coffee_table(server, name="CoffeeTable", width=1.2, depth=0.6,
                        height=0.42) -> dict:
    """Create a coffee table: top slab + four legs + lower shelf."""
    _check_name(name)
    width = _check_positive("width", width, 0.4, 4.0)
    depth = _check_positive("depth", depth, 0.3, 3.0)
    height = _check_positive("height", height, 0.25, 1.0)
    top_t = 0.04
    if top_t + 0.08 >= height:
        raise ValueError("height must leave room for top slab and lower shelf")

    bm = bmesh.new()
    wood, metal = _mats(name, [
        ("Wood", (0.45, 0.30, 0.16, 1.0), 0.7, 0.0),
        ("Metal", (0.35, 0.35, 0.38, 1.0), 0.4, 0.8),
    ])
    leg_s = 0.05
    leg_h = height - top_t
    _box(bm, (width, depth, top_t), (0.0, 0.0, height - top_t / 2.0), 0)
    ox, oy = width / 2.0 - leg_s / 2.0, depth / 2.0 - leg_s / 2.0
    _legs4(bm, ox, oy, leg_s, leg_h, 1)
    # Lower shelf between the legs.
    shelf_t = 0.025
    _box(bm, (width - 2 * leg_s, depth - 2 * leg_s, shelf_t),
         (0.0, 0.0, 0.08 + shelf_t / 2.0), 0)

    obj, dims, polys = _create_object(bm, name, [wood, metal])
    return _result(obj, dims, polys, [wood, metal],
                   width=width, depth=depth, height=height)


def create_bench(server, name="Bench", width=1.6, depth=0.45,
                 height=0.45) -> dict:
    """Create a backless bench: seat slab + four legs + stretcher bars."""
    _check_name(name)
    width = _check_positive("width", width, 0.4, 5.0)
    depth = _check_positive("depth", depth, 0.2, 2.0)
    height = _check_positive("height", height, 0.25, 1.2)
    seat_t = 0.05
    if seat_t >= height:
        raise ValueError("height must be larger than the 0.05m seat slab")

    bm = bmesh.new()
    wood, fabric = _mats(name, [
        ("Wood", (0.45, 0.30, 0.16, 1.0), 0.7, 0.0),
        ("Fabric", (0.35, 0.42, 0.50, 1.0), 0.95, 0.0),
    ])
    leg_s = 0.06
    leg_h = height - seat_t
    # Seat slab + cushion pad.
    _box(bm, (width, depth, seat_t), (0.0, 0.0, height - seat_t / 2.0), 0)
    _box(bm, (width - 0.08, depth - 0.06, 0.05),
         (0.0, 0.0, height + 0.025), 1)
    ox, oy = width / 2.0 - leg_s / 2.0, depth / 2.0 - leg_s / 2.0
    _legs4(bm, ox, oy, leg_s, leg_h, 0)
    # Long stretcher bars between leg pairs.
    _box(bm, (width - 2 * leg_s, 0.03, 0.05), (0.0, oy, 0.15), 0)
    _box(bm, (width - 2 * leg_s, 0.03, 0.05), (0.0, -oy, 0.15), 0)

    obj, dims, polys = _create_object(bm, name, [wood, fabric])
    return _result(obj, dims, polys, [wood, fabric],
                   width=width, depth=depth, height=height)


def create_bar_stool(server, name="BarStool", seat_radius=0.18,
                     height=0.75) -> dict:
    """Create a bar stool: round seat + four legs + footrest ring."""
    _check_name(name)
    seat_radius = _check_positive("seat_radius", seat_radius, 0.1, 0.6)
    height = _check_positive("height", height, 0.4, 1.5)
    seat_t = 0.06
    if seat_t >= height:
        raise ValueError("height must be larger than the 0.06m seat")

    bm = bmesh.new()
    wood, metal = _mats(name, [
        ("Wood", (0.48, 0.33, 0.18, 1.0), 0.7, 0.0),
        ("Metal", (0.35, 0.35, 0.38, 1.0), 0.4, 0.8),
    ])
    leg_h = height - seat_t
    leg_s = 0.045
    _cylinder(bm, seat_radius, seat_t,
              (0.0, 0.0, height - seat_t / 2.0), 24, 0)
    inset = seat_radius * 0.55
    _legs4(bm, inset, inset, leg_s, leg_h, 1)
    # Square footrest ring at ~1/3 of leg height.
    fz = leg_h / 3.0
    span = inset * 2.0 + leg_s
    bar = 0.025
    _box(bm, (span + bar, bar, bar), (0.0, inset, fz), 1)
    _box(bm, (span + bar, bar, bar), (0.0, -inset, fz), 1)
    _box(bm, (bar, span + bar, bar), (inset, 0.0, fz), 1)
    _box(bm, (bar, span + bar, bar), (-inset, 0.0, fz), 1)

    obj, dims, polys = _create_object(bm, name, [wood, metal])
    return _result(obj, dims, polys, [wood, metal],
                   seat_radius=seat_radius, height=height)


def create_bookshelf(server, name="Bookshelf", width=1.0, height=2.0,
                     depth=0.3, shelf_count=5) -> dict:
    """Create a bookshelf: sides + top/bottom + shelves + back panel."""
    _check_name(name)
    width = _check_positive("width", width, 0.3, 5.0)
    height = _check_positive("height", height, 0.5, 3.5)
    depth = _check_positive("depth", depth, 0.15, 2.0)
    shelf_count = _check_int("shelf_count", shelf_count, 0, 20)
    board_t = 0.03
    if board_t * 2.0 >= min(width, height):
        raise ValueError("dimensions must be larger than twice the 0.03m boards")

    bm = bmesh.new()
    (wood,) = _mats(name, [
        ("Wood", (0.50, 0.36, 0.20, 1.0), 0.75, 0.0),
    ])
    # Two sides.
    sx = width / 2.0 - board_t / 2.0
    for s in (-1.0, 1.0):
        _box(bm, (board_t, depth, height), (s * sx, 0.0, height / 2.0), 0)
    inner_w = width - 2.0 * board_t
    # Top and bottom boards.
    _box(bm, (inner_w, depth, board_t), (0.0, 0.0, board_t / 2.0), 0)
    _box(bm, (inner_w, depth, board_t),
         (0.0, 0.0, height - board_t / 2.0), 0)
    # Inner shelves evenly spaced.
    if shelf_count > 0:
        span = height - 2.0 * board_t
        for i in range(1, shelf_count + 1):
            z = board_t + span * i / (shelf_count + 1)
            _box(bm, (inner_w, depth - 0.02, board_t * 0.8),
                 (0.0, 0.01, z), 0)
    # Thin back panel.
    _box(bm, (inner_w, 0.015, height - 2 * board_t),
         (0.0, -depth / 2.0 + 0.0075, height / 2.0), 0)

    obj, dims, polys = _create_object(bm, name, [wood])
    return _result(obj, dims, polys, [wood],
                   width=width, height=height, depth=depth,
                   shelf_count=shelf_count)
