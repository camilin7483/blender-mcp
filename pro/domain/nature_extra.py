"""Extra nature dressing tools: forest, grass field, rocks, mountains, cave, island, waterfall, biome (domain pack).

Runs on Blender's main thread. Uses only ``bpy``, ``bmesh``, ``mathutils``
and the standard library. All functions validate their inputs, raise
``ValueError`` with a precise message on bad input, and return plain
JSON-serializable dictionaries. Results are deterministic for a given
``seed``. Compatible with Blender 4.5 LTS and 5.2 LTS.
"""

import math
import random

import bpy
import bmesh
from mathutils import Matrix, Vector

_MASK64 = 0xFFFFFFFFFFFFFFFF
_NORM64 = 18446744073709551616.0

_TREE_TYPES = ("deciduous", "conifer", "palm")


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


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _require_positive(value, label, maximum=1000.0):
    if not _is_number(value) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a positive finite number (got {value!r})")
    number = float(value)
    if number <= 0.0 or number > maximum:
        raise ValueError(f"{label} must be within (0, {maximum}] (got {value!r})")
    return number


def _require_seed(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"seed must be an integer (got {value!r})")
    return value


def _require_int(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum} (got {value!r})")
    if value < minimum or value > maximum:
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum} (got {value})")
    return value


# ---------------------------------------------------------------------------
# Shared build helpers
# ---------------------------------------------------------------------------

def _get_material(name, rgba, roughness=0.8, metallic=0.0):
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


def _link(obj):
    try:
        collection = bpy.context.collection or bpy.context.scene.collection
    except AttributeError:
        collection = bpy.context.scene.collection
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


def _mesh_dims(mesh):
    verts = mesh.vertices
    xs = [v.co.x for v in verts]
    ys = [v.co.y for v in verts]
    zs = [v.co.z for v in verts]
    dims = [round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4), round(max(zs) - min(zs), 4)]
    return dims, round(min(zs), 4), round(max(zs), 4)


def _finish(bm, name, materials, smooth=True, ground=True):
    """Build mesh + object from *bm*, link it, return (object, dims, polys)."""
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    for mat in materials:
        mesh.materials.append(mat)
    if ground and len(mesh.vertices):
        min_z = min(v.co.z for v in mesh.vertices)
        if abs(min_z) > 1e-9:
            for v in mesh.vertices:
                v.co.z -= min_z
            mesh.update()
    _link(obj)
    if smooth:
        try:
            for polygon in mesh.polygons:
                polygon.use_smooth = True
        except AttributeError:
            pass
        mesh.update()
    dims, _, _ = _mesh_dims(mesh)
    return obj, dims, len(mesh.polygons)


def _disc_point(rng, radius):
    dist = radius * math.sqrt(rng.random())
    ang = rng.uniform(0.0, 2.0 * math.pi)
    return math.cos(ang) * dist, math.sin(ang) * dist


def _ground_mesh(mesh):
    if len(mesh.vertices):
        min_z = min(v.co.z for v in mesh.vertices)
        if abs(min_z) > 1e-9:
            for v in mesh.vertices:
                v.co.z -= min_z
            mesh.update()


