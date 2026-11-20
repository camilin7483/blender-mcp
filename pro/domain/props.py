"""Hand-authored props domain pack (v4.5 contract).

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no external assets.
Every function builds ONE joined mesh object grounded at Z=0, assigns
sensible Principled materials per part, and returns a JSON-serializable
dict. Blender 4.5 / 5.2 compatible.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _check_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")


def _check_seed(seed):
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")


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
        sock = bsdf.inputs.get("Transmission Weight", bsdf.inputs.get("Transmission"))
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


def _cylinder(bm, radius1, radius2, depth, center, segments, material_index):
    """Append a Z-axis cylinder centered at *center*."""
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segments,
        radius1=radius1, radius2=radius2, depth=depth,
    )
    bmesh.ops.translate(bm, vec=Vector(center), verts=geo["verts"])
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - before:
        face.material_index = material_index
    return geo["verts"]


def _ball(bm, radius, center, material_index, u_segments=12, v_segments=8,
          scale=None):
    """Append a UV sphere at *center*."""
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_uvsphere(
        bm, u_segments=u_segments, v_segments=v_segments, radius=radius,
    )
    verts = geo["verts"]
    if scale is not None:
        bmesh.ops.scale(bm, vec=Vector(scale), verts=verts)
    bmesh.ops.translate(bm, vec=Vector(center), verts=verts)
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - before:
        face.material_index = material_index
    return verts


def _ground(bm):
    """Translate all verts so the lowest point touches Z=0."""
    bm.verts.ensure_lookup_table()
    if not bm.verts:
        return
    lowest = min(v.co.z for v in bm.verts)
    if abs(lowest) > 1e-9:
        bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, -lowest)),
                            verts=list(bm.verts))


def _create_object(bm, name, materials):
    """Build mesh + object from *bm*, link it, return (object, dims, polys)."""
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
    dims = [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)]
    try:
        for polygon in mesh.polygons:
            polygon.use_smooth = True
    except Exception:
        pass
    return obj, dims, len(mesh.polygons)


# ---------------------------------------------------------------------------
# public functions
# ---------------------------------------------------------------------------

def create_barrel(server, name="Barrel", radius=0.3, height=0.8,
                  segments=16, seed=0) -> dict:
    """Create a staved wooden barrel with metal bands as one joined mesh."""
    _check_name(name)
    _check_seed(seed)
    radius = _check_positive("radius", radius, 0.05, 10.0)
    height = _check_positive("height", height, 0.1, 10.0)
    segments = _check_int("segments", segments, 6, 64)

    rng = random.Random(seed)
    bm = bmesh.new()
    wood = _get_or_create_material(name + "_Wood", (0.42, 0.28, 0.14, 1.0), 0.85)
    metal = _get_or_create_material(name + "_Band", (0.35, 0.35, 0.38, 1.0),
                                    0.45, metallic=0.9)
    materials = [wood, metal]

    # Staved body: stacked rings with a belly bulge; per-stave jitter.
    rings = [(0.0, 0.86), (0.2, 0.96), (0.5, 1.0), (0.8, 0.96), (1.0, 0.86)]
    ring_verts = []
    bm.faces.ensure_lookup_table()
    body_before = set(bm.faces)
    for frac, factor in rings:
        row = []
        for i in range(segments):
            ang = 2.0 * math.pi * i / segments
            jitter = 1.0 + rng.uniform(-0.012, 0.012)
            r = radius * factor * jitter
            row.append(bm.verts.new(Vector(
                (math.cos(ang) * r, math.sin(ang) * r, frac * height))))
        ring_verts.append(row)
    bm.verts.ensure_lookup_table()
    for lower, upper in zip(ring_verts, ring_verts[1:]):
        for i in range(segments):
            try:
                bm.faces.new((lower[i], lower[(i + 1) % segments],
                              upper[(i + 1) % segments], upper[i]))
            except ValueError:
                pass
    # Bottom + top wooden caps.
    for ring, flip in ((ring_verts[0], False), (ring_verts[-1], True)):
        center = bm.verts.new(Vector((0.0, 0.0, ring[0].co.z)))
        bm.verts.ensure_lookup_table()
        for i in range(segments):
            a, b = ring[i], ring[(i + 1) % segments]
            try:
                bm.faces.new((center, b, a) if flip else (center, a, b))
            except ValueError:
                pass
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - body_before:
        face.material_index = 0

    # Metal bands hugging the body at three heights.
    for frac in (0.12, 0.5, 0.88):
        if frac <= 0.2:
            f = 0.86 + (0.96 - 0.86) * (frac / 0.2)
        elif frac <= 0.5:
            f = 0.96 + (1.0 - 0.96) * ((frac - 0.2) / 0.3)
        elif frac <= 0.8:
            f = 1.0 - (1.0 - 0.96) * ((frac - 0.5) / 0.3)
        else:
            f = 0.96 - (0.96 - 0.86) * ((frac - 0.8) / 0.2)
        _cylinder(bm, radius * f + 0.008, radius * f + 0.008,
                  height * 0.055, (0.0, 0.0, frac * height), segments, 1)

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "name": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "radius": radius,
        "height": height,
        "segments": segments,
        "materials": [m.name for m in materials],
        "seed": seed,
    }


def create_crate(server, name="Crate", size=0.6, plank_count=4) -> dict:
    """Create a wooden crate with planks and corner trim as one joined mesh."""
    _check_name(name)
    size = _check_positive("size", size, 0.05, 20.0)
    plank_count = _check_int("plank_count", plank_count, 1, 16)

    bm = bmesh.new()
    wood = _get_or_create_material(name + "_Wood", (0.55, 0.38, 0.20, 1.0), 0.9)
    trim = _get_or_create_material(name + "_Trim", (0.36, 0.24, 0.12, 1.0), 0.9)
    materials = [wood, trim]

    half = size / 2.0
    # Solid core box.
    _box(bm, (size, size, size), (0.0, 0.0, half), 0)
    proud = half + size * 0.015
    slat = size * 0.10
    gap_step = size / plank_count
    for i in range(plank_count):
        z = gap_step * (i + 0.5)
        w = gap_step * 0.82
        _box(bm, (size + slat * 0.3, slat * 0.3, w), (0.0, proud, z), 0)
        _box(bm, (size + slat * 0.3, slat * 0.3, w), (0.0, -proud, z), 0)
        _box(bm, (slat * 0.3, size + slat * 0.3, w), (proud, 0.0, z), 0)
        _box(bm, (slat * 0.3, size + slat * 0.3, w), (-proud, 0.0, z), 0)
    # Corner battens + lid frame.
    post = size * 0.12
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            _box(bm, (post, post, size), (sx * half, sy * half, half), 1)
    _box(bm, (size + post, size + post, post * 0.6),
         (0.0, 0.0, size - post * 0.3), 1)

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "name": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "size": size,
        "plank_count": plank_count,
        "materials": [m.name for m in materials],
    }


def create_chest(server, name="Chest", width=0.8, depth=0.5,
                 height=0.5) -> dict:
    """Create a treasure chest (base + lid + metal bands) as one joined mesh."""
    _check_name(name)
    width = _check_positive("width", width, 0.1, 20.0)
    depth = _check_positive("depth", depth, 0.1, 20.0)
    height = _check_positive("height", height, 0.1, 20.0)

    bm = bmesh.new()
    wood = _get_or_create_material(name + "_Wood", (0.40, 0.25, 0.12, 1.0), 0.8)
    metal = _get_or_create_material(name + "_Metal", (0.55, 0.45, 0.20, 1.0),
                                    0.4, metallic=0.9)
    materials = [wood, metal]

    base_h = height * 0.62
    lid_h = height - base_h
    # Base box.
    _box(bm, (width, depth, base_h), (0.0, 0.0, base_h / 2.0), 0)
    # Lid: box plus a half-cylinder ridge along X for a curved top.
    _box(bm, (width * 1.02, depth * 1.02, lid_h * 0.6),
         (0.0, 0.0, base_h + lid_h * 0.3), 0)
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=16,
        radius1=depth * 0.51, radius2=depth * 0.51, depth=width * 1.02,
    )
    lid_verts = geo["verts"]
    bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)),
                     matrix=Matrix.Rotation(math.pi / 2.0, 3, "Y"),
                     verts=lid_verts)
    bmesh.ops.scale(bm, vec=Vector((1.0, 1.0, lid_h / max(depth * 0.51, 1e-6) * 0.5)),
                    verts=lid_verts)
    # Keep only the upper half of the ridge.
    bm.verts.ensure_lookup_table()
    flat = [v for v in lid_verts if v.co.z < 0.0]
    if flat:
        bmesh.ops.delete(bm, geom=list(flat), context="VERTS")
        bm.faces.ensure_lookup_table()
    bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, base_h + lid_h * 0.6)),
                        verts=[v for v in lid_verts if v in bm.verts])
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - before:
        face.material_index = 0
    # Two metal bands wrapping base + lid, plus a front latch.
    band = width * 0.06
    for x in (-width * 0.3, width * 0.3):
        _box(bm, (band, depth * 1.06, base_h + lid_h * 0.9),
             (x, 0.0, (base_h + lid_h * 0.9) / 2.0), 1)
    _box(bm, (width * 0.12, depth * 0.06, height * 0.22),
         (0.0, depth * 0.53, base_h), 1)

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "name": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "width": width,
        "depth": depth,
        "height": height,
        "materials": [m.name for m in materials],
    }



def _torus(bm, major_rad, minor_rad, major_seg=16, minor_seg=8):
    """Build a torus in the XY plane with explicit vertices and quads."""
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


def create_lantern(server, name="Lantern", height=0.35,
                   radius=0.12) -> dict:
    """Create a lantern (frame, glass panels, handle) as one joined mesh."""
    _check_name(name)
    height = _check_positive("height", height, 0.05, 10.0)
    radius = _check_positive("radius", radius, 0.02, 10.0)
    if radius * 2.0 >= height * 4.0 and radius >= height:
        raise ValueError("radius must be smaller than height")

    bm = bmesh.new()
    metal = _get_or_create_material(name + "_Frame", (0.15, 0.15, 0.16, 1.0),
                                    0.5, metallic=0.85)
    glass = _get_or_create_material(name + "_Glass", (0.9, 0.85, 0.65, 1.0),
                                    0.1, transmission=0.9)
    glow = _get_or_create_material(name + "_Flame", (1.0, 0.6, 0.15, 1.0),
                                   0.5, emission=(1.0, 0.5, 0.1, 1.0))
    materials = [metal, glass, glow]

    base_h = height * 0.08
    cap_h = height * 0.12
    # Bottom tray, top cap, finial knob.
    _cylinder(bm, radius, radius * 1.05, base_h, (0.0, 0.0, base_h / 2.0), 12, 0)
    _cylinder(bm, radius * 0.6, radius * 1.02, cap_h,
              (0.0, 0.0, height - cap_h / 2.0), 12, 0)
    _ball(bm, radius * 0.12, (0.0, 0.0, height + radius * 0.1), 0)
    # Four corner posts.
    post = radius * 0.12
    body_h = height - base_h - cap_h
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            _box(bm, (post, post, body_h),
                 (sx * radius * 0.8, sy * radius * 0.8,
                  base_h + body_h / 2.0), 0)
    # Glass enclosure (single inset box volume).
    _box(bm, (radius * 1.5, radius * 1.5, body_h * 0.95),
         (0.0, 0.0, base_h + body_h / 2.0), 1)
    # Candle + flame.
    _cylinder(bm, radius * 0.25, radius * 0.25, body_h * 0.45,
              (0.0, 0.0, base_h + body_h * 0.225), 10, 2)
    _ball(bm, radius * 0.12, (0.0, 0.0, base_h + body_h * 0.55), 2)
    # Handle: vertical torus ring above the cap.
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    handle_verts = _torus(
        bm, radius * 0.65, radius * 0.06, major_seg=16, minor_seg=8
    )
    bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)),
                     matrix=Matrix.Rotation(math.pi / 2.0, 3, "Y"),
                     verts=handle_verts)
    bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, height + radius * 0.65)),
                        verts=handle_verts)
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - before:
        face.material_index = 0

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "name": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "height": height,
        "radius": radius,
        "materials": [m.name for m in materials],
    }


def create_streetlamp(server, name="StreetLamp", height=3.0,
                      arm_length=0.8) -> dict:
    """Create a street lamp (base, pole, arm, lamp head) as one joined mesh."""
    _check_name(name)
    height = _check_positive("height", height, 0.5, 30.0)
    arm_length = _check_positive("arm_length", arm_length, 0.1, 10.0)
    if arm_length >= height:
        raise ValueError("arm_length must be smaller than height")

    bm = bmesh.new()
    metal = _get_or_create_material(name + "_Iron", (0.10, 0.10, 0.12, 1.0),
                                    0.55, metallic=0.8)
    glass = _get_or_create_material(name + "_Lamp", (1.0, 0.9, 0.7, 1.0),
                                    0.3, emission=(1.0, 0.85, 0.6, 1.0))
    materials = [metal, glass]

    pole_r = height * 0.02
    # Stepped base.
    _cylinder(bm, pole_r * 4.0, pole_r * 5.0, height * 0.04,
              (0.0, 0.0, height * 0.02), 12, 0)
    _cylinder(bm, pole_r * 2.5, pole_r * 3.5, height * 0.06,
              (0.0, 0.0, height * 0.07), 12, 0)
    # Pole.
    pole_base = height * 0.10
    pole_top = height * 0.96
    _cylinder(bm, pole_r * 0.8, pole_r, pole_top - pole_base,
              (0.0, 0.0, (pole_base + pole_top) / 2.0), 12, 0)
    # Collar ring below the arm.
    _cylinder(bm, pole_r * 1.5, pole_r * 1.5, height * 0.02,
              (0.0, 0.0, pole_top - height * 0.05), 12, 0)
    # Horizontal arm.
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=10,
        radius1=pole_r * 0.7, radius2=pole_r * 0.7, depth=arm_length,
    )
    arm_verts = geo["verts"]
    bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)),
                     matrix=Matrix.Rotation(math.pi / 2.0, 3, "Y"),
                     verts=arm_verts)
    bmesh.ops.translate(bm, vec=Vector((arm_length / 2.0, 0.0, pole_top)),
                        verts=arm_verts)
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - before:
        face.material_index = 0
    # Lamp head: shade cone, glowing bulb, top cap.
    hx = arm_length
    shade_r = pole_r * 6.0
    _cylinder(bm, pole_r * 0.8, shade_r, height * 0.05,
              (hx, 0.0, pole_top - height * 0.025), 12, 0)
    _ball(bm, shade_r * 0.45, (hx, 0.0, pole_top - height * 0.055), 1)
    _cylinder(bm, pole_r * 1.2, pole_r * 0.6, height * 0.02,
              (hx, 0.0, pole_top + height * 0.01), 10, 0)

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "name": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "height": height,
        "arm_length": arm_length,
        "materials": [m.name for m in materials],
    }


def create_sword(server, name="Sword", blade_length=0.8,
                 blade_width=0.06, guard_width=0.18) -> dict:
    """Create a sword (blade, guard, grip, pommel) as one joined mesh."""
    _check_name(name)
    blade_length = _check_positive("blade_length", blade_length, 0.1, 10.0)
    blade_width = _check_positive("blade_width", blade_width, 0.01, 1.0)
    guard_width = _check_positive("guard_width", guard_width, 0.05, 2.0)
    if blade_width >= guard_width:
        raise ValueError("blade_width must be smaller than guard_width")

    bm = bmesh.new()
    steel = _get_or_create_material(name + "_Steel", (0.75, 0.78, 0.82, 1.0),
                                    0.3, metallic=1.0)
    brass = _get_or_create_material(name + "_Guard", (0.55, 0.42, 0.18, 1.0),
                                    0.45, metallic=0.9)
    leather = _get_or_create_material(name + "_Grip", (0.30, 0.16, 0.08, 1.0),
                                      0.9)
    materials = [steel, brass, leather]

    pommel_r = blade_width * 0.55
    grip_h = blade_length * 0.16
    guard_h = blade_width * 0.5
    base = pommel_r * 2.0
    # Pommel, grip, guard stacked from the ground up.
    _ball(bm, pommel_r, (0.0, 0.0, pommel_r), 1)
    _cylinder(bm, blade_width * 0.28, blade_width * 0.28, grip_h,
              (0.0, 0.0, base + grip_h / 2.0), 10, 2)
    guard_z = base + grip_h + guard_h / 2.0
    _box(bm, (guard_width, blade_width * 0.7, guard_h), (0.0, 0.0, guard_z), 1)
    # Blade: flattened box + pyramid tip, standing on the guard.
    blade_base = base + grip_h + guard_h
    _box(bm, (blade_width, blade_width * 0.22, blade_length),
         (0.0, 0.0, blade_base + blade_length / 2.0), 0)
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=4,
        radius1=blade_width * 0.72, radius2=0.001,
        depth=blade_width * 2.0,
    )
    tip_verts = geo["verts"]
    bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)),
                     matrix=Matrix.Rotation(math.pi / 4.0, 3, "Z"),
                     verts=tip_verts)
    bmesh.ops.scale(bm, vec=Vector((1.0, 0.22, 1.0)), verts=tip_verts)
    bmesh.ops.translate(
        bm, vec=Vector((0.0, 0.0, blade_base + blade_length + blade_width)),
        verts=tip_verts)
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - before:
        face.material_index = 0

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "name": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "blade_length": blade_length,
        "blade_width": blade_width,
        "guard_width": guard_width,
        "materials": [m.name for m in materials],
    }


def create_shield(server, name="Shield", width=0.6, height=0.8,
                  thickness=0.04) -> dict:
    """Create a curved shield with rim and boss as one joined mesh."""
    _check_name(name)
    width = _check_positive("width", width, 0.1, 10.0)
    height = _check_positive("height", height, 0.1, 10.0)
    thickness = _check_positive("thickness", thickness, 0.005, 1.0)
    if thickness >= min(width, height) / 2.0:
        raise ValueError("thickness must be smaller than half the smallest face")

    bm = bmesh.new()
    wood = _get_or_create_material(name + "_Wood", (0.45, 0.30, 0.16, 1.0), 0.85)
    metal = _get_or_create_material(name + "_Steel", (0.6, 0.62, 0.65, 1.0),
                                    0.4, metallic=0.9)
    materials = [wood, metal]

    seg_x, seg_y = 8, 10
    bulge = width * 0.15
    # Curved front grid, convex toward +Z... built facing -Y? keep facing +Z.
    bm.faces.ensure_lookup_table()
    before = set(bm.faces)
    grid = bmesh.ops.create_grid(bm, x_segments=seg_x, y_segments=seg_y,
                                 size=1.0)
    grid_verts = grid["verts"]
    bmesh.ops.scale(bm, vec=Vector((width / 2.0, height / 2.0, 1.0)),
                    verts=grid_verts)
    for v in grid_verts:
        fx = v.co.x / (width / 2.0)
        v.co.z += bulge * (1.0 - fx * fx)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    grid_faces = list(set(bm.faces) - before)
    for face in grid_faces:
        face.material_index = 0
    # Solidify backward for thickness.
    extruded = bmesh.ops.extrude_face_region(bm, geom=grid_faces)
    back_verts = [e for e in extruded["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, -thickness)), verts=back_verts)
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - before - set(grid_faces):
        face.material_index = 0
    # Center the shield vertically so it grounds at Z=0.
    bmesh.ops.translate(bm, vec=Vector((0.0, 0.0, height / 2.0)),
                        verts=list(bm.verts))
    # Metal rim
    rim = thickness * 1.6
    _box(bm, (width + rim, rim, rim), (0.0, 0.0, height - rim / 2.0), 1)
    _box(bm, (width + rim, rim, rim), (0.0, 0.0, rim / 2.0), 1)
    _box(bm, (rim, rim, height), (width / 2.0, 0.0, height / 2.0), 1)
    _box(bm, (rim, rim, height), (-width / 2.0, 0.0, height / 2.0), 1)
    # Boss: flattened dome on the front center.
    _ball(bm, width * 0.13, (0.0, 0.02, height / 2.0), 1,
          scale=(1.0, 0.55, 1.0))

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "name": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "width": width,
        "height": height,
        "thickness": thickness,
        "materials": [m.name for m in materials],
    }


def create_potion_bottle(server, name="Potion", height=0.2,
                         radius=0.05) -> dict:
    """Create a potion bottle (body, neck, cork, liquid) as one joined mesh."""
    _check_name(name)
    height = _check_positive("height", height, 0.05, 10.0)
    radius = _check_positive("radius", radius, 0.01, 10.0)
    if radius * 2.0 >= height:
        raise ValueError("radius must be smaller than half the height")

    bm = bmesh.new()
    glass = _get_or_create_material(name + "_Glass", (0.35, 0.7, 0.5, 1.0),
                                    0.1, transmission=0.85)
    liquid = _get_or_create_material(name + "_Liquid", (0.75, 0.1, 0.2, 1.0),
                                     0.25, emission=(0.5, 0.05, 0.1, 1.0))
    cork = _get_or_create_material(name + "_Cork", (0.55, 0.40, 0.22, 1.0), 0.95)
    materials = [glass, liquid, cork]

    body_h = height * 0.62
    neck_h = height * 0.24
    cork_h = height * 0.14
    # Rounded glass body.
    _ball(bm, radius, (0.0, 0.0, body_h / 2.0 + radius * 0.2), 0,
          u_segments=16, v_segments=12, scale=(1.0, 1.0, 0.85))
    # Liquid core inside the body.
    _ball(bm, radius * 0.78, (0.0, 0.0, body_h * 0.42), 1,
          u_segments=12, v_segments=8, scale=(1.0, 1.0, 0.7))
    # Neck + cork stopper.
    neck_base = body_h + radius * 0.35
    _cylinder(bm, radius * 0.38, radius * 0.45, neck_h,
              (0.0, 0.0, neck_base + neck_h / 2.0), 12, 0)
    _cylinder(bm, radius * 0.34, radius * 0.38, cork_h,
              (0.0, 0.0, neck_base + neck_h + cork_h / 2.0), 10, 2)

    obj, dims, polys = _create_object(bm, name, materials)
    return {
        "success": True,
        "name": obj.name,
        "dimensions": dims,
        "polygon_count": polys,
        "height": height,
        "radius": radius,
        "materials": [m.name for m in materials],
    }
