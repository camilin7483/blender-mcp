"""Procedural terrain, sculpting, scattering and rock tools (domain pack).

Runs on Blender's main thread. Uses only ``bpy``, ``bmesh``, ``mathutils``
and the standard library. All functions validate their inputs, raise
``ValueError`` with a precise message on bad input, and return plain
JSON-serializable dictionaries. Results are deterministic for a given
``seed``.
"""

import bisect
import math
import random

import bpy
import bmesh
from mathutils import Matrix, Quaternion, Vector

_MASK64 = 0xFFFFFFFFFFFFFFFF
_NORM64 = 18446744073709551616.0

_TERRAIN_STYLES = ("mountains", "hills", "dunes", "flat")
_SMOOTHNESS_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Deterministic value noise (pure Python, platform independent)
# ---------------------------------------------------------------------------

def _mix_hash(state):
    """Avalanche an integer state into a float in [0, 1)."""
    state = (state + 0x9E3779B97F4A7C15) & _MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    z = (z ^ (z >> 31)) & _MASK64
    return z / _NORM64


def _hash2(ix, iy, seed):
    key = ((ix * 0x8DA6B343) ^ (iy * 0xD8163841) ^ (seed * 0x9E3779B9)) & _MASK64
    return _mix_hash(key ^ 0x6A09E667F3BCC909)


def _hash3(ix, iy, iz, seed):
    key = (
        (ix * 0x8DA6B343)
        ^ (iy * 0xD8163841)
        ^ (iz * 0xB5297A4D)
        ^ (seed * 0x9E3779B9)
    ) & _MASK64
    return _mix_hash(key ^ 0x510E527FADE682D1)


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _value_noise2(x, y, seed):
    xi = math.floor(x)
    yi = math.floor(y)
    xf = x - xi
    yf = y - yi
    u = _fade(xf)
    v = _fade(yf)
    a = _hash2(xi, yi, seed)
    b = _hash2(xi + 1, yi, seed)
    c = _hash2(xi, yi + 1, seed)
    d = _hash2(xi + 1, yi + 1, seed)
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v


def _fbm2(x, y, octaves, seed):
    total = 0.0
    amplitude = 0.5
    frequency = 1.0
    norm = 0.0
    for octave in range(octaves):
        total += amplitude * _value_noise2(x * frequency, y * frequency, seed + octave * 7919)
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return total / norm if norm else 0.0


def _value_noise3(x, y, z, seed):
    xi = math.floor(x)
    yi = math.floor(y)
    zi = math.floor(z)
    xf = x - xi
    yf = y - yi
    zf = z - zi
    u = _fade(xf)
    v = _fade(yf)
    w = _fade(zf)
    c000 = _hash3(xi, yi, zi, seed)
    c100 = _hash3(xi + 1, yi, zi, seed)
    c010 = _hash3(xi, yi + 1, zi, seed)
    c110 = _hash3(xi + 1, yi + 1, zi, seed)
    c001 = _hash3(xi, yi, zi + 1, seed)
    c101 = _hash3(xi + 1, yi, zi + 1, seed)
    c011 = _hash3(xi, yi + 1, zi + 1, seed)
    c111 = _hash3(xi + 1, yi + 1, zi + 1, seed)
    x00 = c000 + (c100 - c000) * u
    x10 = c010 + (c110 - c010) * u
    x01 = c001 + (c101 - c001) * u
    x11 = c011 + (c111 - c011) * u
    y0 = x00 + (x10 - x00) * v
    y1 = x01 + (x11 - x01) * v
    return y0 + (y1 - y0) * w


def _fbm3(x, y, z, octaves, seed):
    total = 0.0
    amplitude = 0.5
    frequency = 1.0
    norm = 0.0
    for octave in range(octaves):
        total += amplitude * _value_noise3(
            x * frequency, y * frequency, z * frequency, seed + octave * 7919
        )
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.03
    return total / norm if norm else 0.0


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _require_positive_number(value, label):
    if not _is_number(value) or not math.isfinite(float(value)) or float(value) <= 0.0:
        raise ValueError(f"{label} must be a positive finite number (got {value!r})")
    return float(value)


