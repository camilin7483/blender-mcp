"""Procedural water surfaces (planes, rivers, ponds) and water shaders."""

import math

import bpy
import bmesh
from mathutils import Vector

_DEFAULT_WATER_COLOR = (0.05, 0.25, 0.35, 1.0)
_WATER_IOR = 1.33
_BUMP_STRENGTH = 0.3
_BUMP_DISTANCE = 0.1
_DEFAULT_RIVER_POINTS = (
    (-5.0, 0.0, 0.0),
    (-2.5, 1.0, 0.0),
    (0.0, 0.0, 0.0),
    (2.5, -1.0, 0.0),
    (5.0, 0.0, 0.0),
)


def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def _as_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number.")
    return result


def _as_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    return value


def _validate_color(color):
    if not isinstance(color, (list, tuple)) or len(color) not in (3, 4):
        raise ValueError("color must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1].")
    channels = []
    for channel in color:
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            raise ValueError("color must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1].")
        value = float(channel)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("color must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1].")
        channels.append(value)
    if len(channels) == 3:
        channels.append(1.0)
    return tuple(channels)


def _check_range(value, label, minimum=None, maximum=None):
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum}.")
    return value


def _link_object(obj):
    collection = getattr(bpy.context, "collection", None)
    if collection is None:
        collection = bpy.context.scene.collection
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    obj.select_set(True)
    try:
        bpy.context.view_layer.objects.active = obj
    except Exception:
        pass


def _shade_smooth(obj):
    try:
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
    except Exception:
        pass


def _wave_height_at(x, y, amplitude, scale):
    return amplitude * (
        0.5 * math.sin(x * scale * 0.9) * math.cos(y * scale * 0.9)
        + 0.25 * math.sin((x + y) * scale * 0.5)
    )


def _find_input(node, names):
    for candidate in names:
        socket = node.inputs.get(candidate)
        if socket is not None:
            return socket
    return None


def _set_socket(node, names, value):
    socket = _find_input(node, names)
    if socket is not None:
        socket.default_value = value


def _build_water_material(name, color, roughness, transmission, wave_scale):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)

    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (400.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (100.0, 0.0)
    tex_coord = tree.nodes.new(type="ShaderNodeTexCoord")
    tex_coord.name = "Texture Coordinate"
    tex_coord.location = (-700.0, 0.0)
    mapping = tree.nodes.new(type="ShaderNodeMapping")
    mapping.name = "Mapping"
    mapping.location = (-500.0, 0.0)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Water Noise"
    noise.location = (-300.0, 0.0)
    bump = tree.nodes.new(type="ShaderNodeBump")
    bump.name = "Water Bump"
    bump.location = (-100.0, -200.0)

    _set_socket(bsdf, ("Base Color",), color)
    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Roughness",), roughness)
    _set_socket(bsdf, ("IOR",), _WATER_IOR)
    _set_socket(bsdf, ("Transmission Weight", "Transmission"), transmission)
    _set_socket(noise, ("Scale",), wave_scale)
    _set_socket(noise, ("Detail",), 2.0)
    _set_socket(bump, ("Strength",), _BUMP_STRENGTH)
    _set_socket(bump, ("Distance",), _BUMP_DISTANCE)

    links = tree.links
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    normal_socket = _find_input(bsdf, ("Normal",))
    if normal_socket is not None:
        links.new(bump.outputs["Normal"], normal_socket)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return material


def _assign_material(obj, material):
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)


def create_water_material(server, name="WaterMaterial",
                          color=(0.05, 0.25, 0.35, 1.0), roughness=0.1,
                          transmission=0.6, wave_scale=1.5) -> dict:
    """Create a Principled BSDF water shader with a subtle noise bump."""
    name = _validate_name(name)
    color = _validate_color(color)
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)
    transmission = _check_range(_as_number(transmission, "transmission"), "transmission", 0.0, 1.0)
    wave_scale = _as_number(wave_scale, "wave_scale")
    _check_range(wave_scale, "wave_scale", minimum=0.001, maximum=1000.0)

    material = _build_water_material(name, color, roughness, transmission, wave_scale)
    nodes = {node.name: node.bl_idname for node in material.node_tree.nodes}
    return {
        "success": True,
        "material": material.name,
        "nodes": nodes,
        "color": list(color),
        "roughness": roughness,
        "transmission": transmission,
        "wave_scale": wave_scale,
        "ior": _WATER_IOR,
    }