def _build_local_tree(name, x, y, rng, index, tree_type, height):
    """Fallback single tree (trunk cone + displaced icosphere crown)."""
    bm = bmesh.new()
    bark = _get_material(name + "_Bark", (0.30, 0.20, 0.12, 1.0), 0.95)
    leaf = _get_material(name + "_Leaf", (0.16, 0.42, 0.12, 1.0), 0.85)
    trunk_h = height * 0.5
    trunk_r = max(0.08, height * 0.035)
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=7,
        radius1=trunk_r, radius2=trunk_r * 0.65, depth=trunk_h,
    )
    bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, trunk_h / 2.0)), verts=geo["verts"])
    crown_r = height * 0.28
    center = Vector((0.0, 0.0, trunk_h + crown_r * 0.8))
    geo = bmesh.ops.create_icosphere(
        bm, subdivisions=2, radius=crown_r, matrix=Matrix.Translation(center),
    )
    for v in geo["verts"]:
        direction = v.co - center
        if direction.length < 1e-6:
            direction = Vector((0.0, 0.0, 1.0))
        direction.normalize()
        v.co += direction * rng.uniform(-crown_r * 0.12, crown_r * 0.12)
    obj, _, polys = _finish(bm, name, [bark, leaf])
    obj.location = (x, y, 0.0)
    return obj, polys, tree_type, height


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def create_forest(server, name="Forest", radius=10.0, tree_count=12, seed=0) -> dict:
    """Create a deterministic disc forest of individual tree objects."""
    _ = server
    clean = _require_name(name)
    radius = _require_positive(radius, "radius")
    tree_count = _require_int(tree_count, "tree_count", 1, 500)
    seed = _require_seed(seed)

    rng = random.Random(seed)
    specs = []
    for _ in range(tree_count):
        x, y = _disc_point(rng, radius)
        specs.append({
            "x": x, "y": y,
            "height": rng.uniform(3.0, 5.0),
            "trunk_radius": rng.uniform(0.10, 0.20),
            "crown_radius": rng.uniform(1.0, 1.8),
            "tree_type": _TREE_TYPES[rng.randrange(len(_TREE_TYPES))],
        })

    create_tree = getattr(server, "create_tree", None)
    trees = []
    total_polys = 0
    max_h = 0.0
    for i, spec in enumerate(specs):
        tree_name = f"{clean}_Tree_{i + 1:02d}"
        obj = None
        if callable(create_tree):
            try:
                result = create_tree(
                    name=tree_name, height=spec["height"],
                    trunk_radius=spec["trunk_radius"],
                    crown_radius=spec["crown_radius"],
                    tree_type=spec["tree_type"], seed=seed + i,
                )
                obj_name = result.get("object") if isinstance(result, dict) else None
                obj = bpy.data.objects.get(obj_name) if obj_name else None
                if obj is not None:
                    obj.location = (spec["x"], spec["y"], 0.0)
                    total_polys += len(obj.data.polygons) if obj.data else 0
            except Exception:
                obj = None
        if obj is None:
            obj, polys, _, _ = _build_local_tree(
                tree_name, spec["x"], spec["y"], rng, i, spec["tree_type"], spec["height"])
            total_polys += polys
        trees.append(obj.name)
        max_h = max(max_h, spec["height"])

    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return {
        "success": True,
        "name": clean,
        "trees": trees,
        "count": len(trees),
        "tree_count": len(trees),
        "radius": radius,
        "dimensions": [round(radius * 2.0, 4), round(radius * 2.0, 4), round(max_h, 4)],
        "polygon_count": total_polys,
        "seed": seed,
    }


def create_grass_field(server, name="GrassField", size=10.0, blade_count=100, seed=0) -> dict:
    """Create one joined mesh of tapered grass blades over a square."""
    _ = server
    clean = _require_name(name)
    size = _require_positive(size, "size")
    blade_count = _require_int(blade_count, "blade_count", 1, 20000)
    seed = _require_seed(seed)

    rng = random.Random(seed)
    half = size / 2.0
    bm = bmesh.new()
    green = _get_material(clean + "_Blade", (0.20, 0.48, 0.12, 1.0), 0.9)
    base_h = 0.25
    for _ in range(blade_count):
        bx = rng.uniform(-half, half)
        by = rng.uniform(-half, half)
        h = base_h * rng.uniform(0.7, 1.3)
        w = base_h * 0.12
        lean_ang = rng.uniform(0.0, 2.0 * math.pi)
        lean = base_h * rng.uniform(0.05, 0.35)
        dx, dy = math.cos(lean_ang) * lean, math.sin(lean_ang) * lean
        twist = rng.uniform(0.0, math.pi)
        ca, sa = math.cos(twist), math.sin(twist)
        px, py = ca * w / 2.0, sa * w / 2.0
        ring = []
        for frac, wf in ((0.0, 1.0), (0.45, 0.75), (0.8, 0.45)):
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

    obj, dims, polys = _finish(bm, clean, [green], smooth=False)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "size": size,
        "dimensions": dims,
        "polygon_count": polys,
        "blade_count": blade_count,
        "materials": [green.name],
        "seed": seed,
    }