def _require_non_negative_number(value, label):
    if not _is_number(value) or not math.isfinite(float(value)) or float(value) < 0.0:
        raise ValueError(f"{label} must be a non-negative finite number (got {value!r})")
    return float(value)


def _require_seed(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"seed must be an integer (got {value!r})")
    return value


def _require_object(object_name, label="object_name"):
    clean = _require_name(object_name, label)
    obj = bpy.data.objects.get(clean)
    if obj is None:
        raise ValueError(f"Object '{clean}' not found")
    return obj


def _require_mesh_object(obj):
    if obj.type != "MESH":
        raise ValueError(f"Object '{obj.name}' must be a MESH (got {obj.type})")
    if obj.data is None or len(obj.data.vertices) == 0:
        raise ValueError(f"Object '{obj.name}' has no mesh vertices")
    return obj


def _set_smooth_shading(mesh, smooth):
    try:
        for polygon in mesh.polygons:
            polygon.use_smooth = smooth
    except AttributeError:
        pass
    mesh.update()


def _link_object(obj, reference=None):
    collections = getattr(reference, "users_collection", None) if reference else None
    target = collections[0] if collections else bpy.context.scene.collection
    target.objects.link(obj)
    return target.name


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------

def _terrain_raw_height(style, nx, ny, seed, warp_noise):
    if style == "mountains":
        base = _fbm2(nx, ny, 5, seed)
        ridge = 1.0 - abs(2.0 * base - 1.0)
        detail = _fbm2(nx * 2.7 + 13.1, ny * 2.7 + 7.7, 3, seed + 101)
        return 0.7 * (ridge ** 1.5) + 0.3 * detail
    if style == "hills":
        return _fbm2(nx * 0.8, ny * 0.8, 4, seed)
    if style == "dunes":
        warp = (warp_noise - 0.5) * 1.4
        phase = nx * 1.2 + warp
        crest = 1.0 - abs(2.0 * (phase - math.floor(phase)) - 1.0)
        detail = _fbm2(nx * 2.0 + 3.3, ny * 2.0 + 9.1, 2, seed + 202)
        return 0.8 * (crest ** 1.5) + 0.2 * detail
    return _fbm2(nx, ny, 1, seed)


def create_terrain(server, name="Terrain", size=10.0, subdivisions=64,
                   height=1.0, noise_scale=2.0, seed=0, style="mountains"):
    """Create a displaced grid terrain with multi-octave noise."""
    _ = server
    clean_name = _require_name(name)
    size = _require_positive_number(size, "size")
    if isinstance(subdivisions, bool) or not isinstance(subdivisions, int):
        raise ValueError(f"subdivisions must be an integer (got {subdivisions!r})")
    if subdivisions < 1 or subdivisions > 256:
        raise ValueError(f"subdivisions must be between 1 and 256 (got {subdivisions})")
    height = _require_non_negative_number(height, "height")
    noise_scale = _require_positive_number(noise_scale, "noise_scale")
    seed = _require_seed(seed)
    if not isinstance(style, str):
        raise ValueError(f"style must be a string (got {style!r})")
    style_key = style.strip().lower()
    if style_key not in _TERRAIN_STYLES:
        raise ValueError(
            f"Unknown style '{style}'. Expected one of {sorted(_TERRAIN_STYLES)}"
        )

    rng = random.Random(seed)
    offset_x = rng.uniform(-256.0, 256.0)
    offset_y = rng.uniform(-256.0, 256.0)
    seed_masked = seed & _MASK64

    step = size / subdivisions
    half = size / 2.0
    xs = [-half + i * step for i in range(subdivisions + 1)]

    raw = []
    for j in range(subdivisions + 1):
        y = xs[j]
        for i in range(subdivisions + 1):
            x = xs[i]
            nx = (x / size + 0.5) * noise_scale + offset_x
            ny = (y / size + 0.5) * noise_scale + offset_y
            warp = _fbm2(nx * 0.7 + 5.2, ny * 0.7 + 1.3, 2, seed_masked + 303)
            raw.append(_terrain_raw_height(style_key, nx, ny, seed_masked, warp))

    if style_key == "flat":
        # Nearly planar micro-relief proportional to height.
        heights = [(value - 0.5) * height * 0.04 for value in raw]
    else:
        raw_min = min(raw)
        raw_max = max(raw)
        span = raw_max - raw_min
        if height == 0.0 or span <= 0.0:
            heights = [0.0] * len(raw)
        else:
            heights = [(value - raw_min) / span * height for value in raw]

    verts = []
    index = 0
    for j in range(subdivisions + 1):
        for i in range(subdivisions + 1):
            verts.append((xs[i], xs[j], heights[index]))
            index += 1

    row = subdivisions + 1
    faces = []
    for j in range(subdivisions):
        for i in range(subdivisions):
            a = j * row + i
            faces.append((a, a + 1, a + 1 + row, a + row))

    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)
    _set_smooth_shading(mesh, True)
    bpy.context.view_layer.update()

    min_z = min(heights)
    max_z = max(heights)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "style": style_key,
        "size": size,
        "subdivisions": subdivisions,
        "height": height,
        "noise_scale": noise_scale,
        "seed": seed,
        "dimensions": [round(size, 6), round(size, 6), round(max_z - min_z, 6)],
        "vertex_count": len(verts),
        "face_count": len(faces),
        "min_z": round(min_z, 6),
        "max_z": round(max_z, 6),
    }