def create_water_plane(server, name="Water", size=10.0, subdivisions=64,
                       wave_height=0.08, wave_scale=1.5,
                       color=(0.05, 0.25, 0.35, 1.0), roughness=0.15) -> dict:
    """Create a subdivided water plane with low-amplitude sine waves."""
    name = _validate_name(name)
    size = _as_number(size, "size")
    _check_range(size, "size", minimum=0.001, maximum=1000.0)
    subdivisions = _as_int(subdivisions, "subdivisions")
    _check_range(subdivisions, "subdivisions", minimum=1, maximum=256)
    wave_height = _as_number(wave_height, "wave_height")
    _check_range(wave_height, "wave_height", minimum=0.0, maximum=10.0)
    wave_scale = _as_number(wave_scale, "wave_scale")
    _check_range(wave_scale, "wave_scale", minimum=0.001, maximum=1000.0)
    color = _validate_color(color)
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)

    half = size / 2.0
    bm = bmesh.new()
    grid = []
    for iy in range(subdivisions + 1):
        row = []
        y = -half + size * iy / subdivisions
        for ix in range(subdivisions + 1):
            x = -half + size * ix / subdivisions
            z = _wave_height_at(x, y, wave_height, wave_scale)
            row.append(bm.verts.new((x, y, z)))
        grid.append(row)
    bm.verts.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    for iy in range(subdivisions):
        for ix in range(subdivisions):
            v0 = grid[iy][ix]
            v1 = grid[iy][ix + 1]
            v2 = grid[iy + 1][ix + 1]
            v3 = grid[iy + 1][ix]
            face = bm.faces.new((v0, v1, v2, v3))
            for loop, vert in zip(face.loops, (v0, v1, v2, v3)):
                loop[uv_layer].uv = (
                    (vert.co.x + half) / size,
                    (vert.co.y + half) / size,
                )

    mesh = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    _link_object(obj)
    _shade_smooth(obj)

    material = _build_water_material(
        obj.name + "_Material", color, roughness, 0.6, wave_scale)
    _assign_material(obj, material)

    return {
        "success": True,
        "name": obj.name,
        "material": material.name,
        "size": size,
        "dimensions": [size, size],
        "subdivisions": subdivisions,
        "wave_height": wave_height,
        "wave_scale": wave_scale,
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
    }


def _validate_points(points):
    if points is None:
        return [Vector(item) for item in _DEFAULT_RIVER_POINTS]
    if not isinstance(points, (list, tuple)) or len(points) < 2:
        raise ValueError("points must be a sequence of at least two (x, y, z) coordinates.")
    if len(points) > 1024:
        raise ValueError("points must contain at most 1024 control points.")
    result = []
    for index, item in enumerate(points):
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise ValueError(f"points[{index}] must be an (x, y, z) sequence of 3 numbers.")
        coords = []
        for channel in item:
            if isinstance(channel, bool) or not isinstance(channel, (int, float)):
                raise ValueError(f"points[{index}] coordinates must be finite numbers.")
            value = float(channel)
            if not math.isfinite(value):
                raise ValueError(f"points[{index}] coordinates must be finite numbers.")
            coords.append(value)
        result.append(Vector(coords))
    return result


def _resample_polyline(points, segments):
    cumulative = [0.0]
    for first, second in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + (second - first).length)
    total = cumulative[-1]
    if total <= 1e-9:
        raise ValueError("points define a zero-length path; provide at least two distinct points.")
    samples = []
    span_index = 0
    for i in range(segments + 1):
        distance = total * i / segments
        while span_index < len(cumulative) - 2 and cumulative[span_index + 1] < distance:
            span_index += 1
        first = points[span_index]
        second = points[span_index + 1]
        span = cumulative[span_index + 1] - cumulative[span_index]
        factor = 0.0 if span <= 1e-12 else (distance - cumulative[span_index]) / span
        samples.append(first.lerp(second, factor))
    return samples, total