def create_rock_cluster(server, name="Rocks", radius=3.0, count=8, seed=0) -> dict:
    """Create one joined mesh of displaced rocks scattered in a disc, grounded."""
    _ = server
    clean = _require_name(name)
    radius = _require_positive(radius, "radius")
    count = _require_int(count, "count", 1, 200)
    seed = _require_seed(seed)

    rng = random.Random(seed)
    bm = bmesh.new()
    rock_mat = _get_material(clean + "_Rock", (0.45, 0.42, 0.38, 1.0), 0.95)
    subdiv = 2 if count <= 16 else 1
    for _ in range(count):
        rock_r = rng.uniform(0.3, 0.9)
        cx, cy = _disc_point(rng, max(0.05, radius * 0.9))
        center = Vector((cx, cy, rock_r * 0.55))
        geo = bmesh.ops.create_icosphere(
            bm, subdivisions=subdiv, radius=rock_r, matrix=Matrix.Translation(center),
        )
        jitter = rock_r * 0.25
        for v in geo["verts"]:
            direction = v.co - center
            if direction.length < 1e-6:
                direction = Vector((0.0, 0.0, 1.0))
            direction.normalize()
            v.co += direction * rng.uniform(-jitter, jitter)

    obj, dims, polys = _finish(bm, clean, [rock_mat], smooth=False)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "radius": radius,
        "count": count,
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [rock_mat.name],
        "seed": seed,
    }


def create_mountain_range(server, name="Mountains", width=40.0, depth=20.0,
                          peak_height=8.0, seed=0) -> dict:
    """Create a displaced grid mountain range with rock/snow materials."""
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width")
    depth = _require_positive(depth, "depth")
    peak_height = _require_positive(peak_height, "peak_height")
    seed = _require_seed(seed)
    seed_masked = seed & _MASK64

    rng = random.Random(seed)
    nx, ny = 56, 28
    peaks = []
    for _ in range(4):
        peaks.append({
            "x": rng.uniform(-0.35, 0.35) * width,
            "y": rng.uniform(-0.35, 0.35) * depth,
            "h": peak_height * rng.uniform(0.55, 1.0),
            "s": rng.uniform(0.15, 0.30) * max(width, depth),
        })

    verts = []
    for j in range(ny + 1):
        y = -depth / 2.0 + depth * j / ny
        for i in range(nx + 1):
            x = -width / 2.0 + width * i / nx
            h = 0.0
            for p in peaks:
                d2 = (x - p["x"]) ** 2 + (y - p["y"]) ** 2
                h += p["h"] * math.exp(-d2 / (2.0 * p["s"] ** 2))
            fx = max(0.0, 1.0 - (2.0 * x / width) ** 2)
            fy = max(0.0, 1.0 - (2.0 * y / depth) ** 2)
            detail = _fbm2(x * 0.25 + 7.3, y * 0.25 + 2.1, 3, seed_masked)
            h = h * fx * fy + (detail - 0.5) * peak_height * 0.15 * fx * fy
            verts.append((x, y, max(0.0, h)))

    row = nx + 1
    faces = []
    for j in range(ny):
        for i in range(nx):
            a = j * row + i
            faces.append((a, a + 1, a + 1 + row, a + row))

    mesh = bpy.data.meshes.new(clean + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    rock = _get_material(clean + "_Rock", (0.40, 0.36, 0.30, 1.0), 0.95)
    snow = _get_material(clean + "_Snow", (0.90, 0.92, 0.95, 1.0), 0.6)
    mesh.materials.append(rock)
    mesh.materials.append(snow)
    snow_line = peak_height * 0.55
    for poly in mesh.polygons:
        cx = sum(mesh.vertices[k].co.x for k in poly.vertices) / len(poly.vertices)
        cy = sum(mesh.vertices[k].co.y for k in poly.vertices) / len(poly.vertices)
        cz = sum(mesh.vertices[k].co.z for k in poly.vertices) / len(poly.vertices)
        _ = (cx, cy)
        poly.material_index = 1 if cz >= snow_line else 0
        try:
            poly.use_smooth = True
        except AttributeError:
            pass
    mesh.update()
    _ground_mesh(mesh)
    obj = bpy.data.objects.new(clean, mesh)
    _link(obj)
    dims, _, max_z = _mesh_dims(mesh)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "depth": depth,
        "peak_height": peak_height,
        "max_elevation": max_z,
        "dimensions": dims,
        "polygon_count": len(mesh.polygons),
        "vertex_count": len(mesh.vertices),
        "materials": [rock.name, snow.name],
        "seed": seed,
    }