def sculpt_terrain_region(server, object_name, center=(0.0, 0.0, 0.0),
                          radius=1.0, strength=0.5, direction="UP"):
    """Raise or lower a radial region of a mesh with smooth falloff."""
    _ = server
    obj = _require_mesh_object(_require_object(object_name))
    try:
        cx, cy, cz = (float(v) for v in center)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"center must be a sequence of 3 numbers (got {center!r})"
        ) from exc
    if any(not math.isfinite(v) for v in (cx, cy, cz)):
        raise ValueError(f"center coordinates must be finite (got {center!r})")
    radius = _require_positive_number(radius, "radius")
    strength = _require_non_negative_number(strength, "strength")
    if not isinstance(direction, str):
        raise ValueError(f"direction must be 'UP' or 'DOWN' (got {direction!r})")
    direction_key = direction.strip().upper()
    if direction_key not in ("UP", "DOWN"):
        raise ValueError(f"direction must be 'UP' or 'DOWN' (got {direction!r})")
    sign = 1.0 if direction_key == "UP" else -1.0

    bpy.context.view_layer.update()
    matrix = obj.matrix_world.copy()
    inv_matrix = matrix.inverted()
    world_center = Vector((cx, cy, cz))

    vertex_count_before = len(obj.data.vertices)
    face_count_before = len(obj.data.polygons)

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        moved = 0
        for vert in bm.verts:
            world = matrix @ vert.co
            dist = math.hypot(world.x - world_center.x, world.y - world_center.y)
            if dist < radius:
                falloff = 0.5 * (1.0 + math.cos(math.pi * dist / radius))
                local = inv_matrix @ (world + Vector((0.0, 0.0, sign * strength * falloff)))
                vert.co = local
                moved += 1
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    bpy.context.view_layer.update()

    matrix = obj.matrix_world.copy()
    world_verts = [matrix @ v.co for v in obj.data.vertices]
    min_z = min(v.z for v in world_verts)
    max_z = max(v.z for v in world_verts)
    bounds_min = [
        round(min(v.x for v in world_verts), 6),
        round(min(v.y for v in world_verts), 6),
        round(min_z, 6),
    ]
    bounds_max = [
        round(max(v.x for v in world_verts), 6),
        round(max(v.y for v in world_verts), 6),
        round(max_z, 6),
    ]
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "direction": direction_key,
        "center": [cx, cy, cz],
        "radius": radius,
        "strength": strength,
        "moved_count": moved,
        "vertex_count": len(obj.data.vertices),
        "face_count": len(obj.data.polygons),
        "vertices_unchanged": len(obj.data.vertices) == vertex_count_before
        and len(obj.data.polygons) == face_count_before,
        "min_z": round(min_z, 6),
        "max_z": round(max_z, 6),
        "bounds_min": bounds_min,
        "bounds_max": bounds_max,
    }


