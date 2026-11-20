"""Room shell, door and window builders (domain pack).

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no booleans or external
assets. Wall openings are built by arranging solid segments around the
holes. All functions run on Blender's main thread, validate their inputs,
raise ``ValueError`` with a precise message on bad input, and return plain
JSON-serializable dictionaries.

Conventions: meters and degrees in public parameters, front is ``-Y``,
bilateral symmetry across ``X=0``, ground plane is ``Z=0``. ``location``
is always the bottom-center offset of the created object(s).
"""

import math

import bmesh
import bpy
from mathutils import Vector

_EPS = 1e-6


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _require_positive(value, label):
    if not _is_number(value) or not math.isfinite(float(value)) or float(value) <= 0.0:
        raise ValueError(f"{label} must be a positive finite number (got {value!r})")
    return float(value)


def _require_vector3(value, label):
    if isinstance(value, str) or not hasattr(value, "__len__") or len(value) != 3:
        raise ValueError(f"{label} must be a sequence of 3 numbers (got {value!r})")
    try:
        result = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a sequence of 3 numbers (got {value!r})") from exc
    if any(isinstance(v, bool) for v in value) or any(not math.isfinite(v) for v in result):
        raise ValueError(f"{label} coordinates must be finite numbers (got {value!r})")
    return result


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _get_or_create_material(name, rgba, roughness=0.8):
    """Get or create a simple Principled material (Blender 4.5/5.2 safe)."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = mat.node_tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    color = list(rgba) if len(rgba) == 4 else list(rgba) + [1.0]
    if "Base Color" in bsdf.inputs:
        bsdf.inputs["Base Color"].default_value = color
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = float(roughness)
    return mat


def _add_box(bm, xmin, xmax, ymin, ymax, zmin, zmax, material_index=None):
    """Append a solid axis-aligned box to *bm* (local coordinates)."""
    dx, dy, dz = xmax - xmin, ymax - ymin, zmax - zmin
    if dx <= _EPS or dy <= _EPS or dz <= _EPS:
        raise ValueError(
            f"box extents must be positive (got dx={dx}, dy={dy}, dz={dz})"
        )
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_cube(bm, size=1.0)
    verts = geo["verts"]
    bmesh.ops.scale(bm, vec=Vector((dx, dy, dz)), verts=verts)
    bmesh.ops.translate(
        bm,
        vec=Vector(((xmin + xmax) / 2.0, (ymin + ymax) / 2.0, (zmin + zmax) / 2.0)),
        verts=verts,
    )
    if material_index is not None:
        bm.faces.ensure_lookup_table()
        for face in set(bm.faces) - before:
            face.material_index = material_index


def _finish_object(bm, name, materials, location, rotation):
    """Build a mesh object from *bm*, place it, return (object, dimensions)."""
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    for mat in materials:
        mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = Vector(location)
    obj.rotation_euler = Vector((
        math.radians(rotation[0]),
        math.radians(rotation[1]),
        math.radians(rotation[2]),
    ))
    bpy.context.view_layer.update()
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    dims = [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)]
    return obj, dims


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def create_room_shell(server, name="Room", width=5.0, depth=4.0, height=3.0,
                       wall_thickness=0.12, floor_thickness=0.10,
                       door_width=0.9, door_height=2.1,
                       window_width=1.2, window_height=1.2,
                       location=(0.0, 0.0, 0.0)) -> dict:
    """Create a floor slab plus four walls with real door/window openings.

    The door opening is centered on the front wall (``-Y``), from the top
    of the floor slab upward. The window opening is centered on the right
    wall (``+X``), vertically centered in the wall height. Walls sit on
    top of the floor slab; the slab bottom is at ``location[2]``.
    """
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width")
    depth = _require_positive(depth, "depth")
    height = _require_positive(height, "height")
    wall_thickness = _require_positive(wall_thickness, "wall_thickness")
    floor_thickness = _require_positive(floor_thickness, "floor_thickness")
    door_width = _require_positive(door_width, "door_width")
    door_height = _require_positive(door_height, "door_height")
    window_width = _require_positive(window_width, "window_width")
    window_height = _require_positive(window_height, "window_height")
    loc = _require_vector3(location, "location")

    t = wall_thickness
    if 2.0 * t >= min(width, depth):
        raise ValueError(
            f"wall_thickness ({t}) must be less than half of min(width, depth) "
            f"(got width={width}, depth={depth})"
        )
    if door_width >= width - _EPS:
        raise ValueError(
            f"door_width ({door_width}) must be smaller than width ({width})"
        )
    if door_height >= height - _EPS:
        raise ValueError(
            f"door_height ({door_height}) must be smaller than height ({height})"
        )
    inner_length = depth - 2.0 * t
    if window_width >= inner_length - _EPS:
        raise ValueError(
            f"window_width ({window_width}) must be smaller than the right-wall "
            f"inner length ({inner_length})"
        )
    if window_height >= height - _EPS:
        raise ValueError(
            f"window_height ({window_height}) must be smaller than height ({height})"
        )

    hx, hy = width / 2.0, depth / 2.0
    base = floor_thickness  # wall base in local Z
    top = floor_thickness + height
    sill = (height - window_height) / 2.0  # window sill above wall base

    # Floor slab: full outer footprint, bottom at local Z=0.
    floor_bm = bmesh.new()
    _add_box(floor_bm, -hx, hx, -hy, hy, 0.0, floor_thickness)
    wall_mat = _get_or_create_material(clean + "_Wall", (0.82, 0.80, 0.74, 1.0), 0.9)
    floor_mat = _get_or_create_material(clean + "_Floor", (0.45, 0.42, 0.38, 1.0), 0.9)
    floor_obj, _ = _finish_object(floor_bm, clean + "_Floor", [floor_mat], loc, (0.0, 0.0, 0.0))

    # Walls: back solid, front with centered door hole, left solid,
    # right with centered window hole. All coordinates are local with the
    # room centered on X=0 / Y=0.
    walls_bm = bmesh.new()
    # Back wall (+Y), full width.
    _add_box(walls_bm, -hx, hx, hy - t, hy, base, top)
    # Front wall (-Y) around the door opening.
    dx = door_width / 2.0
    _add_box(walls_bm, -hx, -dx, -hy, -hy + t, base, top)
    _add_box(walls_bm, dx, hx, -hy, -hy + t, base, top)
    _add_box(walls_bm, -dx, dx, -hy, -hy + t, base + door_height, top)  # lintel
    # Left wall (-X), solid, between front and back walls.
    _add_box(walls_bm, -hx, -hx + t, -hy + t, hy - t, base, top)
    # Right wall (+X) around the window opening (opening spans Y).
    wy = window_width / 2.0
    wsill = base + sill
    wtop = wsill + window_height
    _add_box(walls_bm, hx - t, hx, -hy + t, -wy, base, top)
    _add_box(walls_bm, hx - t, hx, wy, hy - t, base, top)
    _add_box(walls_bm, hx - t, hx, -wy, wy, base, wsill)  # sill block
    _add_box(walls_bm, hx - t, hx, -wy, wy, wtop, top)  # lintel block
    walls_obj, walls_dims = _finish_object(
        walls_bm, clean + "_Walls", [wall_mat], loc, (0.0, 0.0, 0.0)
    )

    door_center = [loc[0], loc[1] - hy, loc[2] + base + door_height / 2.0]
    window_center = [loc[0] + hx, loc[1], loc[2] + wsill + window_height / 2.0]
    return {
        "success": True,
        "name": clean,
        "floor_object": floor_obj.name,
        "walls_object": walls_obj.name,
        "objects": [floor_obj.name, walls_obj.name],
        "width": width,
        "depth": depth,
        "height": height,
        "wall_thickness": t,
        "floor_thickness": floor_thickness,
        "dimensions": [round(width, 6), round(depth, 6), round(floor_thickness + height, 6)],
        "walls_dimensions": [round(v, 6) for v in walls_dims],
        "location": loc,
        "door_opening": {
            "wall": "front",
            "wall_axis": "-Y",
            "width": door_width,
            "height": door_height,
            "sill_height": 0.0,
            "center": [round(v, 6) for v in door_center],
        },
        "window_opening": {
            "wall": "right",
            "wall_axis": "+X",
            "width": window_width,
            "height": window_height,
            "sill_height": round(sill, 6),
            "center": [round(v, 6) for v in window_center],
        },
    }


def create_door(server, name="Door", width=0.9, height=2.1, thickness=0.04,
                frame_thickness=0.06, location=(0.0, 0.0, 0.0),
                rotation=(0.0, 0.0, 0.0)) -> dict:
    """Create a door slab plus surrounding frame as one joined mesh.

    Origin at bottom-center, slab spans local ``X``. ``rotation`` is Euler
    degrees (XYZ); ``location`` is the bottom-center offset.
    """
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width")
    height = _require_positive(height, "height")
    thickness = _require_positive(thickness, "thickness")
    frame_thickness = _require_positive(frame_thickness, "frame_thickness")
    loc = _require_vector3(location, "location")
    rot = _require_vector3(rotation, "rotation")
    if frame_thickness >= width - _EPS:
        raise ValueError(
            f"frame_thickness ({frame_thickness}) must be smaller than width ({width})"
        )
    if frame_thickness >= height - _EPS:
        raise ValueError(
            f"frame_thickness ({frame_thickness}) must be smaller than height ({height})"
        )

    ft = frame_thickness
    bm = bmesh.new()
    slab_mat = _get_or_create_material(clean + "_Slab", (0.40, 0.26, 0.13, 1.0), 0.7)
    frame_mat = _get_or_create_material(clean + "_Frame", (0.30, 0.22, 0.14, 1.0), 0.8)
    # Slab: bottom-center at local origin.
    _add_box(bm, -width / 2.0, width / 2.0, -thickness / 2.0, thickness / 2.0,
             0.0, height, material_index=0)
    # Frame jambs flanking the slab, header across the top.
    _add_box(bm, -width / 2.0 - ft, -width / 2.0, -thickness / 2.0, thickness / 2.0,
             0.0, height, material_index=1)
    _add_box(bm, width / 2.0, width / 2.0 + ft, -thickness / 2.0, thickness / 2.0,
             0.0, height, material_index=1)
    _add_box(bm, -width / 2.0 - ft, width / 2.0 + ft, -thickness / 2.0,
             thickness / 2.0, height, height + ft, material_index=1)
    obj, dims = _finish_object(bm, clean, [slab_mat, frame_mat], loc, rot)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "height": height,
        "thickness": thickness,
        "frame_thickness": ft,
        "dimensions": [round(v, 6) for v in dims],
        "location": loc,
        "rotation": rot,
    }


def create_window(server, name="Window", width=1.2, height=1.2,
                  frame_thickness=0.06, glass_thickness=0.01,
                  location=(0.0, 0.0, 0.0),
                  rotation=(0.0, 0.0, 0.0)) -> dict:
    """Create a window frame plus glass pane as one joined mesh.

    Outer size is ``width`` (local ``X``) by ``height`` (local ``Z``),
    origin at bottom-center. The glass fills the inner opening left by
    the frame rails.
    """
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width")
    height = _require_positive(height, "height")
    frame_thickness = _require_positive(frame_thickness, "frame_thickness")
    glass_thickness = _require_positive(glass_thickness, "glass_thickness")
    loc = _require_vector3(location, "location")
    rot = _require_vector3(rotation, "rotation")
    if 2.0 * frame_thickness >= width - _EPS:
        raise ValueError(
            f"2 * frame_thickness ({2.0 * frame_thickness}) must be smaller than "
            f"width ({width}) so the glass opening is positive"
        )
    if 2.0 * frame_thickness >= height - _EPS:
        raise ValueError(
            f"2 * frame_thickness ({2.0 * frame_thickness}) must be smaller than "
            f"height ({height}) so the glass opening is positive"
        )

    ft = frame_thickness
    frame_depth = max(ft, glass_thickness)
    fd = frame_depth / 2.0
    gd = glass_thickness / 2.0
    bm = bmesh.new()
    frame_mat = _get_or_create_material(clean + "_Frame", (0.88, 0.88, 0.86, 1.0), 0.5)
    glass_mat = _get_or_create_material(clean + "_Glass", (0.55, 0.75, 0.85, 1.0), 0.1)
    # Side jambs (full height), bottom and top rails between them.
    _add_box(bm, -width / 2.0, -width / 2.0 + ft, -fd, fd, 0.0, height, material_index=0)
    _add_box(bm, width / 2.0 - ft, width / 2.0, -fd, fd, 0.0, height, material_index=0)
    _add_box(bm, -width / 2.0 + ft, width / 2.0 - ft, -fd, fd, 0.0, ft, material_index=0)
    _add_box(bm, -width / 2.0 + ft, width / 2.0 - ft, -fd, fd,
             height - ft, height, material_index=0)
    # Glass pane filling the inner opening.
    _add_box(bm, -width / 2.0 + ft, width / 2.0 - ft, -gd, gd, ft,
             height - ft, material_index=1)
    obj, dims = _finish_object(bm, clean, [frame_mat, glass_mat], loc, rot)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "height": height,
        "frame_thickness": ft,
        "glass_thickness": glass_thickness,
        "frame_depth": round(frame_depth, 6),
        "dimensions": [round(v, 6) for v in dims],
        "glass_dimensions": [
            round(width - 2.0 * ft, 6),
            round(glass_thickness, 6),
            round(height - 2.0 * ft, 6),
        ],
        "location": loc,
        "rotation": rot,
    }