def create_river(server, name="River", points=None, width=2.0, depth=0.2,
                 segments=32) -> dict:
    """Create a ribbon-mesh river following a gently curved path."""
    name = _validate_name(name)
    path = _validate_points(points)
    width = _as_number(width, "width")
    _check_range(width, "width", minimum=0.001, maximum=1000.0)
    depth = _as_number(depth, "depth")
    _check_range(depth, "depth", minimum=0.0, maximum=100.0)
    segments = _as_int(segments, "segments")
    _check_range(segments, "segments", minimum=1, maximum=512)

    samples, length = _resample_polyline(path, segments)
    half_width = width / 2.0
    bm = bmesh.new()
    left, center, right = [], [], []
    prev_nx, prev_ny = 1.0, 0.0
    for i, sample in enumerate(samples):
        prev = samples[max(i - 1, 0)]
        nxt = samples[min(i + 1, segments)]
        tangent = nxt - prev
        axis = math.hypot(tangent.x, tangent.y)
        if axis < 1e-8:
            nx, ny = prev_nx, prev_ny
        else:
            nx, ny = -tangent.y / axis, tangent.x / axis
            prev_nx, prev_ny = nx, ny
        base_z = sample.z
        left.append(bm.verts.new((
            sample.x + nx * half_width, sample.y + ny * half_width, base_z)))
        center.append(bm.verts.new((sample.x, sample.y, base_z - depth)))
        right.append(bm.verts.new((
            sample.x - nx * half_width, sample.y - ny * half_width, base_z)))
    bm.verts.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    for i in range(segments):
        u0 = i / segments
        u1 = (i + 1) / segments
        left_face = bm.faces.new((left[i], center[i], center[i + 1], left[i + 1]))
        for loop, uv in zip(left_face.loops, ((u0, 0.0), (u0, 0.5), (u1, 0.5), (u1, 0.0))):
            loop[uv_layer].uv = uv
        right_face = bm.faces.new((center[i], right[i], right[i + 1], center[i + 1]))
        for loop, uv in zip(right_face.loops, ((u0, 0.5), (u0, 1.0), (u1, 1.0), (u1, 0.5))):
            loop[uv_layer].uv = uv

    mesh = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    _link_object(obj)
    _shade_smooth(obj)

    material = _build_water_material(
        obj.name + "_Material", _DEFAULT_WATER_COLOR, 0.15, 0.6, 1.5)
    _assign_material(obj, material)

    return {
        "success": True,
        "name": obj.name,
        "material": material.name,
        "length": length,
        "width": width,
        "depth": depth,
        "segments": segments,
        "control_points": len(path),
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
    }


def create_pond(server, name="Pond", radius=3.0, depth=0.4, segments=48) -> dict:
    """Create a circular pond with a depressed bed and a raised rim."""
    name = _validate_name(name)
    radius = _as_number(radius, "radius")
    _check_range(radius, "radius", minimum=0.001, maximum=1000.0)
    depth = _as_number(depth, "depth")
    _check_range(depth, "depth", minimum=0.0, maximum=100.0)
    segments = _as_int(segments, "segments")
    _check_range(segments, "segments", minimum=3, maximum=256)

    rings = [
        (radius * 0.5, -depth * 0.6),
        (radius, 0.0),
        (radius * 1.25, depth * 0.35),
    ]
    extent = radius * 1.25
    bm = bmesh.new()
    bed = bm.verts.new((0.0, 0.0, -depth))
    ring_verts = []
    for ring_radius, ring_z in rings:
        row = []
        for j in range(segments):
            angle = 2.0 * math.pi * j / segments
            row.append(bm.verts.new((
                ring_radius * math.cos(angle),
                ring_radius * math.sin(angle),
                ring_z,
            )))
        ring_verts.append(row)
    bm.verts.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.new("UVMap")

    def _planar_uv(vert):
        return ((vert.co.x + extent) / (2.0 * extent),
                (vert.co.y + extent) / (2.0 * extent))

    inner, middle, outer = ring_verts
    for j in range(segments):
        fan = bm.faces.new((bed, inner[j], inner[(j + 1) % segments]))
        for loop in fan.loops:
            loop[uv_layer].uv = _planar_uv(loop.vert)
    for lower, upper in ((inner, middle), (middle, outer)):
        for j in range(segments):
            quad = bm.faces.new((
                lower[j], lower[(j + 1) % segments],
                upper[(j + 1) % segments], upper[j],
            ))
            for loop in quad.loops:
                loop[uv_layer].uv = _planar_uv(loop.vert)

    mesh = bpy.data.meshes.new(name + "Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    _link_object(obj)
    _shade_smooth(obj)

    material = _build_water_material(
        obj.name + "_Material", _DEFAULT_WATER_COLOR, 0.15, 0.6, 1.5)
    _assign_material(obj, material)

    return {
        "success": True,
        "name": obj.name,
        "material": material.name,
        "radius": radius,
        "depth": depth,
        "rim_radius": radius * 1.25,
        "rim_height": depth * 0.35,
        "segments": segments,
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
    }