def scatter_objects(server, source_name, target_name, count=50, seed=0,
                    scale_min=0.8, scale_max=1.2, align_to_normal=True):
    """Scatter linked duplicates of a source object over a target surface."""
    _ = server
    source = _require_object(source_name, "source_name")
    target = _require_mesh_object(_require_object(target_name, "target_name"))
    if source == target:
        raise ValueError("source_name and target_name must be different objects")
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError(f"count must be an integer (got {count!r})")
    if count < 0:
        raise ValueError(f"count must be >= 0 (got {count})")
    scale_min = _require_positive_number(scale_min, "scale_min")
    scale_max = _require_positive_number(scale_max, "scale_max")
    if scale_min > scale_max:
        raise ValueError(
            f"scale_min ({scale_min}) must not exceed scale_max ({scale_max})"
        )
    seed = _require_seed(seed)
    if not isinstance(align_to_normal, bool):
        raise ValueError(f"align_to_normal must be a boolean (got {align_to_normal!r})")

    if count == 0:
        return {
            "success": True,
            "source": source.name,
            "target": target.name,
            "count": 0,
            "requested": 0,
            "instances": [],
            "align_to_normal": align_to_normal,
            "scale_min": scale_min,
            "scale_max": scale_max,
            "seed": seed,
        }

    rng = random.Random(seed)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = target.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    try:
        polygons = eval_mesh.polygons
        if len(polygons) == 0:
            raise ValueError(f"Object '{target.name}' has no evaluated faces")
        matrix = eval_obj.matrix_world.copy()
        rotation = matrix.to_3x3()
        areas = [float(p.area) for p in polygons]
        total_area = sum(areas)
        if total_area <= 0.0:
            raise ValueError(f"Object '{target.name}' has no surface area to scatter on")
        cumulative = []
        running = 0.0
        for area in areas:
            running += area
            cumulative.append(running)

        samples = []
        for _ in range(count):
            pick = rng.random() * total_area
            poly_index = bisect.bisect_left(cumulative, pick, 0, len(cumulative) - 1)
            poly = polygons[min(poly_index, len(polygons) - 1)]
            corners = [matrix @ eval_mesh.vertices[i].co for i in poly.vertices]
            normal = (rotation @ poly.normal).normalized()
            # Fan triangulation around the first corner, area-weighted.
            tri_areas = []
            tri_total = 0.0
            for k in range(1, len(corners) - 1):
                edge_a = corners[k] - corners[0]
                edge_b = corners[k + 1] - corners[0]
                area = 0.5 * edge_a.cross(edge_b).length
                tri_areas.append(area)
                tri_total += area
            if tri_total <= 0.0:
                point = corners[0].copy()
            else:
                choice = rng.random() * tri_total
                acc = 0.0
                tri = 0
                for k, area in enumerate(tri_areas):
                    acc += area
                    if choice <= acc:
                        tri = k
                        break
                a = corners[0]
                b = corners[tri + 1]
                c = corners[tri + 2]
                r1 = rng.random()
                r2 = rng.random()
                if r1 + r2 > 1.0:
                    r1, r2 = 1.0 - r1, 1.0 - r2
                point = a + (b - a) * r1 + (c - a) * r2
            samples.append((point, normal))
    finally:
        eval_obj.to_mesh_clear()

    bpy.context.view_layer.update()
    target_matrix = target.matrix_world.copy()
    source_quat = source.matrix_world.to_quaternion()
    source_scale = source.matrix_world.to_scale()
    up = Vector((0.0, 0.0, 1.0))

    instances = []
    for i, (point, normal) in enumerate(samples):
        factor = rng.uniform(scale_min, scale_max)
        if align_to_normal:
            src_up = (source_quat @ up).normalized()
            if src_up.length < 1e-9:
                src_up = up
            align = src_up.rotation_difference(normal)
            spin = Quaternion(normal, rng.uniform(0.0, 2.0 * math.pi))
            quat = spin @ align @ source_quat
        else:
            spin = Quaternion(up, rng.uniform(0.0, 2.0 * math.pi))
            quat = spin @ source_quat
        scale = Vector((
            source_scale.x * factor,
            source_scale.y * factor,
            source_scale.z * factor,
        ))
        inst = source.copy()
        inst.name = f"{source.name}_scatter_{i + 1:04d}"
        _link_object(inst, target)
        inst.parent = target
        inst.matrix_parent_inverse = target_matrix.inverted()
        inst.matrix_world = Matrix.LocRotScale(point, quat, scale)
        instances.append(inst.name)

    bpy.context.view_layer.update()
    return {
        "success": True,
        "source": source.name,
        "target": target.name,
        "count": len(instances),
        "requested": count,
        "instances": instances,
        "align_to_normal": align_to_normal,
        "scale_min": scale_min,
        "scale_max": scale_max,
        "seed": seed,
    }


