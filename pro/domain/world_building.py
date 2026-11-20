"""City-scale world building domain pack.

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no external assets.
All functions run on Blender's main thread, validate their inputs,
are deterministic for a given ``seed`` and return plain
JSON-serializable dictionaries.

Conventions: meters and degrees in public parameters, front is ``-Y``,
bilateral symmetry across ``X=0``, ground plane is ``Z=0`` (lowest
point of every build touches ``Z=0``).
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

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


def _require_positive(value, label, maximum=1000.0):
    if not _is_number(value) or not math.isfinite(float(value)) \
            or float(value) <= 0.0 or float(value) > maximum:
        raise ValueError(
            f"{label} must be a positive finite number <= {maximum} "
            f"(got {value!r})"
        )
    return float(value)


def _require_int(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if value < minimum or value > maximum:
        raise ValueError(
            f"{label} must be within [{minimum}, {maximum}] (got {value!r})"
        )
    return value


def _require_seed(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"seed must be an integer (got {value!r})")
    return value


# ---------------------------------------------------------------------------
# Geometry / material helpers
# ---------------------------------------------------------------------------

def _get_or_create_material(name, rgba, roughness=0.8, metallic=0.0):
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
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = float(metallic)
    return mat


def _get_or_create_glass(name, rgba=(0.55, 0.75, 0.88, 1.0)):
    """Bluish facade glass; sets transmission only if the socket exists."""
    mat = _get_or_create_material(name, rgba, roughness=0.12, metallic=0.0)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        for socket in ("Transmission Weight", "Transmission"):
            if socket in bsdf.inputs:
                try:
                    bsdf.inputs[socket].default_value = 0.4
                except Exception:
                    pass
                break
    return mat


def _box(bm, xmin, xmax, ymin, ymax, zmin, zmax, material_index=None):
    """Append a solid axis-aligned box; return its verts for later rotation."""
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
        vec=Vector(((xmin + xmax) / 2.0, (ymin + ymax) / 2.0,
                    (zmin + zmax) / 2.0)),
        verts=verts,
    )
    if material_index is not None:
        bm.faces.ensure_lookup_table()
        for face in set(bm.faces) - before:
            face.material_index = material_index
    return verts


def _cylinder(bm, radius_bottom, radius_top, depth, center,
              segments=12, material_index=None):
    """Append a vertical tapered cylinder centered on *center*; return verts."""
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segments,
        radius1=radius_bottom, radius2=radius_top, depth=depth,
    )
    verts = geo["verts"]
    bmesh.ops.translate(bm, vec=Vector(center), verts=verts)
    if material_index is not None:
        bm.faces.ensure_lookup_table()
        for face in set(bm.faces) - before:
            face.material_index = material_index
    return verts


def _blob(bm, radius, center, material_index=None, subdivisions=2):
    """Append an icosphere blob centered on *center*."""
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    bmesh.ops.create_icosphere(
        bm, subdivisions=subdivisions, radius=radius,
        matrix=Matrix.Translation(Vector(center)),
    )
    if material_index is not None:
        bm.faces.ensure_lookup_table()
        for face in set(bm.faces) - before:
            face.material_index = material_index


def _finish(bm, name, materials):
    """Build a mesh object from *bm*, link it, return (object, dims, polys)."""
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    for mat in materials:
        mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
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


def _tree_into(bm, rng, x, y, base_z, trunk_h, crown_r,
               trunk_idx, leaf_idx):
    """Append a trunk + crown tree at (x, y) with its base at *base_z*."""
    _cylinder(bm, 0.12, 0.09, trunk_h, (x, y, base_z + trunk_h / 2.0),
              segments=8, material_index=trunk_idx)
    top = Vector((x, y, base_z + trunk_h))
    _blob(bm, crown_r,
          (top.x + rng.uniform(-0.1, 0.1), top.y + rng.uniform(-0.1, 0.1),
           top.z + crown_r * 0.55),
          material_index=leaf_idx, subdivisions=2)
    return top.z + crown_r * 1.55


def _bench_into(bm, x, y, z, facing=0.0, seat_idx=0, leg_idx=1):
    """Append a wooden bench (seat + back + legs); *facing* rotates it."""
    verts = []
    verts += _box(bm, x - 0.9, x + 0.9, y - 0.25, y + 0.25, z + 0.42,
                  z + 0.50, material_index=seat_idx)
    verts += _box(bm, x - 0.9, x + 0.9, y - 0.30, y - 0.22, z + 0.50,
                  z + 1.00, material_index=seat_idx)
    for lx in (x - 0.75, x + 0.75):
        verts += _box(bm, lx - 0.04, lx + 0.04, y - 0.21, y + 0.21, z,
                      z + 0.42, material_index=leg_idx)
    if facing:
        bmesh.ops.rotate(bm, cent=Vector((x, y, z)),
                         matrix=Matrix.Rotation(facing, 3, "Z"), verts=verts)
    return z + 1.00


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def create_city_block(server, name="CityBlock", width=40.0, depth=40.0,
                      building_count=6, seed=0) -> dict:
    """Create a deterministic grid of towers on an asphalt base with roads.

    Buildings sit on concrete sidewalk pads; the gaps between pads act as
    roads. Lowest point touches ``Z=0``.
    """
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width")
    depth = _require_positive(depth, "depth")
    building_count = _require_int(building_count, "building_count", 1, 100)
    seed = _require_seed(seed)
    rng = random.Random(seed)

    cols = math.ceil(math.sqrt(building_count))
    rows = math.ceil(building_count / cols)
    cell_w, cell_d = width / cols, depth / rows

    bm = bmesh.new()
    asphalt = _get_or_create_material(clean + "_Asphalt",
                                      (0.09, 0.09, 0.10, 1.0), 0.95)
    concrete = _get_or_create_material(clean + "_Sidewalk",
                                       (0.55, 0.55, 0.53, 1.0), 0.9)
    wall_a = _get_or_create_material(clean + "_WallA",
                                     (0.70, 0.66, 0.58, 1.0), 0.85)
    wall_b = _get_or_create_material(clean + "_WallB",
                                     (0.55, 0.58, 0.62, 1.0), 0.85)
    roof_m = _get_or_create_material(clean + "_Roof",
                                     (0.25, 0.25, 0.27, 1.0), 0.9)
    materials = [asphalt, concrete, wall_a, wall_b, roof_m]

    _box(bm, -width / 2.0, width / 2.0, -depth / 2.0, depth / 2.0,
         0.0, 0.30, material_index=0)

    walls = [wall_a, wall_b]
    buildings = []
    top_z = 0.30
    for i in range(building_count):
        col, row = i % cols, i // cols
        cx = -width / 2.0 + (col + 0.5) * cell_w
        cy = -depth / 2.0 + (row + 0.5) * cell_d
        bw = cell_w * rng.uniform(0.50, 0.62)
        bd = cell_d * rng.uniform(0.50, 0.62)
        height = rng.uniform(6.0, 20.0)
        wall_idx = 2 + (i % 2)
        _box(bm, cx - bw / 2.0 - 0.6, cx + bw / 2.0 + 0.6,
             cy - bd / 2.0 - 0.6, cy + bd / 2.0 + 0.6,
             0.30, 0.42, material_index=1)
        _box(bm, cx - bw / 2.0, cx + bw / 2.0, cy - bd / 2.0,
             cy + bd / 2.0, 0.42, 0.42 + height, material_index=wall_idx)
        _box(bm, cx - bw / 2.0, cx + bw / 2.0, cy - bd / 2.0,
             cy + bd / 2.0, 0.42 + height, 0.57 + height,
             material_index=4)
        top_z = max(top_z, 0.57 + height)
        buildings.append({
            "position": [round(cx, 4), round(cy, 4)],
            "width": round(bw, 4),
            "depth": round(bd, 4),
            "height": round(height, 4),
            "material": walls[i % 2].name,
        })

    obj, dims, polys = _finish(bm, clean, materials)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "depth": depth,
        "building_count": building_count,
        "buildings": buildings,
        "grid": {"columns": cols, "rows": rows},
        "dimensions": [round(v, 6) for v in dims],
        "footprint": [round(width, 6), round(depth, 6)],
        "max_height": round(top_z, 6),
        "polygon_count": polys,
        "materials": [m.name for m in materials],
        "seed": seed,
    }


def create_road(server, name="Road", length=40.0, width=7.0,
                lane_count=2) -> dict:
    """Create an asphalt road slab (length along Y) with markings + sidewalks."""
    _ = server
    clean = _require_name(name)
    length = _require_positive(length, "length")
    width = _require_positive(width, "width", maximum=200.0)
    lane_count = _require_int(lane_count, "lane_count", 1, 8)

    bm = bmesh.new()
    asphalt = _get_or_create_material(clean + "_Asphalt",
                                      (0.09, 0.09, 0.10, 1.0), 0.95)
    concrete = _get_or_create_material(clean + "_Sidewalk",
                                       (0.55, 0.55, 0.53, 1.0), 0.9)
    paint = _get_or_create_material(clean + "_Marking",
                                    (0.85, 0.85, 0.82, 1.0), 0.6)
    materials = [asphalt, concrete, paint]

    _box(bm, -width / 2.0, width / 2.0, -length / 2.0, length / 2.0,
         0.0, 0.12, material_index=0)
    sw = 1.5
    _box(bm, -width / 2.0 - sw, -width / 2.0, -length / 2.0,
         length / 2.0, 0.0, 0.22, material_index=1)
    _box(bm, width / 2.0, width / 2.0 + sw, -length / 2.0,
         length / 2.0, 0.0, 0.22, material_index=1)

    dashes = 0
    if lane_count >= 2:
        lane_w = width / lane_count
        dash_len, gap = 2.0, 2.0
        y = -length / 2.0
        while y + dash_len <= length / 2.0 + _EPS:
            for li in range(1, lane_count):
                lx = -width / 2.0 + li * lane_w
                _box(bm, lx - 0.075, lx + 0.075, y, y + dash_len,
                     0.12, 0.14, material_index=2)
                dashes += 1
            y += dash_len + gap
    # Solid edge lines.
    for ex in (-width / 2.0 + 0.25, width / 2.0 - 0.25):
        _box(bm, ex - 0.06, ex + 0.06, -length / 2.0, length / 2.0,
             0.12, 0.14, material_index=2)

    obj, dims, polys = _finish(bm, clean, materials)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "length": length,
        "width": width,
        "lane_count": lane_count,
        "sidewalk_width": sw,
        "dash_count": dashes,
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "materials": [m.name for m in materials],
    }


def create_street(server, name="Street", length=40.0, width=8.0,
                  seed=0) -> dict:
    """Create a road with sidewalks, street lamps and deterministic props."""
    _ = server
    clean = _require_name(name)
    length = _require_positive(length, "length")
    width = _require_positive(width, "width", maximum=200.0)
    seed = _require_seed(seed)
    rng = random.Random(seed)

    bm = bmesh.new()
    asphalt = _get_or_create_material(clean + "_Asphalt",
                                      (0.09, 0.09, 0.10, 1.0), 0.95)
    concrete = _get_or_create_material(clean + "_Sidewalk",
                                       (0.55, 0.55, 0.53, 1.0), 0.9)
    paint = _get_or_create_material(clean + "_Marking",
                                    (0.85, 0.85, 0.82, 1.0), 0.6)
    pole_m = _get_or_create_material(clean + "_Pole",
                                     (0.20, 0.20, 0.22, 1.0), 0.5, 0.8)
    lamp_m = _get_or_create_material(clean + "_Lamp",
                                     (1.00, 0.95, 0.80, 1.0), 0.4)
    wood = _get_or_create_material(clean + "_Wood",
                                   (0.42, 0.28, 0.14, 1.0), 0.8)
    leaf = _get_or_create_material(clean + "_Foliage",
                                   (0.16, 0.42, 0.12, 1.0), 0.9)
    materials = [asphalt, concrete, paint, pole_m, lamp_m, wood, leaf]

    _box(bm, -width / 2.0, width / 2.0, -length / 2.0, length / 2.0,
         0.0, 0.12, material_index=0)
    sw = 1.5
    _box(bm, -width / 2.0 - sw, -width / 2.0, -length / 2.0,
         length / 2.0, 0.0, 0.22, material_index=1)
    _box(bm, width / 2.0, width / 2.0 + sw, -length / 2.0,
         length / 2.0, 0.0, 0.22, material_index=1)
    # Center dashed line (2 lanes).
    dash_len, gap = 2.0, 2.0
    y = -length / 2.0
    dashes = 0
    while y + dash_len <= length / 2.0 + _EPS:
        _box(bm, -0.075, 0.075, y, y + dash_len, 0.12, 0.14,
             material_index=2)
        dashes += 1
        y += dash_len + gap

    # Street lamps every 12 m, alternating sides.
    lamp_positions = []
    side = 1.0
    ly = -length / 2.0 + 4.0
    while ly <= length / 2.0 - 2.0:
        px = side * (width / 2.0 + 1.0)
        _cylinder(bm, 0.09, 0.07, 5.0, (px, ly, 0.22 + 2.5),
                  segments=8, material_index=3)
        arm = _box(bm, min(px, px - side * 1.2), max(px, px - side * 1.2),
                   ly - 0.08, ly + 0.08, 5.0, 5.16, material_index=3)
        del arm
        _box(bm, px - side * 1.2 - 0.25, px - side * 1.2 + 0.25,
             ly - 0.15, ly + 0.15, 4.9, 5.02, material_index=4)
        lamp_positions.append([round(px, 4), round(ly, 4)])
        side *= -1.0
        ly += 12.0

    # Deterministic small props (planters / bollards) on the sidewalks.
    props = []
    prop_total = max(2, int(length // 10))
    for _ in range(prop_total):
        px = rng.choice((-1.0, 1.0)) * (width / 2.0 + 0.75)
        py = rng.uniform(-length / 2.0 + 1.0, length / 2.0 - 1.0)
        if rng.random() < 0.5:
            _box(bm, px - 0.3, px + 0.3, py - 0.3, py + 0.3, 0.22,
                 0.62, material_index=1)
            _blob(bm, 0.32, (px, py, 0.95), material_index=6,
                  subdivisions=1)
            props.append({"kind": "planter",
                          "position": [round(px, 4), round(py, 4)]})
        else:
            _cylinder(bm, 0.09, 0.09, 0.7, (px, py, 0.22 + 0.35),
                      segments=8, material_index=3)
            props.append({"kind": "bollard",
                          "position": [round(px, 4), round(py, 4)]})

    obj, dims, polys = _finish(bm, clean, materials)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "length": length,
        "width": width,
        "lamp_count": len(lamp_positions),
        "lamp_positions": lamp_positions,
        "props": props,
        "dash_count": dashes,
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "materials": [m.name for m in materials],
        "seed": seed,
    }


def create_bridge(server, name="Bridge", length=20.0, width=8.0,
                  height=4.0) -> dict:
    """Create an elevated deck with railings, piers and arch struts."""
    _ = server
    clean = _require_name(name)
    length = _require_positive(length, "length")
    width = _require_positive(width, "width", maximum=200.0)
    height = _require_positive(height, "height", maximum=200.0)
    if height < 1.5:
        raise ValueError(f"height must be at least 1.5 (got {height!r})")

    bm = bmesh.new()
    concrete = _get_or_create_material(clean + "_Concrete",
                                       (0.55, 0.55, 0.53, 1.0), 0.9)
    asphalt = _get_or_create_material(clean + "_Asphalt",
                                      (0.09, 0.09, 0.10, 1.0), 0.95)
    rail_m = _get_or_create_material(clean + "_Railing",
                                     (0.30, 0.32, 0.35, 1.0), 0.5, 0.8)
    materials = [concrete, asphalt, rail_m]

    deck_t = 0.5
    deck_bottom = height - deck_t
    # Deck slab spanning the gap (length along Y), top at *height*.
    _box(bm, -width / 2.0, width / 2.0, -length / 2.0, length / 2.0,
         deck_bottom, height, material_index=0)
    # Roadway strip on the deck.
    _box(bm, -width / 2.0 + 0.5, width / 2.0 - 0.5, -length / 2.0,
         length / 2.0, height, height + 0.05, material_index=1)
    # Railings.
    _box(bm, -width / 2.0, -width / 2.0 + 0.2, -length / 2.0,
         length / 2.0, height, height + 1.1, material_index=2)
    _box(bm, width / 2.0 - 0.2, width / 2.0, -length / 2.0,
         length / 2.0, height, height + 1.1, material_index=2)

    # Piers with diagonal arch struts fanning toward the deck.
    pier_count = max(2, int(length // 8) + 1)
    piers = []
    for i in range(pier_count):
        frac = i / (pier_count - 1) if pier_count > 1 else 0.5
        py = -length / 2.0 + frac * length
        _box(bm, -width * 0.30, width * 0.30, py - 0.6, py + 0.6,
             0.0, deck_bottom, material_index=0)
        for direction in (-1.0, 1.0):
            verts = _box(bm, -0.25, 0.25, py - 0.25, py + 0.25,
                         0.0, deck_bottom * 0.75, material_index=0)
            bmesh.ops.rotate(
                bm, cent=Vector((0.0, py, deck_bottom * 0.35)),
                matrix=Matrix.Rotation(direction * 0.5, 3, "X"),
                verts=verts,
            )
        piers.append(round(py, 4))

    obj, dims, polys = _finish(bm, clean, materials)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "length": length,
        "width": width,
        "height": height,
        "deck_thickness": deck_t,
        "pier_count": pier_count,
        "pier_positions": piers,
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "materials": [m.name for m in materials],
    }


def create_tunnel(server, name="Tunnel", length=20.0, width=8.0,
                  height=4.0) -> dict:
    """Create an arched tunnel shell, open at both ends, with a roadway."""
    _ = server
    clean = _require_name(name)
    length = _require_positive(length, "length")
    width = _require_positive(width, "width", maximum=200.0)
    height = _require_positive(height, "height", maximum=200.0)
    radius = width / 2.0
    if height <= radius + 0.3:
        raise ValueError(
            f"height ({height}) must be greater than width/2 + 0.3 "
            f"({radius + 0.3}) so the arch has vertical walls"
        )

    bm = bmesh.new()
    concrete = _get_or_create_material(clean + "_Concrete",
                                       (0.55, 0.55, 0.53, 1.0), 0.9)
    asphalt = _get_or_create_material(clean + "_Asphalt",
                                      (0.09, 0.09, 0.10, 1.0), 0.95)
    paint = _get_or_create_material(clean + "_Marking",
                                    (0.85, 0.85, 0.82, 1.0), 0.6)
    materials = [concrete, asphalt, paint]

    wall_h = height - radius
    thick = 0.4
    # Roadway floor.
    _box(bm, -radius, radius, -length / 2.0, length / 2.0, 0.0, 0.1,
         material_index=1)
    # Side walls (interior faces at x = +/-radius).
    _box(bm, -radius - thick, -radius, -length / 2.0, length / 2.0,
         0.0, wall_h, material_index=0)
    _box(bm, radius, radius + thick, -length / 2.0, length / 2.0,
         0.0, wall_h, material_index=0)
    # Arch shell: rotated flat panels spanning 180 degrees.
    nseg = 11
    shell_r = radius + thick / 2.0
    arc_len = math.pi * shell_r / nseg + 0.06
    for i in range(nseg):
        angle = math.pi * i / (nseg - 1)  # 0 (+X spring) .. pi (-X spring)
        cx = math.cos(angle) * shell_r
        cz = wall_h + math.sin(angle) * shell_r
        verts = _box(bm, -arc_len / 2.0, arc_len / 2.0,
                     -length / 2.0, length / 2.0,
                     -thick / 2.0, thick / 2.0, material_index=0)
        bmesh.ops.rotate(bm, cent=Vector((0.0, 0.0, 0.0)),
                         matrix=Matrix.Rotation(angle + math.pi / 2.0, 3, "Y"),
                         verts=verts)
        bmesh.ops.translate(bm, vec=Vector((cx, 0.0, cz)), verts=verts)
    # Portal beams framing both open ends.
    for end in (-length / 2.0, length / 2.0):
        _box(bm, -radius - thick, radius + thick, end - 0.3, end + 0.3,
             height, height + 0.5, material_index=0)
    # Center dashed roadway marking.
    y = -length / 2.0
    dashes = 0
    while y + 2.0 <= length / 2.0 + _EPS:
        _box(bm, -0.075, 0.075, y, y + 2.0, 0.1, 0.12,
             material_index=2)
        dashes += 1
        y += 4.0

    obj, dims, polys = _finish(bm, clean, materials)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "length": length,
        "width": width,
        "height": height,
        "wall_height": round(wall_h, 6),
        "arch_radius": round(radius, 6),
        "arch_segments": nseg,
        "dash_count": dashes,
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "materials": [m.name for m in materials],
    }


def create_skyscraper(server, name="Skyscraper", width=12.0, depth=12.0,
                      height=60.0, floors=20) -> dict:
    """Create a tower with per-floor glass bands; bbox is exactly W x D x H."""
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width", maximum=300.0)
    depth = _require_positive(depth, "depth", maximum=300.0)
    height = _require_positive(height, "height", maximum=1000.0)
    floors = _require_int(floors, "floors", 1, 200)
    if height < 3.0:
        raise ValueError(f"height must be at least 3.0 (got {height!r})")
    if width < 2.0 or depth < 2.0:
        raise ValueError(
            f"width and depth must each be at least 2.0 "
            f"(got {width!r}, {depth!r})"
        )

    bm = bmesh.new()
    wall_m = _get_or_create_material(clean + "_Wall",
                                     (0.62, 0.63, 0.65, 1.0), 0.8)
    glass = _get_or_create_glass(clean + "_Glass")
    roof_m = _get_or_create_material(clean + "_Roof",
                                     (0.25, 0.25, 0.27, 1.0), 0.9)
    materials = [wall_m, glass, roof_m]

    parapet_h = 1.0
    shaft_h = height - parapet_h
    inset = 0.06
    hx_in, hy_in = (width - 2.0 * inset) / 2.0, (depth - 2.0 * inset) / 2.0
    hx, hy = width / 2.0, depth / 2.0
    # Main shaft, slightly inset so glass bands land exactly on W x D.
    _box(bm, -hx_in, hx_in, -hy_in, hy_in, 0.0, shaft_h,
         material_index=0)
    # Per-floor window bands proud of the shaft on all four facades.
    floor_h = shaft_h / floors
    band_h = floor_h * 0.55
    for f in range(floors):
        bz0 = f * floor_h + (floor_h - band_h) / 2.0
        bz1 = bz0 + band_h
        _box(bm, -hx, hx, -hy, -hy_in, bz0, bz1, material_index=1)
        _box(bm, -hx, hx, hy_in, hy, bz0, bz1, material_index=1)
        _box(bm, -hx, -hx_in, -hy_in, hy_in, bz0, bz1,
             material_index=1)
        _box(bm, hx_in, hx, -hy_in, hy_in, bz0, bz1, material_index=1)
    # Parapet ring at the exact outer footprint, topping out at *height*.
    pt = 0.15
    _box(bm, -hx, hx, -hy, -hy + pt, shaft_h, height,
         material_index=2)
    _box(bm, -hx, hx, hy - pt, hy, shaft_h, height, material_index=2)
    _box(bm, -hx, -hx + pt, -hy + pt, hy - pt, shaft_h, height,
         material_index=2)
    _box(bm, hx - pt, hx, -hy + pt, hy - pt, shaft_h, height,
         material_index=2)
    # Rooftop bulkhead + antenna, both topping out at or below *height*.
    _box(bm, -1.5, 1.5, -1.5, 1.5, shaft_h, height - 0.3,
         material_index=0)
    _cylinder(bm, 0.05, 0.02, 2.5, (0.0, 0.0, height - 1.25),
              segments=8, material_index=2)

    obj, dims, polys = _finish(bm, clean, materials)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "depth": depth,
        "height": height,
        "floors": floors,
        "floor_height": round(floor_h, 6),
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "materials": [m.name for m in materials],
    }


def create_park(server, name="Park", width=20.0, depth=20.0,
                tree_count=8, seed=0) -> dict:
    """Create a grass park with crossing paths, trees and benches."""
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width")
    depth = _require_positive(depth, "depth")
    tree_count = _require_int(tree_count, "tree_count", 0, 500)
    seed = _require_seed(seed)
    rng = random.Random(seed)

    bm = bmesh.new()
    grass = _get_or_create_material(clean + "_Grass",
                                    (0.12, 0.35, 0.08, 1.0), 0.95)
    concrete = _get_or_create_material(clean + "_Path",
                                       (0.60, 0.58, 0.52, 1.0), 0.9)
    trunk_m = _get_or_create_material(clean + "_Bark",
                                      (0.30, 0.20, 0.12, 1.0), 0.95)
    leaf = _get_or_create_material(clean + "_Foliage",
                                   (0.16, 0.42, 0.12, 1.0), 0.9)
    wood = _get_or_create_material(clean + "_Wood",
                                   (0.42, 0.28, 0.14, 1.0), 0.8)
    iron = _get_or_create_material(clean + "_Iron",
                                   (0.20, 0.20, 0.22, 1.0), 0.5, 0.8)
    materials = [grass, concrete, trunk_m, leaf, wood, iron]

    _box(bm, -width / 2.0, width / 2.0, -depth / 2.0, depth / 2.0,
         0.0, 0.20, material_index=0)
    pw = 1.5
    _box(bm, -width / 2.0, width / 2.0, -pw / 2.0, pw / 2.0, 0.20,
         0.26, material_index=1)
    _box(bm, -pw / 2.0, pw / 2.0, -depth / 2.0, depth / 2.0, 0.20,
         0.26, material_index=1)

    trees = []
    top_z = 0.26
    for _ in range(tree_count):
        for _attempt in range(20):
            tx = rng.uniform(-width / 2.0 + 1.0, width / 2.0 - 1.0)
            ty = rng.uniform(-depth / 2.0 + 1.0, depth / 2.0 - 1.0)
            if abs(tx) > pw / 2.0 + 0.8 or abs(ty) > pw / 2.0 + 0.8:
                break
        else:
            continue
        trunk_h = rng.uniform(1.0, 1.6)
        crown_r = rng.uniform(0.9, 1.5)
        top = _tree_into(bm, rng, tx, ty, 0.20, trunk_h, crown_r, 2, 3)
        top_z = max(top_z, top)
        trees.append({"position": [round(tx, 4), round(ty, 4)],
                      "crown_radius": round(crown_r, 4)})

    bench_positions = []
    for bx, by, facing in ((-pw / 2.0 - 1.0, 2.5, math.pi / 2.0),
                           (pw / 2.0 + 1.0, -2.5, -math.pi / 2.0),
                           (2.5, pw / 2.0 + 1.0, math.pi),
                           (-2.5, -pw / 2.0 - 1.0, 0.0)):
        if abs(bx) < width / 2.0 - 1.0 and abs(by) < depth / 2.0 - 1.0:
            top = _bench_into(bm, bx, by, 0.26, facing=facing,
                              seat_idx=4, leg_idx=5)
            top_z = max(top_z, top)
            bench_positions.append([round(bx, 4), round(by, 4)])

    obj, dims, polys = _finish(bm, clean, materials)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "depth": depth,
        "tree_count": len(trees),
        "trees": trees,
        "bench_count": len(bench_positions),
        "bench_positions": bench_positions,
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "materials": [m.name for m in materials],
        "seed": seed,
    }


def create_plaza(server, name="Plaza", width=20.0, depth=20.0,
                 seed=0) -> dict:
    """Create a paved plaza with planters, benches and a central fountain."""
    _ = server
    clean = _require_name(name)
    width = _require_positive(width, "width")
    depth = _require_positive(depth, "depth")
    seed = _require_seed(seed)
    rng = random.Random(seed)

    bm = bmesh.new()
    stone = _get_or_create_material(clean + "_Stone",
                                    (0.62, 0.60, 0.55, 1.0), 0.85)
    border = _get_or_create_material(clean + "_Border",
                                    (0.35, 0.35, 0.36, 1.0), 0.9)
    concrete = _get_or_create_material(clean + "_Concrete",
                                       (0.55, 0.55, 0.53, 1.0), 0.9)
    wood = _get_or_create_material(clean + "_Wood",
                                   (0.42, 0.28, 0.14, 1.0), 0.8)
    iron = _get_or_create_material(clean + "_Iron",
                                   (0.20, 0.20, 0.22, 1.0), 0.5, 0.8)
    leaf = _get_or_create_material(clean + "_Foliage",
                                   (0.16, 0.42, 0.12, 1.0), 0.9)
    water = _get_or_create_material(clean + "_Water",
                                    (0.15, 0.35, 0.50, 1.0), 0.15)
    materials = [stone, border, concrete, wood, iron, leaf, water]

    _box(bm, -width / 2.0, width / 2.0, -depth / 2.0, depth / 2.0,
         0.0, 0.15, material_index=0)
    # Darker perimeter border frame.
    bw = 0.8
    hx, hy = width / 2.0, depth / 2.0
    _box(bm, -hx, hx, -hy, -hy + bw, 0.15, 0.19, material_index=1)
    _box(bm, -hx, hx, hy - bw, hy, 0.15, 0.19, material_index=1)
    _box(bm, -hx, -hx + bw, -hy + bw, hy - bw, 0.15, 0.19,
         material_index=1)
    _box(bm, hx - bw, hx, -hy + bw, hy - bw, 0.15, 0.19,
         material_index=1)

    # Four planters near the corners with foliage blobs.
    planters = []
    for sx, sy in ((-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (1.0, 1.0)):
        px = sx * (hx - 2.5) + rng.uniform(-0.3, 0.3)
        py = sy * (hy - 2.5) + rng.uniform(-0.3, 0.3)
        _box(bm, px - 0.6, px + 0.6, py - 0.6, py + 0.6, 0.15, 0.65,
             material_index=2)
        _blob(bm, 0.55, (px, py, 1.05), material_index=5, subdivisions=1)
        planters.append([round(px, 4), round(py, 4)])

    # Four benches facing the center.
    benches = []
    for i, (ang, dist) in enumerate([(0.0, 4.0), (math.pi / 2.0, 4.0),
                                     (math.pi, 4.0),
                                     (3.0 * math.pi / 2.0, 4.0)]):
        if dist + 1.0 > min(hx, hy) - 0.5:
            continue
        bx, by = math.cos(ang) * dist, math.sin(ang) * dist
        _bench_into(bm, bx, by, 0.15, facing=ang - math.pi / 2.0,
                    seat_idx=3, leg_idx=4)
        benches.append([round(bx, 4), round(by, 4)])
        del i

    # Central fountain: base ring + water disk + column + cap sphere.
    _cylinder(bm, 2.0, 2.1, 0.6, (0.0, 0.0, 0.15 + 0.3), segments=24,
              material_index=2)
    _cylinder(bm, 1.7, 1.7, 0.12, (0.0, 0.0, 0.75 + 0.06), segments=24,
              material_index=6)
    _cylinder(bm, 0.30, 0.22, 1.5, (0.0, 0.0, 0.75 + 0.75), segments=12,
              material_index=2)
    _blob(bm, 0.30, (0.0, 0.0, 2.55), material_index=2, subdivisions=2)

    obj, dims, polys = _finish(bm, clean, materials)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "depth": depth,
        "planters": planters,
        "benches": benches,
        "feature": "fountain",
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "materials": [m.name for m in materials],
        "seed": seed,
    }
