"""Parametric furniture domain pack.

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no external assets.
Every function builds ONE joined mesh object grounded at Z=0, assigns
sensible Principled materials per part, and returns a JSON-serializable
dict. Blender 4.5 / 5.2 compatible.
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


# ---------------------------------------------------------------------------
# public functions
# ---------------------------------------------------------------------------

def create_table(server, name="Table", width=1.4, depth=0.8, height=0.75,
                 top_thickness=0.04, leg_size=0.06) -> dict:
    """Create a table: top slab + four legs + apron, grounded at Z=0."""
    _check_name(name)
    width = _check_positive("width", width, 0.2, 10.0)
    depth = _check_positive("depth", depth, 0.2, 10.0)
    height = _check_positive("height", height, 0.2, 5.0)
    top_thickness = _check_positive("top_thickness", top_thickness, 0.01, 0.3)
    leg_size = _check_positive("leg_size", leg_size, 0.02, 0.5)
    if top_thickness >= height:
        raise ValueError("top_thickness must be smaller than height")
    if leg_size * 2.0 >= min(width, depth):
        raise ValueError("leg_size must be smaller than half of width/depth")

    bm = bmesh.new()
    wood, metal = _mats(name, [
        ("Wood", (0.45, 0.30, 0.16, 1.0), 0.7, 0.0),
        ("Metal", (0.35, 0.35, 0.38, 1.0), 0.4, 0.8),
    ])
    leg_h = height - top_thickness
    # Top slab.
    _box(bm, (width, depth, top_thickness),
         (0.0, 0.0, height - top_thickness / 2.0), 0)
    # Four legs, inset by half leg size from each edge.
    ox, oy = width / 2.0 - leg_size / 2.0, depth / 2.0 - leg_size / 2.0
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            _box(bm, (leg_size, leg_size, leg_h),
                 (sx * ox, sy * oy, leg_h / 2.0), 1)
    # Apron under the top when there is room.
    apron_h = min(0.08, leg_h - 0.04)
    if apron_h >= 0.03:
        az = height - top_thickness - apron_h / 2.0
        at = 0.02
        _box(bm, (width - 2 * leg_size, at, apron_h), (0.0, oy, az), 0)
        _box(bm, (width - 2 * leg_size, at, apron_h), (0.0, -oy, az), 0)
        _box(bm, (at, depth - 2 * leg_size, apron_h), (ox, 0.0, az), 0)
        _box(bm, (at, depth - 2 * leg_size, apron_h), (-ox, 0.0, az), 0)

    obj, dims, polys = _create_object(bm, name, [wood, metal])
    return {
        "success": True,
        "object": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [wood.name, metal.name],
        "width": width,
        "depth": depth,
        "height": height,
    }


def create_chair(server, name="Chair", seat_width=0.45, seat_depth=0.45,
                 seat_height=0.45, back_height=0.45,
                 leg_size=0.04) -> dict:
    """Create a chair: seat + four legs + backrest, grounded at Z=0."""
    _check_name(name)
    seat_width = _check_positive("seat_width", seat_width, 0.2, 3.0)
    seat_depth = _check_positive("seat_depth", seat_depth, 0.2, 3.0)
    seat_height = _check_positive("seat_height", seat_height, 0.15, 2.0)
    back_height = _check_positive("back_height", back_height, 0.15, 2.0)
    leg_size = _check_positive("leg_size", leg_size, 0.015, 0.3)
    if leg_size * 2.0 >= min(seat_width, seat_depth):
        raise ValueError("leg_size must be smaller than half of seat_width/seat_depth")

    bm = bmesh.new()
    wood, fabric = _mats(name, [
        ("Wood", (0.45, 0.30, 0.16, 1.0), 0.7, 0.0),
        ("Fabric", (0.30, 0.35, 0.55, 1.0), 0.95, 0.0),
    ])
    seat_t = min(0.04, seat_height / 2.0)
    # Seat slab.
    _box(bm, (seat_width, seat_depth, seat_t),
         (0.0, 0.0, seat_height - seat_t / 2.0), 0)
    # Four legs.
    ox, oy = seat_width / 2.0 - leg_size / 2.0, seat_depth / 2.0 - leg_size / 2.0
    leg_h = seat_height - seat_t
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            _box(bm, (leg_size, leg_size, leg_h),
                 (sx * ox, sy * oy, leg_h / 2.0), 0)
    # Backrest: two rear posts + panel.
    post_t = leg_size
    post_h = back_height + seat_t
    rear_y = -oy
    for sx in (-1.0, 1.0):
        _box(bm, (post_t, post_t, post_h),
             (sx * ox, rear_y, seat_height + back_height / 2.0 - seat_t / 2.0), 0)
    _box(bm, (seat_width, 0.03, back_height),
         (0.0, rear_y, seat_height + back_height / 2.0), 1)

    obj, dims, polys = _create_object(bm, name, [wood, fabric])
    return {
        "success": True,
        "object": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [wood.name, fabric.name],
        "seat_width": seat_width,
        "seat_depth": seat_depth,
        "seat_height": seat_height,
        "back_height": back_height,
    }


def create_shelf(server, name="Shelf", width=1.0, height=1.8, depth=0.3,
                 shelf_count=4, board_thickness=0.03) -> dict:
    """Create a shelf unit: two sides + top/bottom + inner boards."""
    _check_name(name)
    width = _check_positive("width", width, 0.2, 10.0)
    height = _check_positive("height", height, 0.3, 5.0)
    depth = _check_positive("depth", depth, 0.15, 5.0)
    shelf_count = _check_int("shelf_count", shelf_count, 0, 20)
    board_thickness = _check_positive("board_thickness", board_thickness, 0.01, 0.2)
    if board_thickness * 2.0 >= min(width, height):
        raise ValueError("board_thickness must be smaller than half of width/height")

    bm = bmesh.new()
    (wood,) = _mats(name, [
        ("Wood", (0.50, 0.36, 0.20, 1.0), 0.75, 0.0),
    ])
    # Two sides.
    sx = width / 2.0 - board_thickness / 2.0
    for s in (-1.0, 1.0):
        _box(bm, (board_thickness, depth, height), (s * sx, 0.0, height / 2.0), 0)
    inner_w = width - 2.0 * board_thickness
    # Top and bottom boards.
    _box(bm, (inner_w, depth, board_thickness),
         (0.0, 0.0, board_thickness / 2.0), 0)
    _box(bm, (inner_w, depth, board_thickness),
         (0.0, 0.0, height - board_thickness / 2.0), 0)
    # Inner horizontal boards evenly spaced.
    if shelf_count > 0:
        span = height - 2.0 * board_thickness
        for i in range(1, shelf_count + 1):
            z = board_thickness + span * i / (shelf_count + 1)
            _box(bm, (inner_w, depth, board_thickness), (0.0, 0.0, z), 0)

    obj, dims, polys = _create_object(bm, name, [wood])
    return {
        "success": True,
        "object": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [wood.name],
        "width": width,
        "height": height,
        "depth": depth,
        "shelf_count": shelf_count,
    }


def create_bed(server, name="Bed", width=1.6, length=2.0, height=0.5,
               headboard_height=0.9) -> dict:
    """Create a bed: frame + mattress + headboard, grounded at Z=0."""
    _check_name(name)
    width = _check_positive("width", width, 0.5, 5.0)
    length = _check_positive("length", length, 0.8, 6.0)
    height = _check_positive("height", height, 0.2, 2.0)
    headboard_height = _check_positive("headboard_height", headboard_height, 0.3, 2.5)

    bm = bmesh.new()
    wood, fabric, blanket = _mats(name, [
        ("Wood", (0.42, 0.28, 0.15, 1.0), 0.7, 0.0),
        ("Mattress", (0.88, 0.87, 0.83, 1.0), 0.95, 0.0),
        ("Blanket", (0.35, 0.45, 0.60, 1.0), 0.95, 0.0),
    ])
    leg_h = min(0.25, height * 0.4)
    leg_s = 0.08
    # Four short legs.
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            _box(bm, (leg_s, leg_s, leg_h),
                 (sx * (width / 2.0 - leg_s / 2.0),
                  sy * (length / 2.0 - leg_s / 2.0), leg_h / 2.0), 0)
    # Frame rails around the perimeter.
    rail_h = height - leg_h
    rail_t = 0.05
    rz = leg_h + rail_h / 2.0
    _box(bm, (width, rail_t, rail_h), (0.0, length / 2.0 - rail_t / 2.0, rz), 0)
    _box(bm, (width, rail_t, rail_h), (0.0, -length / 2.0 + rail_t / 2.0, rz), 0)
    _box(bm, (rail_t, length, rail_h), (width / 2.0 - rail_t / 2.0, 0.0, rz), 0)
    _box(bm, (rail_t, length, rail_h), (-width / 2.0 + rail_t / 2.0, 0.0, rz), 0)
    # Mattress + folded blanket on top.
    matt_t = 0.20
    _box(bm, (width - 0.10, length - 0.10, matt_t),
         (0.0, 0.0, height + matt_t / 2.0), 1)
    _box(bm, (width - 0.10, length * 0.45, 0.06),
         (0.0, length * 0.15, height + matt_t + 0.03), 2)
    # Headboard panel at the rear (-Y).
    hb_t = 0.06
    _box(bm, (width, hb_t, headboard_height),
         (0.0, -length / 2.0 + hb_t / 2.0, headboard_height / 2.0), 0)

    obj, dims, polys = _create_object(bm, name, [wood, fabric, blanket])
    return {
        "success": True,
        "object": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [wood.name, fabric.name, blanket.name],
        "width": width,
        "length": length,
        "height": height,
        "headboard_height": headboard_height,
    }


def create_sofa(server, name="Sofa", width=2.0, depth=0.9, height=0.8,
                 seat_count=3) -> dict:
    """Create a sofa: base + seat/back cushions + armrests, grounded at Z=0."""
    _check_name(name)
    width = _check_positive("width", width, 0.6, 6.0)
    depth = _check_positive("depth", depth, 0.5, 3.0)
    height = _check_positive("height", height, 0.4, 2.5)
    seat_count = _check_int("seat_count", seat_count, 1, 6)
    if width / seat_count < 0.3:
        raise ValueError("width must allow at least 0.3m per seat cushion")

    bm = bmesh.new()
    fabric, dark = _mats(name, [
        ("Fabric", (0.45, 0.30, 0.35, 1.0), 0.95, 0.0),
        ("Frame", (0.25, 0.22, 0.24, 1.0), 0.85, 0.0),
    ])
    base_h = height * 0.35
    arm_w = min(0.20, width * 0.12)
    back_t = min(0.20, depth * 0.25)
    # Base + armrests + backrest frame.
    _box(bm, (width, depth, base_h), (0.0, 0.0, base_h / 2.0), 1)
    _box(bm, (arm_w, depth, height),
         (width / 2.0 - arm_w / 2.0, 0.0, height / 2.0), 1)
    _box(bm, (arm_w, depth, height),
         (-width / 2.0 + arm_w / 2.0, 0.0, height / 2.0), 1)
    _box(bm, (width, back_t, height),
         (0.0, -depth / 2.0 + back_t / 2.0, height / 2.0), 1)
    # Seat cushions + back cushions.
    inner_w = width - 2.0 * arm_w
    cw = inner_w / seat_count
    cushion_t = 0.15
    gap = min(0.02, cw * 0.05)
    for i in range(seat_count):
        cx = -inner_w / 2.0 + cw * (i + 0.5)
        _box(bm, (cw - gap, depth - back_t - arm_w * 0.2, cushion_t),
             (cx, arm_w * 0.1, base_h + cushion_t / 2.0), 0)
        _box(bm, (cw - gap, 0.14, height - base_h - cushion_t + 0.05),
             (cx, -depth / 2.0 + back_t + 0.07,
              base_h + cushion_t + (height - base_h - cushion_t) / 2.0), 0)

    obj, dims, polys = _create_object(bm, name, [fabric, dark])
    return {
        "success": True,
        "object": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [fabric.name, dark.name],
        "width": width,
        "depth": depth,
        "height": height,
        "seat_count": seat_count,
    }


def create_kitchen_block(server, name="Kitchen", width=2.4, depth=0.6,
                         height=0.9, cabinet_count=4,
                         counter_thickness=0.04) -> dict:
    """Create a kitchen block: cabinet body + doors + countertop."""
    _check_name(name)
    width = _check_positive("width", width, 0.4, 10.0)
    depth = _check_positive("depth", depth, 0.3, 3.0)
    height = _check_positive("height", height, 0.4, 3.0)
    cabinet_count = _check_int("cabinet_count", cabinet_count, 1, 12)
    counter_thickness = _check_positive("counter_thickness", counter_thickness, 0.01, 0.3)
    if counter_thickness >= height:
        raise ValueError("counter_thickness must be smaller than height")
    if width / cabinet_count < 0.2:
        raise ValueError("width must allow at least 0.2m per cabinet door")

    bm = bmesh.new()
    cabinet, door, counter, steel = _mats(name, [
        ("Cabinet", (0.75, 0.72, 0.68, 1.0), 0.6, 0.0),
        ("Door", (0.55, 0.50, 0.45, 1.0), 0.55, 0.0),
        ("Counter", (0.30, 0.30, 0.32, 1.0), 0.35, 0.0),
        ("Steel", (0.70, 0.71, 0.73, 1.0), 0.3, 0.9),
    ])
    body_h = height - counter_thickness
    kick_h = min(0.10, body_h * 0.15)
    # Carcass (recessed toe-kick at the bottom front).
    _box(bm, (width, depth - 0.06, body_h - kick_h),
         (0.0, -0.03, kick_h + (body_h - kick_h) / 2.0), 0)
    _box(bm, (width, depth - 0.12, kick_h),
         (0.0, -0.06, kick_h / 2.0), 0)
    # Door panels with gaps + bar handles.
    door_w = width / cabinet_count
    gap = min(0.015, door_w * 0.05)
    for i in range(cabinet_count):
        cx = -width / 2.0 + door_w * (i + 0.5)
        _box(bm, (door_w - gap, 0.02, body_h - kick_h - 0.04),
             (cx, depth / 2.0 - 0.06 + 0.01 - 0.03, kick_h + (body_h - kick_h) / 2.0), 1)
        _box(bm, (0.12, 0.025, 0.025),
             (cx, depth / 2.0 - 0.06 + 0.02 - 0.03, body_h - 0.12), 3)
    # Countertop with slight overhang.
    _box(bm, (width + 0.04, depth + 0.02, counter_thickness),
         (0.0, 0.01, body_h + counter_thickness / 2.0), 2)

    obj, dims, polys = _create_object(bm, name, [cabinet, door, counter, steel])
    return {
        "success": True,
        "object": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [cabinet.name, door.name, counter.name, steel.name],
        "width": width,
        "depth": depth,
        "height": height,
        "cabinet_count": cabinet_count,
    }