def create_rock(server, name="Rock", size=1.0, roughness=0.35, seed=0,
                subdivisions=2):
    """Create a noise-displaced icosphere rock."""
    _ = server
    clean_name = _require_name(name)
    size = _require_positive_number(size, "size")
    if not _is_number(roughness) or not math.isfinite(float(roughness)):
        raise ValueError(f"roughness must be a finite number (got {roughness!r})")
    roughness = float(roughness)
    if roughness < 0.0 or roughness > 1.0:
        raise ValueError(f"roughness must be between 0.0 and 1.0 (got {roughness})")
    seed = _require_seed(seed)
    if isinstance(subdivisions, bool) or not isinstance(subdivisions, int):
        raise ValueError(f"subdivisions must be an integer (got {subdivisions!r})")
    if subdivisions < 1 or subdivisions > 5:
        raise ValueError(f"subdivisions must be between 1 and 5 (got {subdivisions})")

    rng = random.Random(seed)
    offset = Vector((
        rng.uniform(-64.0, 64.0),
        rng.uniform(-64.0, 64.0),
        rng.uniform(-64.0, 64.0),
    ))
    seed_masked = seed & _MASK64
    radius = size / 2.0

    bm = bmesh.new()
    try:
        bmesh.ops.create_icosphere(
            bm, subdivisions=subdivisions, radius=radius, calc_uvs=False
        )
        bm.verts.ensure_lookup_table()
        for vert in bm.verts:
            direction = vert.co.normalized()
            noise = _fbm3(
                direction.x * 1.8 + offset.x,
                direction.y * 1.8 + offset.y,
                direction.z * 1.8 + offset.z,
                3,
                seed_masked,
            )
            vert.co = vert.co * (1.0 + (noise - 0.5) * 2.0 * roughness)
        # Rescale so the largest dimension matches the requested size.
        coords = [v.co for v in bm.verts]
        min_c = Vector((min(c.x for c in coords),
                        min(c.y for c in coords),
                        min(c.z for c in coords)))
        max_c = Vector((max(c.x for c in coords),
                        max(c.y for c in coords),
                        max(c.z for c in coords)))
        extent = max_c - min_c
        largest = max(extent.x, extent.y, extent.z)
        if largest > 1e-9:
            factor = size / largest
            for vert in bm.verts:
                vert.co = vert.co * factor
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        mesh = bpy.data.meshes.new(clean_name + "Mesh")
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()

    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)
    smooth = roughness < _SMOOTHNESS_THRESHOLD
    _set_smooth_shading(mesh, smooth)
    bpy.context.view_layer.update()

    coords = [v.co for v in mesh.vertices]
    min_c = [min(c[i] for c in coords) for i in range(3)]
    max_c = [max(c[i] for c in coords) for i in range(3)]
    dims = [round(max_c[i] - min_c[i], 6) for i in range(3)]
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "size": size,
        "roughness": roughness,
        "subdivisions": subdivisions,
        "seed": seed,
        "shading": "smooth" if smooth else "flat",
        "dimensions": dims,
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "face_count": len(mesh.polygons),
        "min_bound": [round(v, 6) for v in min_c],
        "max_bound": [round(v, 6) for v in max_c],
    }
