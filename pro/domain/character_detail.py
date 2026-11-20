"""Facial detail blockout domain pack.

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no sculpting, textures,
hair dynamics or external assets. All functions run on Blender's main
thread, validate their inputs, raise ``ValueError`` with a precise message
on bad input and return plain JSON-serializable dictionaries.

Every output here is an explicit low-poly detail blockout for proportions
and layout, not a photoreal feature.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

_DETAIL_LIMITATIONS = (
    "Detail blockouts only: low-poly proportion guides for facial and hand "
    "details (not photoreal sculpts; no pores, wrinkles, hair dynamics, "
    "nail beds or textures)."
)

# Fixed half-gap between the two eyes used by the eyelash pair (matches the
# default eye spacing of 0.065 in character.create_eye_pair).
_EYELASH_HALF_GAP = 0.0325


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_float(value, label, minimum=None, maximum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number (got {value!r})")
    if isinstance(value, bool) or not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number (got {value!r})")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {number})")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {number})")
    return number


def _validate_int(value, label, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {value})")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {value})")
    return value


def _validate_seed(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"seed must be an integer (got {value!r})")
    return value


def _require_object(name, label="head_object"):
    clean = _validate_name(name, label)
    obj = bpy.data.objects.get(clean)
    if obj is None:
        raise ValueError(f"Object '{clean}' not found")
    return obj


# ---------------------------------------------------------------------------
# Geometry helpers (data API + bmesh only: Blender 4.5/5.2 compatible)
# ---------------------------------------------------------------------------

def _get_or_create_material(name, rgba, roughness=0.7):
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
    return mat


def _skin_material(name):
    return _get_or_create_material(name + "_Skin", (0.65, 0.45, 0.35, 1.0), 0.6)


def _hair_material(name):
    return _get_or_create_material(name + "_Hair", (0.16, 0.10, 0.07, 1.0), 0.8)


def _link(obj):
    try:
        collection = bpy.context.collection or bpy.context.scene.collection
    except AttributeError:
        collection = bpy.context.scene.collection
    collection.objects.link(obj)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return obj


def _finish(bm, name, materials=()):
    """Build mesh + object from *bm*, link it, return (object, dims, polys)."""
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    for mat in materials:
        mesh.materials.append(mat)
    _link(obj)
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    dims = [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)]
    return obj, dims, len(mesh.polygons)


def _box(bm, size_x, size_y, size_z, location=(0.0, 0.0, 0.0), rot_z=0.0):
    """Add a cuboid centered at *location*; returns created verts."""
    geo = bmesh.ops.create_cube(bm, size=1.0)
    verts = geo["verts"]
    bmesh.ops.scale(bm, vec=Vector((size_x, size_y, size_z)), verts=verts)
    if rot_z:
        bmesh.ops.rotate(
            bm, cent=Vector((0.0, 0.0, 0.0)),
            matrix=Matrix.Rotation(rot_z, 3, "Z"), verts=verts,
        )
    bmesh.ops.translate(bm, vec=Vector(location), verts=verts)
    return verts


def _ball(bm, radius, location=(0.0, 0.0, 0.0), u_segments=16,
          v_segments=12, scale=None):
    """Add a UV sphere at *location*; returns created verts."""
    geo = bmesh.ops.create_uvsphere(
        bm, u_segments=u_segments, v_segments=v_segments, radius=radius,
    )
    verts = geo["verts"]
    if scale is not None:
        bmesh.ops.scale(bm, vec=Vector(scale), verts=verts)
    bmesh.ops.translate(bm, vec=Vector(location), verts=verts)
    return verts


def _strand(bm, root, mid, tip):
    """Add a 3-vert / 2-edge strand segment; returns the new verts."""
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    v0 = bm.verts.new(Vector(root))
    v1 = bm.verts.new(Vector(mid))
    v2 = bm.verts.new(Vector(tip))
    bm.edges.new((v0, v1))
    bm.edges.new((v1, v2))
    return (v0, v1, v2)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def create_nose(server, name="Nose", width=0.035, height=0.05,
                depth=0.04) -> dict:
    """Create a wedge/rounded nose blockout (bridge, tip, nostril wings)."""
    _ = server
    name = _validate_name(name)
    width = _validate_float(width, "width", minimum=0.005, maximum=0.2)
    height = _validate_float(height, "height", minimum=0.005, maximum=0.3)
    depth = _validate_float(depth, "depth", minimum=0.005, maximum=0.3)

    bm = bmesh.new()
    # Nasal bridge: tapered box running down the face (front is -Y).
    _box(bm, width * 0.55, depth * 0.55, height, (0.0, depth * 0.05, 0.0))
    # Rounded tip protruding forward and slightly down.
    _ball(bm, width * 0.45, (0.0, -depth * 0.35, -height * 0.32),
          u_segments=14, v_segments=10, scale=(1.0, 1.1, 0.9))
    # Nostril wings flanking the tip.
    for sign in (-1.0, 1.0):
        _ball(bm, width * 0.22, (sign * width * 0.32, -depth * 0.15,
                                 -height * 0.42),
              u_segments=10, v_segments=8, scale=(1.0, 1.2, 0.7))

    skin = _skin_material(name)
    obj, dims, polys = _finish(bm, name, [skin])

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "height": height,
        "depth": depth,
        "parts": ["bridge", "tip", "nostril_wing_L", "nostril_wing_R"],
        "dimensions": [round(d, 6) for d in dims],
        "polygon_count": polys,
        "limitations": _DETAIL_LIMITATIONS,
    }


def create_ear_pair(server, name="Ears", width=0.03, height=0.06,
                    spacing=0.16) -> dict:
    """Create two outer-ear meshes (shell + inner ridge) at +/- spacing."""
    _ = server
    name = _validate_name(name)
    width = _validate_float(width, "width", minimum=0.005, maximum=0.2)
    height = _validate_float(height, "height", minimum=0.01, maximum=0.3)
    spacing = _validate_float(spacing, "spacing", minimum=0.05, maximum=0.5)
    if spacing < width:
        raise ValueError(
            f"spacing ({spacing}) must be >= width ({width}) "
            "so the ears do not overlap"
        )

    skin = _skin_material(name)
    created = []
    for side, sign in (("L", 1.0), ("R", -1.0)):
        bm = bmesh.new()
        cx = sign * spacing / 2.0
        outer_r = height / 2.0
        # Outer shell: thin in X (sideways), tall in Z, some depth in Y.
        _ball(bm, outer_r, (cx, 0.0, 0.0), u_segments=16, v_segments=12,
              scale=(width / height, 0.55, 1.0))
        # Inner ridge (antihelix hint), offset outward in X.
        _ball(bm, height * 0.28, (cx + sign * width * 0.18, -height * 0.03, 0.0),
              u_segments=12, v_segments=8, scale=(0.5, 0.4, 1.0))
        obj, dims, polys = _finish(bm, f"{name}_{side}", [skin])
        created.append({"name": obj.name, "dimensions": dims,
                        "polygon_count": polys})

    return {
        "success": True,
        "ears": [created[0]["name"], created[1]["name"]],
        "left": created[0]["name"],
        "right": created[1]["name"],
        "width": width,
        "height": height,
        "spacing": spacing,
        "details": created,
        "limitations": _DETAIL_LIMITATIONS,
    }


def create_mouth(server, name="Mouth", width=0.05, height=0.018,
                 depth=0.02) -> dict:
    """Create a mouth blockout (upper/lower lips plus dark opening)."""
    _ = server
    name = _validate_name(name)
    width = _validate_float(width, "width", minimum=0.01, maximum=0.3)
    height = _validate_float(height, "height", minimum=0.003, maximum=0.1)
    depth = _validate_float(depth, "depth", minimum=0.005, maximum=0.2)

    lip = _get_or_create_material(name + "_Lip", (0.55, 0.25, 0.22, 1.0), 0.55)
    cavity = _get_or_create_material(name + "_Cavity",
                                     (0.08, 0.02, 0.02, 1.0), 0.9)

    bm = bmesh.new()
    # Upper lip.
    start = set(bm.faces)
    _box(bm, width, depth * 0.5, height * 0.35, (0.0, 0.0, height * 0.28))
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - start:
        face.material_index = 0
    # Lower lip, slightly fuller and forward (front is -Y).
    start = set(bm.faces)
    _box(bm, width * 0.92, depth * 0.55, height * 0.38,
         (0.0, -depth * 0.06, -height * 0.28))
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - start:
        face.material_index = 0
    # Dark mouth opening between the lips.
    start = set(bm.faces)
    _box(bm, width * 0.85, depth * 0.55, height * 0.30,
         (0.0, -depth * 0.10, 0.0))
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - start:
        face.material_index = 1

    obj, dims, polys = _finish(bm, name, [lip, cavity])

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "height": height,
        "depth": depth,
        "parts": ["upper_lip", "lower_lip", "opening"],
        "dimensions": [round(d, 6) for d in dims],
        "polygon_count": polys,
        "limitations": _DETAIL_LIMITATIONS,
    }


def create_brow_pair(server, name="Brows", width=0.04, height=0.01,
                     spacing=0.065) -> dict:
    """Create two arched brow strips from angled segments at +/- spacing."""
    _ = server
    name = _validate_name(name)
    width = _validate_float(width, "width", minimum=0.01, maximum=0.2)
    height = _validate_float(height, "height", minimum=0.002, maximum=0.05)
    spacing = _validate_float(spacing, "spacing", minimum=0.02, maximum=0.3)
    if spacing < width:
        raise ValueError(
            f"spacing ({spacing}) must be >= width ({width}) "
            "so the brows do not overlap"
        )

    hair = _hair_material(name)
    strip_depth = width * 0.25
    segments = 5
    arch = width * 0.12
    created = []
    for side, sign in (("L", 1.0), ("R", -1.0)):
        bm = bmesh.new()
        cx = sign * spacing / 2.0
        seg_w = (width / segments) * 1.2
        for i in range(segments):
            t = (i / (segments - 1.0)) * 2.0 - 1.0  # -1..1 across the brow
            x = cx + t * width / 2.0
            z = arch * (1.0 - t * t)
            # Slope of the arch dz/dx gives the segment tilt about Y.
            slope = -arch * 2.0 * t / (width / 2.0) if width else 0.0
            angle = math.atan(slope)
            geo = bmesh.ops.create_cube(bm, size=1.0)
            verts = geo["verts"]
            bmesh.ops.scale(
                bm, vec=Vector((seg_w, strip_depth, height)), verts=verts)
            bmesh.ops.rotate(
                bm, cent=Vector((0.0, 0.0, 0.0)),
                matrix=Matrix.Rotation(angle, 3, "Y"), verts=verts)
            bmesh.ops.translate(
                bm, vec=Vector((x, 0.0, z)), verts=verts)
        obj, dims, polys = _finish(bm, f"{name}_{side}", [hair])
        created.append({"name": obj.name, "dimensions": dims,
                        "polygon_count": polys})

    return {
        "success": True,
        "brows": [created[0]["name"], created[1]["name"]],
        "left": created[0]["name"],
        "right": created[1]["name"],
        "width": width,
        "height": height,
        "spacing": spacing,
        "segment_count": segments,
        "details": created,
        "limitations": _DETAIL_LIMITATIONS,
    }


def create_eyelash_pair(server, name="Eyelashes", radius=0.014,
                        strand_count=24, seed=0) -> dict:
    """Create paired upper-lid lash strands fanning around eye radius."""
    _ = server
    name = _validate_name(name)
    radius = _validate_float(radius, "radius", minimum=0.003, maximum=0.1)
    strand_count = _validate_int(strand_count, "strand_count",
                                 minimum=2, maximum=500)
    seed = _validate_seed(seed)

    hair = _hair_material(name)
    rng = random.Random(seed)
    # Split strands across both lids; the left lid takes the odd one.
    left_count = (strand_count + 1) // 2
    right_count = strand_count // 2
    created = []
    for side, sign, count in (("L", 1.0, left_count),
                              ("R", -1.0, right_count)):
        bm = bmesh.new()
        cx = sign * _EYELASH_HALF_GAP
        for i in range(count):
            frac = i / max(count - 1, 1)
            # Upper-lid arc from outer to inner corner (20..160 degrees).
            angle = math.radians(20.0 + frac * 140.0)
            rim = Vector((cx + math.cos(angle) * radius,
                          0.0,
                          math.sin(angle) * radius))
            # Lashes fan outward/up with a forward (-Y) curl.
            flare = radius * rng.uniform(0.7, 1.1)
            radial = Vector((math.cos(angle) * 0.45 * flare,
                             -0.55 * flare,
                             (0.55 + math.sin(angle) * 0.35) * flare))
            mid = rim + radial * 0.55 + Vector((0.0, 0.0, radius * 0.12))
            tip = rim + radial
            _strand(bm, rim, mid, tip)
        obj, dims, polys = _finish(bm, f"{name}_{side}", [hair])
        created.append({"name": obj.name, "dimensions": dims,
                        "polygon_count": polys,
                        "strand_count": count,
                        "edge_count": count * 2})

    return {
        "success": True,
        "eyelashes": [created[0]["name"], created[1]["name"]],
        "left": created[0]["name"],
        "right": created[1]["name"],
        "radius": radius,
        "strand_count": strand_count,
        "eye_half_gap": _EYELASH_HALF_GAP,
        "seed": seed,
        "details": created,
        "limitations": _DETAIL_LIMITATIONS,
    }


def create_hair_strands(server, name="HairStrands", radius=0.1,
                        strand_count=200, length=0.2, seed=0) -> dict:
    """Create one mesh of strand segments radiating from a scalp dome."""
    _ = server
    name = _validate_name(name)
    radius = _validate_float(radius, "radius", minimum=0.02, maximum=1.0)
    strand_count = _validate_int(strand_count, "strand_count",
                                 minimum=1, maximum=5000)
    length = _validate_float(length, "length", minimum=0.01, maximum=1.0)
    seed = _validate_seed(seed)

    rng = random.Random(seed)
    center = Vector((0.0, 0.0, radius))
    bm = bmesh.new()
    for _ in range(strand_count):
        # Roots spread over the upper scalp dome (front is -Y).
        theta = rng.uniform(0.0, 1.9)
        phi = rng.uniform(0.0, 2.0 * math.pi)
        direction = Vector((
            math.sin(theta) * math.cos(phi),
            math.sin(theta) * math.sin(phi),
            math.cos(theta),
        ))
        root = center + direction * radius
        strand_len = length * rng.uniform(0.6, 1.1)
        fall = Vector((
            direction.x * 0.35 * strand_len + rng.uniform(-0.1, 0.1) * length,
            direction.y * 0.35 * strand_len + 0.15 * strand_len,
            -0.75 * strand_len,
        ))
        mid = root + fall * 0.55
        tip = root + fall
        _strand(bm, root, mid, tip)

    hair = _hair_material(name)
    obj, dims, polys = _finish(bm, name, [hair])

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "radius": radius,
        "strand_count": strand_count,
        "length": length,
        "center": [round(c, 6) for c in center],
        "edge_count": strand_count * 2,
        "dimensions": [round(d, 6) for d in dims],
        "polygon_count": polys,
        "seed": seed,
        "limitations": _DETAIL_LIMITATIONS,
    }


def create_fingernails(server, name="Nails", radius=0.006,
                       count=10) -> dict:
    """Create small rounded nail plates arranged as two hands in one mesh."""
    _ = server
    name = _validate_name(name)
    radius = _validate_float(radius, "radius", minimum=0.001, maximum=0.03)
    count = _validate_int(count, "count", minimum=1, maximum=20)

    # Split plates across two hands; the left hand takes the odd one.
    left_count = (count + 1) // 2
    right_count = count // 2
    bm = bmesh.new()
    placements = []
    for hand, sign, hand_count in (("L", 1.0, left_count),
                                   ("R", -1.0, right_count)):
        hand_x = sign * 0.055
        for i in range(hand_count):
            # Spread fingers along X; the middle finger sits further
            # forward (-Y) to suggest natural finger lengths.
            offset = (i - (hand_count - 1.0) / 2.0) * radius * 3.4
            forward = abs(i - (hand_count - 1.0) / 2.0) * radius * 1.2
            pos = (hand_x + offset, forward, 0.0)
            _ball(bm, radius, pos, u_segments=10, v_segments=8,
                  scale=(1.0, 1.35, 0.32))
            placements.append({
                "hand": hand,
                "position": [round(c, 6) for c in pos],
            })

    nail = _get_or_create_material(name + "_Nail",
                                    (0.87, 0.62, 0.55, 1.0), 0.4)
    obj, dims, polys = _finish(bm, name, [nail])

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "radius": radius,
        "count": count,
        "hands": ["L", "R"],
        "placements": placements,
        "dimensions": [round(d, 6) for d in dims],
        "polygon_count": polys,
        "limitations": _DETAIL_LIMITATIONS,
    }


def create_face_proportions(server, head_object, height=0.22) -> dict:
    """Create empty landmarks (brow/eyes/nose/mouth/chin/ears) from head top."""
    _ = server
    head = _require_object(head_object)
    height = _validate_float(height, "height", minimum=0.05, maximum=1.0)

    corners = [head.matrix_world @ Vector(corner) for corner in head.bound_box]
    xs = [corner.x for corner in corners]
    ys = [corner.y for corner in corners]
    zs = [corner.z for corner in corners]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)  # front is -Y, so min_y faces forward
    top = max(zs)
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    half_depth = (max_y - min_y) / 2.0

    eye_x = height * 0.15
    offsets = {
        # (dx from center X, Y mode, distance below the head top)
        "brow": (0.0, min_y + 0.003, 0.30 * height),
        "eye_L": (eye_x, min_y + 0.003, 0.36 * height),
        "eye_R": (-eye_x, min_y + 0.003, 0.36 * height),
        "nose": (0.0, min_y - 0.005, 0.55 * height),
        "mouth": (0.0, min_y - 0.001, 0.70 * height),
        "chin": (0.0, min_y + half_depth * 0.6, 1.0 * height),
        "ear_L": (None, cy, 0.55 * height),  # placeholders, set below
        "ear_R": (None, cy, 0.55 * height),
    }
    positions = {}
    created = []
    for label, (dx, y, below_top) in offsets.items():
        empty = bpy.data.objects.new(f"{head.name}_{label}", None)
        empty.empty_display_type = "PLAIN_AXES"
        if label == "ear_L":
            empty.location = Vector((max_x, y, top - below_top))
        elif label == "ear_R":
            empty.location = Vector((min_x, y, top - below_top))
        else:
            empty.location = Vector((cx + dx, y, top - below_top))
        _link(empty)
        positions[label] = [round(c, 6) for c in empty.location]
        created.append(empty.name)

    return {
        "success": True,
        "head": head.name,
        "height": height,
        "top": round(top, 6),
        "landmarks": sorted(positions.keys()),
        "empties": created,
        "positions": positions,
        "limitations": _DETAIL_LIMITATIONS,
    }
