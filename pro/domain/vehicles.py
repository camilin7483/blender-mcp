"""Vehicle and robot blockout domain pack.

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no external files.
All functions run on Blender's main thread, validate their inputs and
return plain JSON-serializable dictionaries. Each builder produces one
joined mesh object grounded at Z=0 with approximate requested dimensions.

All blockouts use length along X (front at -X), width along Y, up at +Z.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

_LIMITATIONS = (
    "Blockout geometry only: approximate proportions for layout and preview, "
    "not a production vehicle asset (no interior, rigging, UVs, or fine details)."
)

_VALID_ROBOT_BUILDS = ("humanoid", "rover")


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


def _get_or_create_material(name, rgba, roughness=0.6, metallic=0.0):
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


def _vehicle_materials(name, paint_color):
    """Standard rubber/metal/paint/glass set for one vehicle blockout."""
    rubber = _get_or_create_material(name + "_Rubber", (0.05, 0.05, 0.06, 1.0), 0.9)
    metal = _get_or_create_material(name + "_Metal", (0.55, 0.57, 0.60, 1.0), 0.35, 0.85)
    paint = _get_or_create_material(name + "_Paint", paint_color, 0.4, 0.1)
    glass = _get_or_create_material(name + "_Glass", (0.55, 0.75, 0.90, 1.0), 0.1)
    return rubber, metal, paint, glass


def _snapshot(bm):
    bm.faces.ensure_lookup_table()
    return set(bm.faces)


def _tag_new(bm, before, material_index):
    bm.faces.ensure_lookup_table()
    for face in bm.faces:
        if face not in before:
            face.material_index = material_index


def _add_box(bm, center, dims, mat_index):
    before = _snapshot(bm)
    verts = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    bmesh.ops.scale(bm, vec=Vector((float(dims[0]), float(dims[1]), float(dims[2]))),
                    verts=verts)
    bmesh.ops.translate(bm, vec=Vector((float(center[0]), float(center[1]),
                                        float(center[2]))), verts=verts)
    _tag_new(bm, before, mat_index)
    return verts


def _add_box_rotated(bm, pivot, angle_z, local_center, dims, mat_index):
    """Box placed at *local_center*, rotated about Z, then moved to *pivot*."""
    before = _snapshot(bm)
    verts = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    bmesh.ops.scale(bm, vec=Vector((float(dims[0]), float(dims[1]), float(dims[2]))),
                    verts=verts)
    bmesh.ops.translate(bm, vec=Vector((float(local_center[0]), float(local_center[1]),
                                         float(local_center[2]))), verts=verts)
    bmesh.ops.rotate(bm, cent=Vector((0.0, 0.0, 0.0)),
                     matrix=Matrix.Rotation(float(angle_z), 3, "Z"), verts=verts)
    bmesh.ops.translate(bm, vec=Vector((float(pivot[0]), float(pivot[1]),
                                        float(pivot[2]))), verts=verts)
    _tag_new(bm, before, mat_index)
    return verts


def _add_cylinder(bm, center, radius, depth, mat_index, segments=16, axis="Z"):
    before = _snapshot(bm)
    verts = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segments,
        radius1=float(radius), radius2=float(radius), depth=float(depth),
    )["verts"]
    if axis == "X":
        bmesh.ops.rotate(bm, cent=Vector((0.0, 0.0, 0.0)),
                         matrix=Matrix.Rotation(math.pi / 2.0, 3, "Y"), verts=verts)
    elif axis == "Y":
        bmesh.ops.rotate(bm, cent=Vector((0.0, 0.0, 0.0)),
                         matrix=Matrix.Rotation(math.pi / 2.0, 3, "X"), verts=verts)
    elif axis != "Z":
        raise ValueError(f"axis must be 'X', 'Y' or 'Z', got {axis!r}")
    bmesh.ops.translate(bm, vec=Vector((float(center[0]), float(center[1]),
                                        float(center[2]))), verts=verts)
    _tag_new(bm, before, mat_index)
    return verts


def _add_sphere(bm, center, radius, mat_index, u_segments=16, v_segments=12, scale=None):
    before = _snapshot(bm)
    verts = bmesh.ops.create_uvsphere(
        bm, u_segments=u_segments, v_segments=v_segments, radius=float(radius),
        matrix=Matrix.Translation(Vector((float(center[0]), float(center[1]),
                                          float(center[2])))),
    )["verts"]
    if scale is not None:
        factors = (float(scale[0]), float(scale[1]), float(scale[2]))
        pivot = Vector((float(center[0]), float(center[1]), float(center[2])))
        for v in verts:
            offset = v.co - pivot
            v.co = pivot + Vector((offset.x * factors[0],
                                   offset.y * factors[1],
                                   offset.z * factors[2]))
    _tag_new(bm, before, mat_index)
    return verts


def _add_tube(bm, p0, p1, radius, mat_index, segments=10):
    """Cylinder strut between two points."""
    start = Vector((float(p0[0]), float(p0[1]), float(p0[2])))
    end = Vector((float(p1[0]), float(p1[1]), float(p1[2])))
    direction = end - start
    length = direction.length
    if length < 1e-6:
        return []
    before = _snapshot(bm)
    verts = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segments,
        radius1=float(radius), radius2=float(radius), depth=float(length),
    )["verts"]
    rotation = Vector((0.0, 0.0, 1.0)).rotation_difference(direction.normalized())
    matrix = rotation.to_matrix()
    for v in verts:
        v.co = matrix @ v.co
    bmesh.ops.translate(bm, vec=(start + end) / 2.0, verts=verts)
    _tag_new(bm, before, mat_index)
    return verts



def _torus(bm, major_rad, minor_rad, major_seg=24, minor_seg=10):
    """Build a torus in the XZ plane (axle along Y) without bmesh.ops.create_torus."""
    major_rad = float(major_rad)
    minor_rad = float(minor_rad)
    major_seg = max(int(major_seg), 3)
    minor_seg = max(int(minor_seg), 3)
    rings = []
    for i in range(major_seg):
        theta = 2.0 * math.pi * i / major_seg
        ring = []
        for j in range(minor_seg):
            phi = 2.0 * math.pi * j / minor_seg
            radial = major_rad + minor_rad * math.cos(phi)
            ring.append(bm.verts.new((
                math.cos(theta) * radial,
                math.sin(theta) * radial,
                minor_rad * math.sin(phi),
            )))
        rings.append(ring)
    for i in range(major_seg):
        nxt = (i + 1) % major_seg
        for j in range(minor_seg):
            jn = (j + 1) % minor_seg
            bm.faces.new((rings[i][j], rings[nxt][j], rings[nxt][jn], rings[i][jn]))
    return [vertex for ring in rings for vertex in ring]


def _add_wheel(bm, center, radius, width, rubber_index, metal_index, segments=24):
    """Tire torus + rim cylinder + hub cylinder, axle along Y."""
    center = Vector((float(center[0]), float(center[1]), float(center[2])))
    minor = min(float(width) * 0.30, float(radius) * 0.45)
    minor = max(minor, float(radius) * 0.08)
    major = max(float(radius) - minor, float(radius) * 0.4)
    tilt = Matrix.Rotation(math.pi / 2.0, 3, "X")
    before = _snapshot(bm)
    verts = _torus(bm, major, minor, max(int(segments), 8), 12)
    for v in verts:
        v.co = tilt @ v.co
    bmesh.ops.translate(bm, vec=center, verts=verts)
    _tag_new(bm, before, rubber_index)
    _add_cylinder(bm, center, float(radius) * 0.55, float(width) * 0.7,
                  metal_index, segments=max(int(segments), 8), axis="Y")
    _add_cylinder(bm, center, float(radius) * 0.16, float(width) * 1.02,
                  metal_index, segments=12, axis="Y")


def _ground(bm):
    bm.verts.ensure_lookup_table()
    if not bm.verts:
        return
    minimum = min(v.co.z for v in bm.verts)
    if abs(minimum) > 1e-9:
        bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, -minimum)),
                            verts=list(bm.verts))


def _create_object(bm, name, materials):
    _check_name(name)
    _ground(bm)
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
    dims = [float(max(xs) - min(xs)), float(max(ys) - min(ys)), float(max(zs) - min(zs))]
    return obj, dims, len(mesh.polygons)


def _result(obj, dims, polys, materials, requested, extra=None):
    data = {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "dimensions": dims,
        "requested": requested,
        "polygon_count": polys,
        "materials": [m.name for m in materials],
        "forward": "-X",
        "limitations": _LIMITATIONS,
    }
    if extra:
        data.update(extra)
    return data


# ---------------------------------------------------------------------------
# public functions
# ---------------------------------------------------------------------------

def create_wheel(server, name="Wheel", radius=0.35, width=0.22,
                 segments=24) -> dict:
    """Create a wheel blockout (tire torus, rim and hub) grounded at Z=0."""
    _check_name(name)
    radius = _check_positive("radius", radius, 0.05, 2.0)
    width = _check_positive("width", width, 0.02, 1.0)
    segments = _check_int("segments", segments, 8, 64)

    rubber, metal, paint, glass = _vehicle_materials(name, (0.2, 0.2, 0.22, 1.0))
    bm = bmesh.new()
    _add_wheel(bm, (0.0, 0.0, radius), radius, width, 0, 1, segments=segments)
    obj, dims, polys = _create_object(bm, name, [rubber, metal, paint, glass])
    return _result(obj, dims, polys, [rubber, metal],
                   {"radius": radius, "width": width, "segments": segments},
                   {"wheel_radius": radius, "wheel_width": width})


def create_car_blockout(server, name="Car", length=4.2, width=1.8,
                        height=1.4) -> dict:
    """Create a car blockout (body, cabin, four wheels, lights)."""
    _check_name(name)
    length = _check_positive("length", length, 1.0, 20.0)
    width = _check_positive("width", width, 0.5, 5.0)
    height = _check_positive("height", height, 0.3, 5.0)

    wheel_radius = min(height * 0.28, width * 0.24, length * 0.10)
    if wheel_radius < 0.05:
        raise ValueError("dimensions too small to fit wheels; "
                         "increase length, width or height")
    wheel_width = wheel_radius * 0.7

    rubber, metal, paint, glass = _vehicle_materials(name, (0.10, 0.25, 0.70, 1.0))
    light_front = _get_or_create_material(name + "_LightFront",
                                          (1.0, 0.95, 0.70, 1.0), 0.3)
    light_rear = _get_or_create_material(name + "_LightRear",
                                         (0.80, 0.05, 0.05, 1.0), 0.3)
    materials = [rubber, metal, paint, glass, light_front, light_rear]

    bm = bmesh.new()
    body_bottom = max(wheel_radius * 0.8, height * 0.15)
    body_h = height * 0.34
    _add_box(bm, (0.0, 0.0, body_bottom + body_h / 2.0),
             (length, width * 0.96, body_h), 2)
    cabin_h = height * 0.30
    cabin_len = length * 0.45
    cabin_x = length * 0.03
    _add_box(bm, (cabin_x, 0.0, body_bottom + body_h + cabin_h / 2.0),
             (cabin_len, width * 0.80, cabin_h), 2)
    _add_box(bm, (cabin_x - cabin_len / 2.0 - 0.01, 0.0,
                  body_bottom + body_h + cabin_h * 0.45),
             (0.06, width * 0.70, cabin_h * 0.70), 3)
    _add_box(bm, (cabin_x + cabin_len / 2.0 + 0.01, 0.0,
                  body_bottom + body_h + cabin_h * 0.45),
             (0.06, width * 0.70, cabin_h * 0.60), 3)
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            _add_wheel(bm, (sx * length * 0.32,
                            sy * (width / 2.0 - wheel_width / 2.0),
                            wheel_radius),
                       wheel_radius, wheel_width, 0, 1)
    for sy in (-1.0, 1.0):
        _add_box(bm, (-length / 2.0 - 0.02, sy * width * 0.30,
                      body_bottom + body_h * 0.55),
                 (0.06, 0.25, 0.12), 4)
        _add_box(bm, (length / 2.0 + 0.02, sy * width * 0.30,
                      body_bottom + body_h * 0.55),
                 (0.06, 0.25, 0.12), 5)

    obj, dims, polys = _create_object(bm, name, materials)
    return _result(obj, dims, polys, materials,
                   {"length": length, "width": width, "height": height},
                   {"wheel_radius": wheel_radius, "wheel_count": 4})


def create_bicycle_blockout(server, name="Bicycle", length=1.7,
                            height=1.0) -> dict:
    """Create a bicycle blockout (frame tubes, two wheels, handlebar, seat)."""
    _check_name(name)
    length = _check_positive("length", length, 0.5, 5.0)
    height = _check_positive("height", height, 0.3, 3.0)

    wheel_radius = min(height * 0.32, length * 0.20)
    if wheel_radius < 0.05:
        raise ValueError("dimensions too small to fit wheels; "
                         "increase length or height")

    rubber, metal, paint, glass = _vehicle_materials(name, (0.70, 0.10, 0.10, 1.0))
    seat_mat = _get_or_create_material(name + "_Seat", (0.08, 0.08, 0.09, 1.0), 0.9)
    materials = [rubber, metal, paint, glass, seat_mat]

    bm = bmesh.new()
    rear = Vector((-length * 0.36, 0.0, wheel_radius))
    front = Vector((length * 0.36, 0.0, wheel_radius))
    tube_r = max(height * 0.022, 0.008)
    # Spoked wheels: thin tire torus, rim torus, hub and spokes.
    for axle in (rear, front):
        tire_minor = max(wheel_radius * 0.09, 0.008)
        before = _snapshot(bm)
        verts = _torus(bm, wheel_radius - tire_minor, tire_minor, 28, 10)
        tilt = Matrix.Rotation(math.pi / 2.0, 3, "X")
        for v in verts:
            v.co = tilt @ v.co
        bmesh.ops.translate(bm, vec=axle, verts=verts)
        _tag_new(bm, before, 0)
        rim_major = max(wheel_radius - 2.0 * tire_minor - 0.008, wheel_radius * 0.5)
        rim_minor = max(wheel_radius * 0.03, 0.005)
        before = _snapshot(bm)
        verts = _torus(bm, rim_major, rim_minor, 24, 8)
        for v in verts:
            v.co = tilt @ v.co
        bmesh.ops.translate(bm, vec=axle, verts=verts)
        _tag_new(bm, before, 1)
        hub_r = wheel_radius * 0.08
        _add_cylinder(bm, axle, hub_r, 0.07, 1, segments=10, axis="Y")
        for i in range(6):
            angle = math.pi * i / 3.0
            direction = Vector((math.cos(angle), 0.0, math.sin(angle)))
            _add_tube(bm, axle + direction * hub_r, axle + direction * rim_major,
                      max(wheel_radius * 0.015, 0.003), 1, segments=6)

    bracket = Vector((-length * 0.02, 0.0, height * 0.32))
    seat_top = Vector((-length * 0.14, 0.0, height * 0.90))
    head_bottom = Vector((length * 0.30, 0.0, height * 0.60))
    head_top = Vector((length * 0.26, 0.0, height * 0.86))
    _add_tube(bm, rear, bracket, tube_r, 2)
    _add_tube(bm, bracket, head_bottom, tube_r, 2)
    _add_tube(bm, head_bottom, head_top, tube_r * 1.3, 2)
    _add_tube(bm, bracket, seat_top, tube_r, 2)
    _add_tube(bm, seat_top, head_top, tube_r * 0.9, 2)
    _add_tube(bm, rear, seat_top, tube_r * 0.6, 2)
    _add_tube(bm, front, head_bottom, tube_r * 0.9, 2)
    _add_box(bm, seat_top + Vector((0.0, 0.0, 0.035)),
             (length * 0.14, 0.07, 0.05), 4)
    bar_center = Vector((length * 0.24, 0.0, height * 0.95))
    _add_tube(bm, head_top, bar_center, tube_r * 0.8, 1)
    bar_w = max(length * 0.25, 0.30)
    _add_cylinder(bm, bar_center, tube_r * 0.8, bar_w, 1, segments=10, axis="Y")
    for sy in (-1.0, 1.0):
        _add_cylinder(bm, bar_center + Vector((0.0, sy * (bar_w / 2.0 - 0.035), 0.0)),
                      tube_r * 1.1, 0.07, 0, segments=8, axis="Y")

    obj, dims, polys = _create_object(bm, name, materials)
    return _result(obj, dims, polys, materials,
                   {"length": length, "height": height},
                   {"wheel_radius": wheel_radius, "wheel_count": 2})


def create_motorcycle_blockout(server, name="Motorcycle", length=2.1,
                               height=1.1) -> dict:
    """Create a motorcycle blockout (body, two wheels, seat, handlebar)."""
    _check_name(name)
    length = _check_positive("length", length, 0.8, 6.0)
    height = _check_positive("height", height, 0.4, 3.0)

    wheel_radius = min(height * 0.30, length * 0.18)
    if wheel_radius < 0.05:
        raise ValueError("dimensions too small to fit wheels; "
                         "increase length or height")
    wheel_width = wheel_radius * 0.55
    body_w = length * 0.28

    rubber, metal, paint, glass = _vehicle_materials(name, (0.15, 0.15, 0.17, 1.0))
    seat_mat = _get_or_create_material(name + "_Seat", (0.07, 0.07, 0.08, 1.0), 0.9)
    light_mat = _get_or_create_material(name + "_Headlight",
                                        (1.0, 0.95, 0.75, 1.0), 0.3)
    materials = [rubber, metal, paint, glass, seat_mat, light_mat]

    bm = bmesh.new()
    rear = Vector((-length * 0.34, 0.0, wheel_radius))
    front = Vector((length * 0.34, 0.0, wheel_radius))
    _add_wheel(bm, rear, wheel_radius, wheel_width, 0, 1)
    _add_wheel(bm, front, wheel_radius, wheel_width, 0, 1)
    engine_z = wheel_radius + height * 0.12
    _add_box(bm, (0.0, 0.0, engine_z),
             (length * 0.22, body_w * 0.55, height * 0.22), 1)
    _add_box(bm, (-length * 0.02, 0.0, engine_z + height * 0.20),
             (length * 0.24, body_w * 0.60, height * 0.16), 2)
    _add_box(bm, (-length * 0.22, 0.0, engine_z + height * 0.24),
             (length * 0.24, body_w * 0.50, height * 0.09), 4)
    head_top = Vector((length * 0.28, 0.0, height * 0.88))
    fork_r = max(height * 0.025, 0.010)
    for sy in (-1.0, 1.0):
        _add_tube(bm, front + Vector((0.0, sy * wheel_width * 0.3, 0.0)),
                  head_top + Vector((0.0, sy * 0.03, 0.0)), fork_r, 1)
        _add_tube(bm, rear + Vector((0.0, sy * wheel_width * 0.3, 0.0)),
                  Vector((-length * 0.05, sy * 0.05, engine_z)), fork_r, 1)
    bar_w = max(length * 0.22, 0.30)
    _add_cylinder(bm, head_top + Vector((0.0, 0.0, 0.03)), 0.02, bar_w,
                  1, segments=10, axis="Y")
    _add_box(bm, (head_top.x - 0.10, 0.0, head_top.z - 0.02),
             (0.08, 0.16, 0.14), 5)
    _add_tube(bm, Vector((length * 0.05, body_w * 0.20, engine_z - 0.02)),
              Vector((length * 0.36, body_w * 0.20, wheel_radius * 1.1)),
              max(height * 0.035, 0.012), 1)

    obj, dims, polys = _create_object(bm, name, materials)
    return _result(obj, dims, polys, materials,
                   {"length": length, "height": height},
                   {"wheel_radius": wheel_radius, "wheel_count": 2})


def create_boat_blockout(server, name="Boat", length=5.0, width=1.8,
                         height=1.0) -> dict:
    """Create a boat blockout (tapered hull, deck, console, motor)."""
    _check_name(name)
    length = _check_positive("length", length, 1.0, 60.0)
    width = _check_positive("width", width, 0.5, 15.0)
    height = _check_positive("height", height, 0.3, 10.0)

    rubber, metal, paint, glass = _vehicle_materials(name, (0.85, 0.85, 0.88, 1.0))
    deck_mat = _get_or_create_material(name + "_Deck", (0.50, 0.35, 0.20, 1.0), 0.8)
    materials = [rubber, metal, paint, glass, deck_mat]

    bm = bmesh.new()
    hull_h = height * 0.55
    before = _snapshot(bm)
    hull_verts = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    bmesh.ops.scale(bm, vec=Vector((length, width, hull_h)), verts=hull_verts)
    bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, hull_h / 2.0)), verts=hull_verts)
    for v in hull_verts:
        if v.co.x < -length * 0.1:
            factor = min((-v.co.x - length * 0.1) / (length * 0.4), 1.0)
            v.co.y *= (1.0 - 0.90 * factor)
            if v.co.z < height * 0.2:
                v.co.z += factor * height * 0.18
    _tag_new(bm, before, 2)
    _add_box(bm, (0.0, 0.0, hull_h + height * 0.03),
             (length * 0.92, width * 0.92, height * 0.06), 4)
    for sy in (-1.0, 1.0):
        _add_box(bm, (-length * 0.02, sy * (width * 0.46 - 0.03),
                      hull_h + height * 0.09),
                 (length * 0.90, 0.06, height * 0.12), 2)
    _add_box(bm, (length * 0.02, 0.0, hull_h + height * 0.20),
             (length * 0.12, width * 0.40, height * 0.30), 2)
    _add_box(bm, (length * 0.02 - length * 0.09, 0.0, hull_h + height * 0.38),
             (0.04, width * 0.36, height * 0.18), 3)
    _add_box(bm, (length * 0.30, 0.0, hull_h + height * 0.10),
             (length * 0.10, width * 0.60, height * 0.12), 4)
    _add_box(bm, (length * 0.36, 0.0, hull_h + height * 0.20),
             (length * 0.06, width * 0.60, height * 0.16), 4)
    _add_box(bm, (length * 0.52, 0.0, hull_h + height * 0.10),
             (0.12, 0.24, height * 0.30), 1)
    _add_cylinder(bm, (length * 0.52, 0.0, hull_h - height * 0.05), 0.05,
                  height * 0.25, 1, segments=12, axis="Z")

    obj, dims, polys = _create_object(bm, name, materials)
    return _result(obj, dims, polys, materials,
                   {"length": length, "width": width, "height": height})


def create_aircraft_blockout(server, name="Aircraft", length=8.0,
                             wingspan=10.0, height=2.5) -> dict:
    """Create an aircraft blockout (fuselage, wings, tail, prop, gear)."""
    _check_name(name)
    length = _check_positive("length", length, 1.0, 100.0)
    wingspan = _check_positive("wingspan", wingspan, 1.0, 100.0)
    height = _check_positive("height", height, 0.5, 20.0)

    rubber, metal, paint, glass = _vehicle_materials(name, (0.75, 0.77, 0.80, 1.0))
    materials = [rubber, metal, paint, glass]

    bm = bmesh.new()
    fuse_r = height * 0.18
    fuse_z = height * 0.50
    fuse_len = length * 0.78
    _add_cylinder(bm, (length * 0.01, 0.0, fuse_z), fuse_r, fuse_len,
                  2, segments=20, axis="X")
    _add_sphere(bm, (-fuse_len / 2.0 + length * 0.01, 0.0, fuse_z), fuse_r,
                2, scale=(1.6, 1.0, 1.0))
    before = _snapshot(bm)
    tail_verts = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=20,
        radius1=fuse_r, radius2=fuse_r * 0.25, depth=length * 0.20,
    )["verts"]
    bmesh.ops.rotate(bm, cent=Vector((0.0, 0.0, 0.0)),
                     matrix=Matrix.Rotation(math.pi / 2.0, 3, "Y"), verts=tail_verts)
    bmesh.ops.translate(bm, vec=Vector((fuse_len / 2.0 + length * 0.01
                                        + length * 0.10, 0.0, fuse_z)),
                        verts=tail_verts)
    _tag_new(bm, before, 2)
    wing_thick = max(height * 0.035, 0.02)
    _add_box(bm, (length * 0.02, 0.0, fuse_z - fuse_r * 0.2),
             (length * 0.22, wingspan, wing_thick), 2)
    _add_box(bm, (length * 0.40, 0.0, fuse_z + fuse_r * 0.7),
             (length * 0.12, wingspan * 0.32, wing_thick * 0.8), 2)
    _add_box(bm, (length * 0.40, 0.0, fuse_z + fuse_r * 0.7 + height * 0.14),
             (length * 0.12, wing_thick * 0.8, height * 0.28), 2)
    _add_sphere(bm, (-length * 0.12, 0.0, fuse_z + fuse_r * 0.75),
                fuse_r * 0.55, 3, scale=(1.8, 0.9, 0.7))
    nose_x = -fuse_len / 2.0 + length * 0.01 - fuse_r * 1.6
    _add_sphere(bm, (nose_x, 0.0, fuse_z), fuse_r * 0.30, 1)
    blade_len = fuse_r * 2.6
    _add_box(bm, (nose_x - fuse_r * 0.25, 0.0, fuse_z),
             (0.06, blade_len, fuse_r * 0.28), 1)
    _add_box(bm, (nose_x - fuse_r * 0.25, 0.0, fuse_z),
             (0.06, fuse_r * 0.28, blade_len), 1)
    gear_r = max(height * 0.06, 0.03)
    for gx, gy in ((length * 0.05, 0.0), (-length * 0.15, -fuse_r),
                   (-length * 0.15, fuse_r)):
        leg_top = Vector((gx, gy, fuse_z - fuse_r * 0.5))
        _add_tube(bm, leg_top, Vector((gx, gy, gear_r * 2.0)),
                  gear_r * 0.25, 1)
        _add_wheel(bm, (gx, gy, gear_r), gear_r, gear_r * 0.6, 0, 1,
                   segments=16)

    obj, dims, polys = _create_object(bm, name, materials)
    return _result(obj, dims, polys, materials,
                   {"length": length, "wingspan": wingspan, "height": height},
                   {"wheel_count": 3})


def create_robot_blockout(server, name="Robot", height=1.8,
                          build="humanoid") -> dict:
    """Create a robot blockout (humanoid or rover build)."""
    _check_name(name)
    height = _check_positive("height", height, 0.3, 5.0)
    if not isinstance(build, str) or build not in _VALID_ROBOT_BUILDS:
        raise ValueError(f"build must be one of {list(_VALID_ROBOT_BUILDS)}")

    rubber, metal, paint, glass = _vehicle_materials(name, (0.80, 0.35, 0.10, 1.0))
    materials = [rubber, metal, paint, glass]

    bm = bmesh.new()
    if build == "humanoid":
        leg_h = height * 0.42
        leg_w = height * 0.10
        for sx in (-1.0, 1.0):
            _add_box(bm, (0.0, sx * height * 0.08, leg_h / 2.0),
                     (leg_w, leg_w, leg_h), 1)
            _add_box(bm, (-height * 0.03, sx * height * 0.08, height * 0.03),
                     (height * 0.16, leg_w, height * 0.06), 0)
        torso_h = height * 0.30
        torso_z = leg_h + torso_h / 2.0
        _add_box(bm, (0.0, 0.0, torso_z),
                 (height * 0.20, height * 0.30, torso_h), 2)
        _add_box(bm, (0.0, 0.0, torso_z + torso_h * 0.15),
                 (height * 0.10, height * 0.16, torso_h * 0.35), 3)
        shoulder_z = leg_h + torso_h * 0.82
        arm_len = height * 0.32
        for sx in (-1.0, 1.0):
            _add_box(bm, (0.0, sx * (height * 0.15 + height * 0.05),
                          shoulder_z - arm_len / 2.0),
                     (height * 0.08, height * 0.08, arm_len), 1)
            _add_sphere(bm, (0.0, sx * (height * 0.15 + height * 0.05),
                             shoulder_z - arm_len),
                        height * 0.05, 0)
        head_r = height * 0.09
        head_z = leg_h + torso_h + head_r * 0.9
        _add_box(bm, (0.0, 0.0, head_z),
                 (head_r * 1.4, head_r * 1.6, head_r * 1.5), 1)
        for sx in (-1.0, 1.0):
            _add_box(bm, (-head_r * 0.75, sx * head_r * 0.35, head_z + head_r * 0.1),
                     (0.02, head_r * 0.35, head_r * 0.25), 3)
        _add_cylinder(bm, (0.0, 0.0, head_z + head_r * 1.2), 0.012,
                      height * 0.10, 1, segments=8, axis="Z")
    else:
        wheel_r = height * 0.10
        wheel_w = height * 0.08
        body_len = height * 0.75
        body_z = wheel_r * 2.0 + height * 0.14
        _add_box(bm, (0.0, 0.0, body_z),
                 (body_len, height * 0.50, height * 0.28), 2)
        _add_box(bm, (0.0, 0.0, body_z + height * 0.17),
                 (body_len * 0.55, height * 0.40, height * 0.05), 3)
        for sx in (-1.0, 0.0, 1.0):
            for sy in (-1.0, 1.0):
                _add_wheel(bm, (sx * body_len * 0.36, sy * height * 0.28, wheel_r),
                           wheel_r, wheel_w, 0, 1, segments=16)
        _add_cylinder(bm, (-body_len * 0.25, 0.0, body_z + height * 0.30),
                      height * 0.03, height * 0.30, 1, segments=10, axis="Z")
        _add_box(bm, (-body_len * 0.25, 0.0, body_z + height * 0.48),
                 (height * 0.16, height * 0.12, height * 0.10), 1)
        _add_box(bm, (-body_len * 0.25 - height * 0.09, 0.0,
                      body_z + height * 0.48),
                 (0.02, height * 0.10, height * 0.05), 3)

    obj, dims, polys = _create_object(bm, name, materials)
    return _result(obj, dims, polys, materials,
                   {"height": height, "build": build},
                   {"build": build})


def create_drone_blockout(server, name="Drone", span=0.5,
                          height=0.2) -> dict:
    """Create a quadcopter drone blockout (body, arms, rotors, legs)."""
    _check_name(name)
    span = _check_positive("span", span, 0.1, 10.0)
    height = _check_positive("height", height, 0.05, 3.0)

    rubber, metal, paint, glass = _vehicle_materials(name, (0.18, 0.19, 0.22, 1.0))
    rotor_mat = _get_or_create_material(name + "_Rotor", (0.10, 0.10, 0.11, 1.0), 0.5)
    materials = [rubber, metal, paint, glass, rotor_mat]

    bm = bmesh.new()
    body_z = height * 0.55
    body_size = span * 0.30
    _add_box(bm, (0.0, 0.0, body_z),
             (body_size, body_size, height * 0.50), 2)
    _add_sphere(bm, (0.0, 0.0, body_z + height * 0.25), body_size * 0.35,
                2, scale=(1.0, 1.0, 0.6))
    arm_len = span * 0.32
    motor_r = span * 0.035
    motor_z = body_z + height * 0.10
    for i in range(4):
        angle = math.pi / 4.0 + i * math.pi / 2.0
        _add_box_rotated(bm, (0.0, 0.0, body_z),
                         angle, (arm_len / 2.0, 0.0, 0.0),
                         (arm_len, span * 0.05, height * 0.12), 1)
        motor_pos = (math.cos(angle) * arm_len, math.sin(angle) * arm_len, motor_z)
        _add_cylinder(bm, motor_pos, motor_r, height * 0.22, 1,
                      segments=12, axis="Z")
        blade_angle = angle + math.pi / 2.0
        _add_box_rotated(bm, motor_pos, blade_angle, (0.0, 0.0, height * 0.13),
                         (span * 0.045, span * 0.30, height * 0.03), 4)
        leg_base = Vector((math.cos(angle) * body_size * 0.35,
                           math.sin(angle) * body_size * 0.35, body_z - height * 0.25))
        _add_tube(bm, leg_base, Vector((leg_base.x * 1.6, leg_base.y * 1.6, 0.0)),
                  max(span * 0.012, 0.003), 1, segments=8)
    _add_sphere(bm, (-body_size * 0.45, 0.0, body_z - height * 0.12),
                span * 0.04, 3)

    obj, dims, polys = _create_object(bm, name, materials)
    return _result(obj, dims, polys, materials,
                   {"span": span, "height": height},
                   {"rotor_count": 4})