def create_cave(server, name="Cave", width=6.0, depth=4.0, height=3.0, seed=0) -> dict:
    """Create a hollow displaced rock shell with a front opening, grounded."""
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width")
    depth = _require_positive(depth, "depth")
    height = _require_positive(height, "height")
    seed = _require_seed(seed)
    seed_masked = seed & _MASK64

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=28, v_segments=14, radius=1.0)
    bmesh.ops.scale(bm, vec=Vector((width / 2.0, depth / 2.0, height)),
                    verts=list(bm.verts))
    # Keep the upper shell only.
    low = [v for v in bm.verts if v.co.z < 0.0]
    if low:
        bmesh.ops.delete(bm, geom=low, context="VERTS")
    # Displace for a rocky look.
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        n = _fbm2(v.co.x * 0.8 + 3.1, (v.co.y + v.co.z) * 0.8 + 9.4, 3, seed_masked)
        direction = v.co.normalized() if v.co.length > 1e-6 else Vector((0.0, 0.0, 1.0))
        v.co += direction * (n - 0.5) * min(width, depth) * 0.10
    # Cut a front (-Y) tunnel opening.
    bm.faces.ensure_lookup_table()
    opening = [f for f in bm.faces
               if f.calc_center_median().y < -depth * 0.05
               and abs(f.calc_center_median().x) < width * 0.24
               and f.calc_center_median().z < height * 0.8]
    if opening:
        bmesh.ops.delete(bm, geom=opening, context="FACES")
    # Elliptical floor fan so the interior is walkable.
    floor_z = 0.02
    center = bm.verts.new(Vector((0.0, 0.0, floor_z)))
    ring = []
    segs = 24
    for j in range(segs):
        ang = 2.0 * math.pi * j / segs
        ring.append(bm.verts.new(Vector((
            math.cos(ang) * width / 2.0 * 0.95,
            math.sin(ang) * depth / 2.0 * 0.95,
            floor_z,
        ))))
    bm.verts.ensure_lookup_table()
    for j in range(segs):
        try:
            bm.faces.new([center, ring[j], ring[(j + 1) % segs]])
        except ValueError:
            pass
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

    rock = _get_material(clean + "_Rock", (0.35, 0.30, 0.25, 1.0), 0.95)
    obj, dims, polys = _finish(bm, clean, [rock], smooth=False)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "depth": depth,
        "height": height,
        "opening": "front (-Y)",
        "dimensions": dims,
        "polygon_count": polys,
        "materials": [rock.name],
        "seed": seed,
    }


def create_island(server, name="Island", radius=8.0, seed=0) -> dict:
    """Create a terrain disc island with a sand beach ring and a water disc."""
    _ = server
    clean = _require_name(name)
    radius = _require_positive(radius, "radius")
    seed = _require_seed(seed)
    seed_masked = seed & _MASK64

    land_h = max(1.0, radius * 0.25)
    rings, segs = 6, 48
    bm = bmesh.new()
    grass = _get_material(clean + "_Grass", (0.18, 0.40, 0.12, 1.0), 0.9)
    sand = _get_material(clean + "_Sand", (0.76, 0.68, 0.48, 1.0), 0.9)
    top = bm.verts.new(Vector((0.0, 0.0, land_h)))
    ring_rows = []
    for r in range(1, rings + 1):
        frac = r / rings
        row = []
        for j in range(segs):
            ang = 2.0 * math.pi * j / segs
            hill = land_h * (math.cos(frac * math.pi / 2.0) ** 1.2)
            n = _fbm2(math.cos(ang) * frac * 2.0 + 5.0, math.sin(ang) * frac * 2.0 + 1.0,
                       2, seed_masked)
            z = max(0.0, hill + (n - 0.5) * land_h * 0.25 * (1.0 - frac))
            row.append(bm.verts.new(Vector((
                math.cos(ang) * frac * radius,
                math.sin(ang) * frac * radius,
                z,
            ))))
        ring_rows.append(row)
    bm.verts.ensure_lookup_table()
    inner = ring_rows[0]
    for j in range(segs):
        try:
            bm.faces.new([top, inner[(j + 1) % segs], inner[j]])
        except ValueError:
            pass
    for lower, upper in zip(ring_rows, ring_rows[1:]):
        for j in range(segs):
            try:
                bm.faces.new([lower[j], lower[(j + 1) % segs],
                              upper[(j + 1) % segs], upper[j]])
            except ValueError:
                pass
    bm.faces.ensure_lookup_table()
    beach_frac = 0.72
    for face in bm.faces:
        c = face.calc_center_median()
        rr = math.hypot(c.x, c.y) / radius
        face.material_index = 1 if rr >= beach_frac else 0

    island_mesh = bpy.data.meshes.new(clean + "_IslandMesh")
    bm.to_mesh(island_mesh)
    bm.free()
    island_mesh.update()
    island_mesh.materials.append(grass)
    island_mesh.materials.append(sand)
    island = bpy.data.objects.new(clean, island_mesh)
    # Fix material slots order: slot 0 grass, slot 1 sand (appended above).
    _ground_mesh(island_mesh)
    _link(island)
    try:
        for poly in island_mesh.polygons:
            poly.use_smooth = True
    except AttributeError:
        pass
    island_mesh.update()

    # Water disc around the island.
    water_r = radius * 1.8
    water_z = 0.12
    wbm = bmesh.new()
    wcenter = wbm.verts.new(Vector((0.0, 0.0, water_z)))
    wring = []
    wsegs = 64
    for j in range(wsegs):
        ang = 2.0 * math.pi * j / wsegs
        wring.append(wbm.verts.new(Vector((
            math.cos(ang) * water_r, math.sin(ang) * water_r, water_z))))
    wbm.verts.ensure_lookup_table()
    for j in range(wsegs):
        try:
            wbm.faces.new([wcenter, wring[j], wring[(j + 1) % wsegs]])
        except ValueError:
            pass
    water_mat = _get_material(clean + "_Water", (0.05, 0.25, 0.35, 1.0), 0.15)
    water, _, water_polys = _finish(wbm, clean + "_Water", [water_mat],
                                    smooth=True, ground=False)

    dims, _, _ = _mesh_dims(island_mesh)
    return {
        "success": True,
        "name": island.name,
        "object": island.name,
        "island": island.name,
        "water": water.name,
        "components": [island.name, water.name],
        "radius": radius,
        "water_radius": round(water_r, 4),
        "dimensions": dims,
        "polygon_count": len(island_mesh.polygons),
        "water_polygon_count": water_polys,
        "materials": [grass.name, sand.name, water_mat.name],
        "seed": seed,
    }


