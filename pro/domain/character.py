"""Procedural character blockout domain pack.

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry, no armatures, shape keys
or external assets. All functions run on Blender's main thread, validate
their inputs, raise ``ValueError`` with a precise message on bad input and
return plain JSON-serializable dictionaries.

Every output here is an explicit low-poly blockout for proportions and
layout, not an AAA character.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

_BLOCKOUT_LIMITATIONS = (
    "Blockout geometry only: primitive-based proportions for layout and "
    "scale reference, not an AAA character (no sculpt, no rig, no "
    "articulation, no textures)."
)

_VALID_BUILDS = ("slim", "average", "heavy")
_VALID_SIDES = ("L", "R")
_VALID_GARMENTS = ("shirt", "jacket", "robe")


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


def _validate_side(value):
    if not isinstance(value, str):
        raise ValueError(f"side must be one of {list(_VALID_SIDES)} (got {value!r})")
    side = value.strip().upper()
    if side not in _VALID_SIDES:
        raise ValueError(f"side must be one of {list(_VALID_SIDES)} (got {value!r})")
    return side


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


def _limb(bm, radius_top, radius_bottom, depth, location=(0.0, 0.0, 0.0),
          segments=10, tilt_x=0.0, tilt_y=0.0):
    """Add a tapered cylinder (along Z) centered at *location*."""
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segments,
        radius1=radius_bottom, radius2=radius_top, depth=depth,
    )
    verts = geo["verts"]
    if tilt_x:
        bmesh.ops.rotate(
            bm, cent=Vector((0.0, 0.0, 0.0)),
            matrix=Matrix.Rotation(tilt_x, 3, "X"), verts=verts,
        )
    if tilt_y:
        bmesh.ops.rotate(
            bm, cent=Vector((0.0, 0.0, 0.0)),
            matrix=Matrix.Rotation(tilt_y, 3, "Y"), verts=verts,
        )
    bmesh.ops.translate(bm, vec=Vector(location), verts=verts)
    return verts


def _ground(obj):
    """Shift *obj* so its lowest local vertex touches Z=0; returns min z."""
    mesh = obj.data
    min_z = min(v.co.z + obj.location.z for v in mesh.vertices)
    obj.location.z -= min_z
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return 0.0


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def create_humanoid_blockout(server, name="Humanoid", height=1.75,
                             build="average") -> dict:
    """Create a grounded single-mesh humanoid blockout ~height tall."""
    _ = server
    name = _validate_name(name)
    height = _validate_float(height, "height", minimum=0.3, maximum=3.0)
    if not isinstance(build, str):
        raise ValueError(f"build must be one of {list(_VALID_BUILDS)} (got {build!r})")
    build_key = build.strip().lower()
    if build_key not in _VALID_BUILDS:
        raise ValueError(f"build must be one of {list(_VALID_BUILDS)} (got {build!r})")

    width_factor = {"slim": 0.85, "average": 1.0, "heavy": 1.22}[build_key]
    wf = width_factor
    h = height

    foot_h = 0.045 * h
    hip_z = 0.52 * h
    hip_x = 0.055 * h * wf
    shoulder_z = 0.82 * h
    shoulder_x = (0.095 * h * wf) + 0.03 * h
    head_r = 0.072 * h
    head_z = h - head_r  # head top lands exactly on height

    bm = bmesh.new()
    # Feet (front is -Y, so toes point -Y).
    foot_len, foot_w = 0.145 * h, 0.055 * h * wf
    for sign in (-1.0, 1.0):
        _box(bm, foot_w, foot_len, foot_h,
             (sign * hip_x, -0.03 * h, foot_h / 2.0))
    # Legs: tapered cylinders from foot top to hips.
    leg_depth = hip_z - foot_h
    for sign in (-1.0, 1.0):
        _limb(bm, 0.075 * h * wf, 0.048 * h * wf, leg_depth,
              (sign * hip_x, 0.0, foot_h + leg_depth / 2.0))
    # Pelvis and torso.
    _box(bm, 0.165 * h * wf, 0.105 * h, 0.13 * h, (0.0, 0.0, 0.585 * h))
    _box(bm, 0.195 * h * wf, 0.115 * h, 0.24 * h, (0.0, 0.0, 0.72 * h))
    # Arms with slight outward tilt, hands as small boxes.
    arm_len = shoulder_z - 0.56 * h
    for sign in (-1.0, 1.0):
        _limb(bm, 0.038 * h * wf, 0.030 * h * wf, arm_len,
              (sign * shoulder_x, 0.0, shoulder_z - arm_len / 2.0),
              tilt_y=sign * -0.09)
        _box(bm, 0.045 * h * wf, 0.05 * h, 0.10 * h,
             (sign * (shoulder_x + 0.035 * h), 0.0, 0.51 * h))
    # Neck and head.
    _limb(bm, 0.032 * h, 0.036 * h, 0.06 * h, (0.0, 0.0, 0.855 * h))
    _ball(bm, head_r, (0.0, 0.008 * h, head_z), u_segments=20, v_segments=14,
          scale=(0.88, 0.95, 1.0))

    skin = _get_or_create_material(name + "_Skin", (0.65, 0.45, 0.35, 1.0), 0.6)
    obj, dims, polys = _finish(bm, name, [skin])
    _ground(obj)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "height": height,
        "build": build_key,
        "dimensions": [round(d, 6) for d in dims],
        "actual_height": round(dims[2], 6),
        "polygon_count": polys,
        "parts": ["feet", "legs", "pelvis", "torso", "arms", "hands",
                  "neck", "head"],
        "limitations": _BLOCKOUT_LIMITATIONS,
    }


def create_eye_pair(server, name="Eyes", radius=0.012, spacing=0.065,
                    height=1.62) -> dict:
    """Create two eyeball meshes with iris/pupil geometry, facing -Y."""
    _ = server
    name = _validate_name(name)
    radius = _validate_float(radius, "radius", minimum=0.002, maximum=0.1)
    spacing = _validate_float(spacing, "spacing", minimum=0.01, maximum=0.5)
    height = _validate_float(height, "height", minimum=0.1, maximum=3.0)
    if spacing < radius * 2.0:
        raise ValueError(
            f"spacing ({spacing}) must be at least 2x radius ({radius})"
        )

    white = _get_or_create_material("EyeWhite", (0.92, 0.92, 0.92, 1.0), 0.35)
    iris_mat = _get_or_create_material("EyeIris", (0.15, 0.30, 0.45, 1.0), 0.4)
    pupil_mat = _get_or_create_material("EyePupil", (0.02, 0.02, 0.02, 1.0), 0.3)
    materials = [white, iris_mat, pupil_mat]

    created = []
    for side, sign in (("L", 1.0), ("R", -1.0)):
        bm = bmesh.new()
        cx = sign * spacing / 2.0
        # Eyeball.
        start = set(bm.faces)
        _ball(bm, radius, (cx, 0.0, height))
        bm.faces.ensure_lookup_table()
        for face in set(bm.faces) - start:
            face.material_index = 0
        # Iris: flattened disc toward -Y (front).
        start = set(bm.faces)
        _ball(bm, radius * 0.45, (cx, -radius * 0.82, height),
              u_segments=12, v_segments=8, scale=(1.0, 0.35, 1.0))
        bm.faces.ensure_lookup_table()
        for face in set(bm.faces) - start:
            face.material_index = 1
        # Pupil: smaller, slightly further forward.
        start = set(bm.faces)
        _ball(bm, radius * 0.22, (cx, -radius * 0.95, height),
              u_segments=10, v_segments=8, scale=(1.0, 0.35, 1.0))
        bm.faces.ensure_lookup_table()
        for face in set(bm.faces) - start:
            face.material_index = 2
        obj, dims, polys = _finish(bm, f"{name}_{side}", materials)
        created.append({"name": obj.name, "dimensions": dims,
                        "polygon_count": polys})

    return {
        "success": True,
        "eyes": [created[0]["name"], created[1]["name"]],
        "left": created[0]["name"],
        "right": created[1]["name"],
        "radius": radius,
        "spacing": spacing,
        "height": height,
        "details": created,
        "limitations": _BLOCKOUT_LIMITATIONS,
    }


def create_teeth_set(server, name="Teeth", width=0.05, height=0.02,
                     depth=0.04) -> dict:
    """Create upper/lower teeth arches as segmented boxes in one mesh."""
    _ = server
    name = _validate_name(name)
    width = _validate_float(width, "width", minimum=0.01, maximum=0.3)
    height = _validate_float(height, "height", minimum=0.005, maximum=0.2)
    depth = _validate_float(depth, "depth", minimum=0.01, maximum=0.3)

    per_arch = 8
    tooth_w = (width / per_arch) * 0.8
    tooth_h = (height / 2.0) * 0.9
    tooth_d = depth * 0.35

    bm = bmesh.new()
    for zc in (height / 4.0, -height / 4.0):
        for i in range(per_arch):
            t = (i / (per_arch - 1.0)) * 2.0 - 1.0  # -1..1 across the arch
            x = t * width / 2.0
            # U-shaped arch: molars sit further back (+Y), front teeth at -Y.
            y = (t * t) * depth * 0.5 - depth * 0.30
            _box(bm, tooth_w, tooth_d, tooth_h, (x, y, zc))

    enamel = _get_or_create_material(name + "_Enamel",
                                     (0.93, 0.90, 0.82, 1.0), 0.35)
    obj, dims, polys = _finish(bm, name, [enamel])

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "height": height,
        "depth": depth,
        "tooth_count": per_arch * 2,
        "arches": ["upper", "lower"],
        "dimensions": [round(d, 6) for d in dims],
        "polygon_count": polys,
        "limitations": _BLOCKOUT_LIMITATIONS,
    }


def create_hair_cap(server, name="Hair", head_object=None, radius=0.10,
                    strand_count=100, seed=0) -> dict:
    """Create a hair cap shell plus strand edges over a head or the origin."""
    _ = server
    name = _validate_name(name)
    radius = _validate_float(radius, "radius", minimum=0.02, maximum=1.0)
    strand_count = _validate_int(strand_count, "strand_count",
                                 minimum=0, maximum=5000)
    seed = _validate_seed(seed)
    if head_object is not None and not isinstance(head_object, str):
        raise ValueError(f"head_object must be a string or None (got {head_object!r})")

    if head_object is not None:
        head = _require_object(head_object)
        corners = [head.matrix_world @ Vector(corner) for corner in head.bound_box]
        xs = [corner.x for corner in corners]
        ys = [corner.y for corner in corners]
        zs = [corner.z for corner in corners]
        cap_r = radius
        center = Vector((
            (min(xs) + max(xs)) / 2.0,
            (min(ys) + max(ys)) / 2.0,
            max(zs) - radius * 0.15,
        ))
    else:
        center = Vector((0.0, 0.0, radius * 1.1))
        cap_r = radius

    rng = random.Random(seed)
    bm = bmesh.new()
    _ball(bm, cap_r, center, u_segments=20, v_segments=14,
          scale=(1.0, 1.0, 1.05))
    # Keep the cap: delete faces below the hairline cutoff.
    cutoff = center.z - cap_r * 0.25
    bm.faces.ensure_lookup_table()
    for face in [f for f in bm.faces
                 if f.calc_center_median().z < cutoff]:
        bm.faces.remove(face)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
    orphans = [v for v in bm.verts if not v.link_faces]
    for vert in orphans:
        bm.verts.remove(vert)
    bm.verts.ensure_lookup_table()

    # Strands: chains of 2 edges flowing down/back (+Y, -Z) from the cap.
    for _ in range(strand_count):
        theta = rng.uniform(0.0, math.pi * 0.75)
        phi = rng.uniform(0.0, 2.0 * math.pi)
        direction = Vector((
            math.sin(theta) * math.cos(phi),
            math.sin(theta) * math.sin(phi),
            math.cos(theta),
        ))
        root = center + direction * cap_r * 1.02
        length = cap_r * rng.uniform(0.6, 1.4)
        p1 = root + Vector((direction.x * 0.2 * length,
                            direction.y * 0.2 * length + 0.25 * length,
                            -0.55 * length))
        p2 = p1 + Vector((rng.uniform(-0.1, 0.1) * length,
                          0.20 * length,
                          -0.60 * length))
        v0 = bm.verts.new(root)
        v1 = bm.verts.new(p1)
        v2 = bm.verts.new(p2)
        bm.edges.new((v0, v1))
        bm.edges.new((v1, v2))

    hair = _get_or_create_material(name + "_Hair", (0.16, 0.10, 0.07, 1.0), 0.8)
    obj, dims, polys = _finish(bm, name, [hair])

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "radius": cap_r,
        "strand_count": strand_count,
        "head_object": head_object,
        "center": [round(c, 6) for c in center],
        "dimensions": [round(d, 6) for d in dims],
        "polygon_count": polys,
        "seed": seed,
        "limitations": _BLOCKOUT_LIMITATIONS,
    }


def create_garment(server, name="Shirt", body_width=0.40, body_depth=0.22,
                   torso_height=0.55, garment_type="shirt") -> dict:
    """Create a grounded shirt/jacket/robe shell with sleeves."""
    _ = server
    name = _validate_name(name)
    body_width = _validate_float(body_width, "body_width",
                                 minimum=0.1, maximum=2.0)
    body_depth = _validate_float(body_depth, "body_depth",
                                 minimum=0.05, maximum=2.0)
    torso_height = _validate_float(torso_height, "torso_height",
                                   minimum=0.1, maximum=2.5)
    if not isinstance(garment_type, str):
        raise ValueError(
            f"garment_type must be one of {list(_VALID_GARMENTS)} (got {garment_type!r})"
        )
    gtype = garment_type.strip().lower()
    if gtype not in _VALID_GARMENTS:
        raise ValueError(
            f"garment_type must be one of {list(_VALID_GARMENTS)} (got {garment_type!r})"
        )

    flare = {"shirt": 1.0, "jacket": 1.08, "robe": 1.35}[gtype]
    sleeve_len = {"shirt": 0.22, "jacket": 0.52, "robe": 0.55}[gtype]
    top_w, top_d = body_width * 1.06, body_depth * 1.12
    bot_w, bot_d = body_width * flare, body_depth * flare
    if gtype == "robe":
        torso_height = torso_height * 1.6

    bm = bmesh.new()
    mid_w, mid_d = (top_w + bot_w) / 2.0, (top_d + bot_d) / 2.0
    # Shell: stacked boxes (shoulders / waist / hem) read as one torso shell.
    _box(bm, top_w, top_d, torso_height * 0.30,
         (0.0, 0.0, torso_height * 0.85))
    _box(bm, mid_w, mid_d, torso_height * 0.35,
         (0.0, 0.0, torso_height * 0.525))
    _box(bm, bot_w, bot_d, torso_height * 0.35,
         (0.0, 0.0, torso_height * 0.175))
    # Sleeves: tapered cylinders angled down/out from the shoulders.
    shoulder_z = torso_height * 0.88
    for sign in (-1.0, 1.0):
        geo = bmesh.ops.create_cone(
            bm, cap_ends=True, segments=10,
            radius1=0.055, radius2=0.075, depth=sleeve_len,
        )
        verts = geo["verts"]
        bmesh.ops.rotate(
            bm, cent=Vector((0.0, 0.0, 0.0)),
            matrix=Matrix.Rotation(math.pi / 2.0 + sign * -0.35, 3, "Y"),
            verts=verts,
        )
        bmesh.ops.translate(
            bm,
            vec=Vector((sign * (top_w / 2.0 + sleeve_len / 2.0 * 0.9),
                        0.0, shoulder_z - 0.06)),
            verts=verts,
        )

    fabric = _get_or_create_material(name + "_Fabric",
                                     (0.25, 0.32, 0.50, 1.0), 0.85)
    obj, dims, polys = _finish(bm, name, [fabric])
    _ground(obj)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "garment_type": gtype,
        "body_width": body_width,
        "body_depth": body_depth,
        "torso_height": round(torso_height, 6),
        "dimensions": [round(d, 6) for d in dims],
        "polygon_count": polys,
        "limitations": _BLOCKOUT_LIMITATIONS,
    }


def create_face_landmarks(server, head_object, eye_spacing=0.065,
                          head_height=0.22) -> dict:
    """Create empty landmarks (eyes, nose, mouth, ears, chin) for a head."""
    _ = server
    head = _require_object(head_object)
    eye_spacing = _validate_float(eye_spacing, "eye_spacing",
                                  minimum=0.01, maximum=0.5)
    head_height = _validate_float(head_height, "head_height",
                                  minimum=0.05, maximum=1.0)

    corners = [head.matrix_world @ Vector(corner) for corner in head.bound_box]
    xs = [corner.x for corner in corners]
    ys = [corner.y for corner in corners]
    zs = [corner.z for corner in corners]
    loc = Vector((
        (min(xs) + max(xs)) / 2.0,
        (min(ys) + max(ys)) / 2.0,
        max(zs) - head_height / 2.0,
    ))
    head_r = head_height / 2.0
    # Front is -Y.
    offsets = {
        "eye_L": (eye_spacing / 2.0, -head_r * 0.82, head_height * 0.10),
        "eye_R": (-eye_spacing / 2.0, -head_r * 0.82, head_height * 0.10),
        "nose": (0.0, -head_r * 1.02, -head_height * 0.05),
        "mouth": (0.0, -head_r * 0.86, -head_height * 0.22),
        "ear_L": (head_r * 0.95, 0.0, 0.0),
        "ear_R": (-head_r * 0.95, 0.0, 0.0),
        "chin": (0.0, -head_r * 0.45, -head_height * 0.5),
    }
    created = {}
    for label, off in offsets.items():
        empty = bpy.data.objects.new(f"{head.name}_{label}", None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.location = loc + Vector(off)
        _link(empty)
        created[label] = [round(c, 6) for c in empty.location]

    return {
        "success": True,
        "head": head.name,
        "landmarks": list(created.keys()),
        "positions": created,
        "eye_spacing": eye_spacing,
        "head_height": head_height,
        "limitations": _BLOCKOUT_LIMITATIONS,
    }


def create_hand_blockout(server, name="Hand", side="L",
                         scale=1.0) -> dict:
    """Create a palm + fingers + thumb blockout, mirrored by *side*."""
    _ = server
    name = _validate_name(name)
    side = _validate_side(side)
    scale = _validate_float(scale, "scale", minimum=0.1, maximum=5.0)
    mirror = 1.0 if side == "L" else -1.0

    bm = bmesh.new()
    # Palm: width X, length Y (fingers toward -Y), thickness Z.
    palm_w, palm_l, palm_t = 0.085 * scale, 0.095 * scale, 0.028 * scale
    _box(bm, palm_w, palm_l, palm_t, (0.0, 0.0, 0.0))
    # Four fingers: two-segment boxes fanning slightly outward.
    finger_w = 0.016 * scale
    finger_spread = [-0.030, -0.010, 0.010, 0.030]
    finger_len = [0.070, 0.080, 0.075, 0.060]
    for fx, fl in zip(finger_spread, finger_len):
        fx = fx * scale * mirror
        seg1 = fl * scale * 0.55
        seg2 = fl * scale * 0.45
        y1 = -palm_l / 2.0 - seg1 / 2.0
        _box(bm, finger_w * scale, seg1, 0.020 * scale, (fx, y1, 0.0))
        y2 = -palm_l / 2.0 - seg1 - seg2 / 2.0 + 0.002
        _box(bm, finger_w * scale * 0.9, seg2, 0.017 * scale, (fx, y2, -0.004))
    # Thumb: two segments angled out from the palm side.
    tx = mirror * palm_w / 2.0
    _box(bm, 0.030 * scale, 0.018 * scale, 0.022 * scale,
         (tx + mirror * 0.020 * scale, -0.005, 0.0), rot_z=mirror * -0.6)
    _box(bm, 0.026 * scale, 0.016 * scale, 0.019 * scale,
         (tx + mirror * 0.042 * scale, -0.022 * scale, -0.002),
         rot_z=mirror * -0.9)

    skin = _get_or_create_material(name + "_Skin", (0.65, 0.45, 0.35, 1.0), 0.6)
    obj, dims, polys = _finish(bm, f"{name}_{side}", [skin])

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "side": side,
        "scale": scale,
        "dimensions": [round(d, 6) for d in dims],
        "polygon_count": polys,
        "limitations": _BLOCKOUT_LIMITATIONS,
    }


def create_foot_blockout(server, name="Foot", side="L",
                         length=0.26) -> dict:
    """Create a grounded foot + toes blockout of approximately *length*."""
    _ = server
    name = _validate_name(name)
    side = _validate_side(side)
    length = _validate_float(length, "length", minimum=0.05, maximum=0.6)
    mirror = 1.0 if side == "L" else -1.0

    bm = bmesh.new()
    foot_w = length * 0.38
    foot_h = length * 0.28
    # Main foot volume (toes toward -Y) plus a raised heel/ankle block.
    _box(bm, foot_w, length * 0.78, foot_h * 0.62,
         (0.0, length * 0.06, foot_h * 0.31))
    _box(bm, foot_w * 0.85, length * 0.30, foot_h,
         (0.0, length * 0.32, foot_h / 2.0))
    # Five toes, big toe on the medial side (mirrored by *side*).
    toe_sizes = [0.032, 0.024, 0.022, 0.020, 0.018]
    span = foot_w * 0.80
    for i, ts in enumerate(toe_sizes):
        frac = i / (len(toe_sizes) - 1.0)  # 0 = big toe .. 1 = little toe
        tx = mirror * (span / 2.0 - frac * span)
        _ball(bm, ts * (length / 0.26), (tx, -length * 0.36, ts * 0.8),
              u_segments=10, v_segments=8, scale=(1.0, 1.3, 0.8))

    skin = _get_or_create_material(name + "_Skin", (0.65, 0.45, 0.35, 1.0), 0.6)
    obj, dims, polys = _finish(bm, f"{name}_{side}", [skin])
    _ground(obj)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "side": side,
        "length": length,
        "dimensions": [round(d, 6) for d in dims],
        "polygon_count": polys,
        "limitations": _BLOCKOUT_LIMITATIONS,
    }