def create_waterfall(server, name="Waterfall", width=2.0, height=4.0) -> dict:
    """Create a curved vertical water sheet with a foam pool at its base."""
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width")
    height = _require_positive(height, "height")

    overhang = min(2.0, 0.5 + width * 0.25)
    cols, rows = 12, 16
    bm = bmesh.new()
    grid = []
    for r in range(rows + 1):
        t = r / rows
        z = height * (1.0 - t)
        y = overhang * t * t
        row = []
        for c in range(cols + 1):
            x = -width / 2.0 + width * c / cols
            ripple = 0.05 * math.sin(x * 3.0 + t * 6.0) * t
            row.append(bm.verts.new(Vector((x, y + ripple, z))))
        grid.append(row)
    bm.verts.ensure_lookup_table()
    for r in range(rows):
        for c in range(cols):
            try:
                bm.faces.new([grid[r][c], grid[r][c + 1],
                              grid[r + 1][c + 1], grid[r + 1][c]])
            except ValueError:
                pass
    water_mat = _get_material(clean + "_Water", (0.55, 0.75, 0.85, 1.0), 0.05)
    sheet, _, sheet_polys = _finish(bm, clean + "_Sheet", [water_mat],
                                    smooth=True, ground=False)

    # Foam pool ellipse at the base.
    fbm = bmesh.new()
    foam_mat = _get_material(clean + "_Foam", (0.92, 0.95, 0.96, 1.0), 0.6)
    fcenter = fbm.verts.new(Vector((0.0, overhang, 0.03)))
    fring = []
    fsegs = 32
    for j in range(fsegs):
        ang = 2.0 * math.pi * j / fsegs
        fring.append(fbm.verts.new(Vector((
            math.cos(ang) * width * 0.9,
            overhang + math.sin(ang) * width * 0.6,
            0.03,
        ))))
    fbm.verts.ensure_lookup_table()
    for j in range(fsegs):
        try:
            fbm.faces.new([fcenter, fring[j], fring[(j + 1) % fsegs]])
        except ValueError:
            pass
    pool, _, pool_polys = _finish(fbm, clean + "_Pool", [foam_mat],
                                  smooth=True, ground=False)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return {
        "success": True,
        "name": clean,
        "sheet": sheet.name,
        "pool": pool.name,
        "components": [sheet.name, pool.name],
        "width": width,
        "height": height,
        "overhang": round(overhang, 4),
        "dimensions": [round(width, 4), round(overhang + width * 0.6, 4), round(height, 4)],
        "polygon_count": sheet_polys + pool_polys,
        "sheet_polygon_count": sheet_polys,
        "pool_polygon_count": pool_polys,
        "materials": [water_mat.name, foam_mat.name],
    }


def _fallback_ground(clean, size, seed):
    """Minimal hill grid used only when server.create_terrain is missing."""
    n = 16
    half = size / 2.0
    h = max(0.5, size * 0.1)
    bm = bmesh.new()
    grid = []
    for j in range(n + 1):
        row = []
        y = -half + size * j / n
        for i in range(n + 1):
            x = -half + size * i / n
            fx = max(0.0, 1.0 - (x / half) ** 2)
            fy = max(0.0, 1.0 - (y / half) ** 2)
            z = h * fx * fy * (0.7 + 0.3 * _fbm2(x * 0.3, y * 0.3, 2, seed & _MASK64))
            row.append(bm.verts.new(Vector((x, y, z))))
        grid.append(row)
    bm.verts.ensure_lookup_table()
    for j in range(n):
        for i in range(n):
            try:
                bm.faces.new([grid[j][i], grid[j][i + 1],
                              grid[j + 1][i + 1], grid[j + 1][i]])
            except ValueError:
                pass
    mat = _get_material(clean + "_Ground", (0.18, 0.40, 0.12, 1.0), 0.9)
    return _finish(bm, clean, [mat])


def create_biome(server, name="Biome", size=20.0, seed=0) -> dict:
    """Compose terrain, water and a small forest into one biome block."""
    clean = _require_name(name)
    size = _require_positive(size, "size")
    seed = _require_seed(seed)

    terrain_height = round(size * 0.12, 4)
    terrain_name = None
    terrain_polys = 0
    make_terrain = getattr(server, "create_terrain", None) if server is not None else None
    if callable(make_terrain):
        result = make_terrain(name=f"{clean}_Terrain", size=size, subdivisions=48,
                              height=terrain_height, noise_scale=2.0,
                              seed=seed, style="hills")
        if isinstance(result, dict):
            terrain_name = result.get("object") or result.get("name")
            terrain_polys = int(result.get("face_count", 0) or 0)
    else:
        terrain, _, terrain_polys = _fallback_ground(f"{clean}_Terrain", size, seed)
        terrain_name = terrain.name

    water_name = None
    water_polys = 0
    make_water = getattr(server, "create_water_plane", None) if server is not None else None
    if callable(make_water):
        result = make_water(name=f"{clean}_Water", size=size * 1.6, subdivisions=16,
                            wave_height=0.05, wave_scale=1.5)
        if isinstance(result, dict):
            water_name = result.get("name") or result.get("object")
            water_polys = int(result.get("face_count", 0) or 0)
            wobj = bpy.data.objects.get(water_name) if water_name else None
            if wobj is not None:
                wobj.location.z = round(terrain_height * 0.25, 4)
    else:
        wbm = bmesh.new()
        half = size * 0.8
        wmat = _get_material(f"{clean}_WaterMat", (0.05, 0.25, 0.35, 1.0), 0.15)
        wcenter = wbm.verts.new(Vector((0.0, 0.0, terrain_height * 0.25)))
        wring = []
        for j in range(48):
            ang = 2.0 * math.pi * j / 48
            wring.append(wbm.verts.new(Vector((
                math.cos(ang) * half, math.sin(ang) * half, terrain_height * 0.25))))
        wbm.verts.ensure_lookup_table()
        for j in range(48):
            try:
                wbm.faces.new([wcenter, wring[j], wring[(j + 1) % 48]])
            except ValueError:
                pass
        wobj, _, water_polys = _finish(wbm, f"{clean}_Water", [wmat],
                                       smooth=True, ground=False)
        water_name = wobj.name

    forest = create_forest(server, name=f"{clean}_Forest",
                           radius=size * 0.32, tree_count=6, seed=seed + 1)
    components = [c for c in (terrain_name, water_name) if c] + forest["trees"]
    return {
        "success": True,
        "name": clean,
        "terrain": terrain_name,
        "water": water_name,
        "forest": forest["name"] if isinstance(forest, dict) else None,
        "trees": forest["trees"],
        "components": components,
        "size": size,
        "terrain_height": terrain_height,
        "dimensions": [round(size, 4), round(size, 4), round(terrain_height, 4)],
        "polygon_count": terrain_polys + water_polys + int(forest.get("polygon_count", 0)),
        "tree_count": forest["count"],
        "seed": seed,
    }
