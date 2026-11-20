"""Procedural character groom / rig / studio domain pack (v4.9).

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry on Blender's main thread.
All functions validate their inputs, raise ``ValueError`` with a precise
message on bad input and return plain JSON-serializable dictionaries.

Every output here is a procedural base for layout and previz, not an AAA
or photoreal character asset. ``character_quality_report`` always reports
``aaa_certified: False``.
"""

import math
import random

import bmesh
import bpy
from mathutils import Vector

_PROCEDURAL_TIER = "procedural_high_detail"

_MISSING_FOR_AAA = [
    "scanned or artist-sculpted primary forms",
    "UDIM texture sets",
    "pore-level maps (normal/displacement)",
    "guide-based groom with dynamics",
    "facial FACS rig",
    "human art-direction review",
]

_FACIAL_BONE_STEMS = (
    "jaw", "eye", "brow", "eyelid", "mouth", "lip",
    "cheek", "tongue", "nose", "ear",
)

_MIRROR_TOLERANCE = 1e-4


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


def _validate_vector3(value, label):
    try:
        items = [float(item) for item in value]
    except (TypeError, ValueError):
        raise ValueError(
            f"{label} must be a sequence of 3 numbers (got {value!r})"
        )
    if len(items) != 3 or not all(math.isfinite(item) for item in items):
        raise ValueError(
            f"{label} must be a sequence of 3 finite numbers (got {value!r})"
        )
    return items


def _require_object(name, label="head_object"):
    clean = _validate_name(name, label)
    obj = bpy.data.objects.get(clean)
    if obj is None:
        raise ValueError(f"Object '{clean}' not found")
    return obj


def _require_mesh(name, label="mesh_name"):
    obj = _require_object(name, label)
    if obj.type != "MESH":
        raise ValueError(
            f"Object '{obj.name}' is not a mesh (got {obj.type})"
        )
    if obj.data is None:
        raise ValueError(f"Mesh '{obj.name}' has no mesh data")
    return obj


def _validate_optional_object(value, label):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"{label} must be a string or None (got {value!r})"
        )
    return _require_object(value, label)


def _validate_hair_objects(value):
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    else:
        try:
            items = list(value)
        except TypeError:
            raise ValueError(
                "hair_objects must be a sequence of object names or None "
                f"(got {value!r})"
            )
    cleaned = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                "hair_objects must contain non-empty strings "
                f"(got {value!r})"
            )
        obj = bpy.data.objects.get(item.strip())
        if obj is None:
            raise ValueError(f"Hair object '{item.strip()}' not found")
        cleaned.append(obj)
    return cleaned


def _round3(values):
    return [round(float(value), 6) for value in values]


# ---------------------------------------------------------------------------
# Geometry helpers (data API only: Blender 4.5/5.2 compatible)
# ---------------------------------------------------------------------------

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


def _hair_material(name):
    return _get_or_create_material(name + "_Hair", (0.16, 0.10, 0.07, 1.0), 0.6)


def _aabb_world(obj):
    obj = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _new_curve_object(name, bevel_depth, material):
    """Create an empty CURVE object with hair-like render settings."""
    if bpy.data.objects.get(name) is not None:
        raise ValueError(f"Object '{name}' already exists")
    curve_data = bpy.data.curves.new(name + "Data", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = float(bevel_depth)
    try:
        curve_data.bevel_resolution = 1
    except (AttributeError, TypeError):
        pass
    try:
        curve_data.use_fill_caps = True
    except (AttributeError, TypeError):
        pass
    obj = bpy.data.objects.new(name, curve_data)
    if material is not None:
        curve_data.materials.append(material)
    _link(obj)
    return curve_data, obj


def _add_bezier_strand(curve_data, points, radii):
    """Add one tapered BEZIER spline through *points* with per-point *radii*."""
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for bp, co, radius in zip(spline.bezier_points, points, radii):
        bp.co = Vector(co)
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
        bp.radius = float(radius)
    spline.use_cyclic_u = False
    return spline


def _strand_bounds(curve_data):
    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]
    total_points = 0
    for spline in curve_data.splines:
        if spline.type == "BEZIER":
            pts = [bp.co for bp in spline.bezier_points]
        else:
            pts = [Vector((p.co[0], p.co[1], p.co[2])) for p in spline.points]
        total_points += len(pts)
        for pt in pts:
            for i in range(3):
                lo[i] = min(lo[i], float(pt[i]))
                hi[i] = max(hi[i], float(pt[i]))
    if total_points == 0:
        lo = hi = [0.0, 0.0, 0.0]
    return lo, hi, total_points


def _curve_report(obj, curve_data):
    lo, hi, total_points = _strand_bounds(curve_data)
    dims = [hi[i] - lo[i] for i in range(3)]
    return {
        "bounds_min": [round(v, 6) for v in lo],
        "bounds_max": [round(v, 6) for v in hi],
        "dimensions": [round(v, 6) for v in dims],
        "spline_count": len(curve_data.splines),
        "point_count": total_points,
    }


def _scalp_frame(head_obj):
    """Return (scalp_center, scalp_radius, top, cx, cy, width, height)."""
    if head_obj is None:
        center = Vector((0.0, 0.0, 0.0))
        return center, 0.09, 0.09, 0.0, 0.0, 0.18, 0.18
    min_x, max_x, min_y, max_y, min_z, max_z = _aabb_world(head_obj)
    width = max_x - min_x
    depth = max_y - min_y
    height = max_z - min_z
    if height <= 0.0:
        raise ValueError(f"Object '{head_obj.name}' has zero height")
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    radius = max(min(width, depth) / 2.0, 0.02)
    center = Vector((cx, cy, max_z - radius))
    return center, radius, max_z, cx, cy, width, height


def _eye_frame(head_obj):
    """Return (eye_z, brow_z, half_gap, front_y, cx) for the eye region."""
    if head_obj is None:
        return 0.0, 0.02, 0.0325, -0.09, 0.0
    min_x, max_x, min_y, max_y, _min_z, max_z = _aabb_world(head_obj)
    width = max_x - min_x
    height = max_z - _min_z
    if height <= 0.0:
        raise ValueError(f"Object '{head_obj.name}' has zero height")
    cx = (min_x + max_x) / 2.0
    front_y = min_y  # front of the character faces -Y
    eye_z = max_z - 0.36 * height
    brow_z = max_z - 0.30 * height
    half_gap = max(width * 0.18, 0.01)
    return eye_z, brow_z, half_gap, front_y, cx


# ---------------------------------------------------------------------------
# Public functions: hair grooms (real CURVE splines)
# ---------------------------------------------------------------------------

def create_hair_groom(server, name="HairGroom", head_object=None,
                      strand_count=500, length=0.18, seed=0) -> dict:
    """Create one CURVE groom of tapered strands rooted on the scalp."""
    _ = server
    name = _validate_name(name)
    head_obj = _validate_optional_object(head_object, "head_object")
    strand_count = _validate_int(
        strand_count, "strand_count", minimum=1, maximum=10000)
    length = _validate_float(length, "length", minimum=0.01, maximum=1.0)
    seed = _validate_seed(seed)

    scalp_center, scalp_r, _top, _cx, _cy, _w, _h = _scalp_frame(head_obj)
    rng = random.Random(seed)
    mat = _hair_material(name)
    curve_data, obj = _new_curve_object(name, 0.0015, mat)

    for _ in range(strand_count):
        theta = rng.uniform(0.0, 1.35)  # polar angle from +Z (scalp dome)
        phi = rng.uniform(0.0, 2.0 * math.pi)
        direction = Vector((
            math.sin(theta) * math.cos(phi),
            math.sin(theta) * math.sin(phi),
            math.cos(theta),
        ))
        root = scalp_center + direction * scalp_r
        strand_len = length * rng.uniform(0.75, 1.2)
        # Strands fall down (-Z) and drift back (+Y); front faces -Y.
        fall = Vector((
            direction.x * 0.30 * strand_len
            + rng.uniform(-0.12, 0.12) * strand_len,
            direction.y * 0.30 * strand_len + 0.25 * strand_len,
            -0.85 * strand_len,
        ))
        p0 = root
        p1 = root + fall * 0.35 + Vector((
            rng.uniform(-0.05, 0.05) * strand_len, 0.0,
            rng.uniform(-0.05, 0.05) * strand_len))
        p2 = root + fall * 0.7
        p3 = root + fall
        _add_bezier_strand(
            curve_data, (p0, p1, p2, p3), (1.0, 0.7, 0.4, 0.15))
    bpy.context.view_layer.update()

    report = _curve_report(obj, curve_data)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "type": "CURVE",
        "strand_count": strand_count,
        "spline_count": report["spline_count"],
        "point_count": report["point_count"],
        "length": length,
        "seed": seed,
        "head_object": head_obj.name if head_obj is not None else None,
        "scalp_center": _round3(scalp_center),
        "scalp_radius": round(scalp_r, 6),
        "bounds_min": report["bounds_min"],
        "bounds_max": report["bounds_max"],
        "dimensions": report["dimensions"],
        "bevel_depth": round(float(curve_data.bevel_depth), 6),
        "material": mat.name,
    }


def create_eyebrow_groom(server, name="BrowsPro", head_object=None,
                         strand_count=80, seed=0) -> dict:
    """Create one CURVE groom of short paired L/R eyebrow strands."""
    _ = server
    name = _validate_name(name)
    head_obj = _validate_optional_object(head_object, "head_object")
    strand_count = _validate_int(
        strand_count, "strand_count", minimum=2, maximum=1000)
    seed = _validate_seed(seed)

    eye_z, brow_z, half_gap, front_y, cx = _eye_frame(head_obj)
    rng = random.Random(seed)
    mat = _hair_material(name)
    curve_data, obj = _new_curve_object(name, 0.0008, mat)

    brow_w = 0.04
    arch = 0.006
    left_count = (strand_count + 1) // 2
    right_count = strand_count // 2
    for side, sign, count in (("L", 1.0, left_count),
                              ("R", -1.0, right_count)):
        brow_cx = cx + sign * half_gap
        for i in range(count):
            t = (i / max(count - 1, 1)) * 2.0 - 1.0  # -1..1 across the brow
            root = Vector((
                brow_cx + t * brow_w / 2.0
                + rng.uniform(-0.001, 0.001),
                front_y - 0.002,
                brow_z + arch * (1.0 - t * t)
                + rng.uniform(-0.0008, 0.0008),
            ))
            strand_len = rng.uniform(0.007, 0.012)
            # Brow hairs sweep outward (+/-X) and slightly up/forward.
            tip = root + Vector((
                sign * strand_len * (0.55 + 0.25 * abs(t)),
                -0.35 * strand_len,
                0.30 * strand_len + t * 0.10 * strand_len,
            ))
            mid = (root + tip) * 0.5 + Vector((0.0, -0.0006, 0.0006))
            _add_bezier_strand(
                curve_data, (root, mid, tip), (1.0, 0.6, 0.25))
    bpy.context.view_layer.update()

    report = _curve_report(obj, curve_data)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "type": "CURVE",
        "strand_count": strand_count,
        "spline_count": report["spline_count"],
        "point_count": report["point_count"],
        "sides": ["L", "R"],
        "left_count": left_count,
        "right_count": right_count,
        "seed": seed,
        "head_object": head_obj.name if head_obj is not None else None,
        "eye_height": round(eye_z, 6),
        "brow_height": round(brow_z, 6),
        "bounds_min": report["bounds_min"],
        "bounds_max": report["bounds_max"],
        "dimensions": report["dimensions"],
        "bevel_depth": round(float(curve_data.bevel_depth), 6),
        "material": mat.name,
    }


def create_eyelash_groom(server, name="LashesPro", head_object=None,
                         strand_count=60, radius=0.014, seed=0) -> dict:
    """Create one CURVE groom of paired L/R eyelash strands."""
    _ = server
    name = _validate_name(name)
    head_obj = _validate_optional_object(head_object, "head_object")
    strand_count = _validate_int(
        strand_count, "strand_count", minimum=2, maximum=1000)
    radius = _validate_float(radius, "radius", minimum=0.003, maximum=0.1)
    seed = _validate_seed(seed)

    eye_z, _brow_z, half_gap, front_y, cx = _eye_frame(head_obj)
    rng = random.Random(seed)
    mat = _hair_material(name)
    curve_data, obj = _new_curve_object(name, 0.0005, mat)

    left_count = (strand_count + 1) // 2
    right_count = strand_count // 2
    for side, sign, count in (("L", 1.0, left_count),
                              ("R", -1.0, right_count)):
        eye_cx = cx + sign * half_gap
        for i in range(count):
            frac = i / max(count - 1, 1)
            # Upper-lid arc from outer to inner corner (20..160 degrees).
            angle = math.radians(20.0 + frac * 140.0)
            rim = Vector((
                eye_cx + math.cos(angle) * radius,
                front_y - 0.001,
                eye_z + math.sin(angle) * radius,
            ))
            lash_len = radius * rng.uniform(0.6, 1.0)
            radial = Vector((
                math.cos(angle) * 0.45 * lash_len,
                -0.60 * lash_len,
                (0.55 + math.sin(angle) * 0.35) * lash_len,
            ))
            mid = rim + radial * 0.55 + Vector((0.0, 0.0, radius * 0.10))
            tip = rim + radial
            _add_bezier_strand(curve_data, (rim, mid, tip), (1.0, 0.6, 0.2))
    bpy.context.view_layer.update()

    report = _curve_report(obj, curve_data)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "type": "CURVE",
        "strand_count": strand_count,
        "spline_count": report["spline_count"],
        "point_count": report["point_count"],
        "sides": ["L", "R"],
        "left_count": left_count,
        "right_count": right_count,
        "radius": radius,
        "seed": seed,
        "head_object": head_obj.name if head_obj is not None else None,
        "eye_height": round(eye_z, 6),
        "bounds_min": report["bounds_min"],
        "bounds_max": report["bounds_max"],
        "dimensions": report["dimensions"],
        "bevel_depth": round(float(curve_data.bevel_depth), 6),
        "material": mat.name,
    }


# ---------------------------------------------------------------------------
# Armature helpers
# ---------------------------------------------------------------------------

def _restore_mode(view_layer, target_obj, previous_active, previous_mode):
    try:
        if target_obj is not None:
            view_layer.objects.active = target_obj
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    finally:
        try:
            view_layer.objects.active = previous_active
        except Exception:
            pass
        if previous_active is not None and previous_mode not in (
            None, "OBJECT",
        ):
            try:
                bpy.ops.object.mode_set(mode=previous_mode)
            except Exception:
                pass


def _new_edit_bone(edit_bones, bone_name, head, tail, parent=None,
                   use_connect=False):
    if bone_name in edit_bones:
        raise ValueError(f"Bone '{bone_name}' already exists")
    if Vector(tail) - Vector(head) == Vector((0.0, 0.0, 0.0)):
        raise ValueError(f"Bone '{bone_name}' has zero length (head == tail)")
    bone = edit_bones.new(bone_name)
    bone.head = Vector(head)
    bone.tail = Vector(tail)
    if parent is not None:
        bone.parent = parent
        bone.use_connect = use_connect
    return bone


def _side_split(bone_name):
    for suffix in ("_L", "_R", ".L", ".R"):
        if bone_name.endswith(suffix):
            return bone_name[: -len(suffix)], suffix[-1]
    return bone_name, None


# ---------------------------------------------------------------------------
# Public function: full-body rig
# ---------------------------------------------------------------------------

def create_character_rig_pro(server, mesh_name,
                             armature_name="CharacterRig") -> dict:
    """Create a symmetric full-body armature and skin the mesh to it."""
    _ = server
    mesh_obj = _require_mesh(mesh_name)
    armature_name = _validate_name(armature_name, "armature_name")
    if bpy.data.objects.get(armature_name) is not None:
        raise ValueError(f"Object '{armature_name}' already exists")

    min_x, max_x, min_y, max_y, min_z, max_z = _aabb_world(mesh_obj)
    center = Vector(((min_x + max_x) / 2, (min_y + max_y) / 2, 0.0))
    width = max_x - min_x
    height = max_z - min_z
    if height <= 0.0:
        raise ValueError(f"Mesh '{mesh_obj.name}' has zero height")
    ground = min_z
    hip_x = max(width * 0.18, 0.04 * height)
    sh_x = max(width * 0.30, 0.09 * height)

    pelvis = (0.0, 0.0, ground + 0.52 * height)
    spine_t = (0.0, 0.0, ground + 0.62 * height)
    chest_t = (0.0, 0.0, ground + 0.72 * height)
    neck_t = (0.0, 0.0, ground + 0.80 * height)
    head_t = (0.0, 0.0, ground + 0.86 * height)
    skull_t = (0.0, 0.0, ground + 0.97 * height)

    finger_names = ("thumb", "index", "middle", "ring", "pinky")
    finger_x = (0.030, 0.016, 0.005, -0.006, -0.017)

    specs = [
        ("pelvis", pelvis, spine_t, None, False),
        ("spine", spine_t, chest_t, "pelvis", True),
        ("chest", chest_t, neck_t, "spine", True),
        ("neck", neck_t, head_t, "chest", True),
        ("head", head_t, skull_t, "neck", True),
    ]
    for side, sign in (("L", 1.0), ("R", -1.0)):
        clav_h = (sign * 0.012 * height, 0.0, ground + 0.785 * height)
        clav_t = (sign * sh_x, 0.0, ground + 0.795 * height)
        elbow = (sign * (sh_x + 0.015 * height), 0.0, ground + 0.63 * height)
        wrist = (sign * (sh_x + 0.025 * height), -0.01 * height,
                 ground + 0.50 * height)
        hand_t = (sign * (sh_x + 0.025 * height), -0.03 * height,
                  ground + 0.44 * height)
        specs.append((f"clavicle_{side}", clav_h, clav_t, "chest", False))
        specs.append((f"upper_arm_{side}", clav_t, elbow,
                      f"clavicle_{side}", True))
        specs.append((f"forearm_{side}", elbow, wrist,
                      f"upper_arm_{side}", True))
        specs.append((f"hand_{side}", wrist, hand_t,
                      f"forearm_{side}", True))
        for finger, fx in zip(finger_names, finger_x):
            segs = 2 if finger == "thumb" else 2
            base = Vector((sign * (sh_x + 0.025 * height + fx * height),
                           -0.03 * height, ground + 0.44 * height))
            direction = Vector((sign * 0.25, -0.25, -1.0)).normalized()
            if finger == "thumb":
                direction = Vector((sign * 0.75, -0.55, -0.25)).normalized()
            parent = f"hand_{side}"
            tip = base
            for index in range(segs):
                seg_len = (0.030 - 0.005 * index) * height
                head_p = tip
                tip = head_p + direction * seg_len
                bone_name = f"{finger}_{index + 1:02d}_{side}"
                specs.append((bone_name, tuple(head_p), tuple(tip),
                              parent, index > 0))
                parent = bone_name
        thigh_h = (sign * hip_x, 0.0, ground + 0.50 * height)
        knee = (sign * hip_x, 0.008 * height, ground + 0.28 * height)
        ankle = (sign * hip_x, 0.0, ground + 0.06 * height)
        toe = (sign * hip_x, -0.10 * height, ground + 0.02 * height)
        specs.append((f"thigh_{side}", thigh_h, knee, "pelvis", False))
        specs.append((f"shin_{side}", knee, ankle, f"thigh_{side}", True))
        specs.append((f"foot_{side}", ankle, toe, f"shin_{side}", True))

    for bone_name, head_p, tail_p, _parent, _conn in specs:
        if Vector(tail_p) - Vector(head_p) == Vector((0.0, 0.0, 0.0)):
            raise ValueError(
                f"Bone '{bone_name}' has zero length (head == tail)")

    arm_data = bpy.data.armatures.new(armature_name + "_Data")
    arm_obj = bpy.data.objects.new(armature_name, arm_data)
    _link(arm_obj)
    arm_obj.location = center

    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    try:
        previous_mode = previous_active.mode
    except Exception:
        previous_mode = "OBJECT"
    try:
        view_layer.objects.active = arm_obj
        arm_obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            edit_map = {}
            for bone_name, head_p, tail_p, parent, conn in specs:
                parent_bone = edit_map.get(parent) if parent else None
                edit_map[bone_name] = _new_edit_bone(
                    arm_obj.data.edit_bones, bone_name, head_p, tail_p,
                    parent=parent_bone, use_connect=conn,
                )
        finally:
            _restore_mode(view_layer, arm_obj, previous_active,
                          previous_mode)
    except ValueError:
        raise
    except RuntimeError as exc:
        raise ValueError(
            f"Could not edit armature '{arm_obj.name}': {exc}")
    view_layer.update()

    # Parent the mesh with automatic weights.
    previous_selection = list(bpy.context.selected_objects)
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    try:
        bpy.ops.object.select_all(action="DESELECT")
        mesh_obj.select_set(True)
        arm_obj.select_set(True)
        view_layer.objects.active = arm_obj
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except RuntimeError as exc:
        raise ValueError(
            f"Could not parent '{mesh_obj.name}' to "
            f"'{arm_obj.name}' with automatic weights: {exc}"
        )
    finally:
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        for item in previous_selection:
            try:
                item.select_set(True)
            except Exception:
                continue
        _restore_mode(view_layer, arm_obj, previous_active, previous_mode)
    view_layer.update()

    bones = sorted(bone.name for bone in arm_obj.data.bones)
    groups = sorted(group.name for group in mesh_obj.vertex_groups)

    # Symmetry check across X == 0.
    stems = {}
    for bone in arm_obj.data.bones:
        stem, side = _side_split(bone.name)
        if side is not None:
            stems.setdefault(stem, {})[side] = bone
    asymmetric = sorted(
        stem for stem, pair in stems.items() if set(pair) != {"L", "R"})
    unmirrored = []
    for stem, pair in sorted(stems.items()):
        if set(pair) != {"L", "R"}:
            continue
        left, right = pair["L"], pair["R"]
        ok = True
        for left_pt, right_pt in ((left.head_local, right.head_local),
                                  (left.tail_local, right.tail_local)):
            if (abs(left_pt.x + right_pt.x) > _MIRROR_TOLERANCE
                    or abs(left_pt.y - right_pt.y) > _MIRROR_TOLERANCE
                    or abs(left_pt.z - right_pt.z) > _MIRROR_TOLERANCE):
                ok = False
                break
        if not ok:
            unmirrored.append(stem)

    present = set(bones)
    required = {item[0] for item in specs}
    missing = sorted(required - present)
    facial = sorted(
        bone for bone in bones
        if _side_split(bone)[0] in _FACIAL_BONE_STEMS)
    has_facial = len(facial) > 0
    validation = {
        "required_bones_present": len(missing) == 0,
        "missing_bones": missing,
        "symmetric": not asymmetric and not unmirrored,
        "asymmetric_bones": asymmetric,
        "unmirrored_pairs": sorted(unmirrored),
        "vertex_groups_created": len(groups) > 0,
        "has_facial_rig": has_facial,
    }

    return {
        "success": True,
        "armature": arm_obj.name,
        "mesh": mesh_obj.name,
        "method": "ARMATURE_AUTO",
        "bone_count": len(bones),
        "bones": bones,
        "vertex_groups": groups,
        "vertex_group_count": len(groups),
        "symmetric": validation["symmetric"],
        "has_facial_rig": has_facial,
        "facial_bones": facial,
        "validation": validation,
        "height": round(height, 6),
        "ground": round(ground, 6),
    }


# ---------------------------------------------------------------------------
# Public function: character studio
# ---------------------------------------------------------------------------

def create_character_studio(server, name="CharacterStudio",
                            target=(0.0, 0.0, 1.0)) -> dict:
    """Create a grounded studio: backdrop, 3-point lights, camera, world."""
    _ = server
    name = _validate_name(name)
    tgt = _validate_vector3(target, "target")
    target_v = Vector(tgt)

    created = []

    def _unique(base):
        candidate = base
        index = 1
        while bpy.data.objects.get(candidate) is not None:
            index += 1
            candidate = f"{base}_{index:02d}"
        return candidate

    # Grounded backdrop plane (lowest point touches Z == 0).
    backdrop_name = _unique(name + "_Backdrop")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=6.0)
    mesh = bpy.data.meshes.new(backdrop_name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    backdrop = bpy.data.objects.new(backdrop_name, mesh)
    backdrop.location = Vector((target_v.x, target_v.y, 0.0))
    back_mat = _get_or_create_material(
        backdrop_name + "_Mat", (0.5, 0.5, 0.5, 1.0), 0.9)
    mesh.materials.append(back_mat)
    _link(backdrop)
    created.append(backdrop.name)

    # Three-point AREA lighting aimed at the target.
    light_specs = [
        ("Key", (2.5, -3.0, 3.0), 500.0, 1.0),
        ("Fill", (-2.5, -2.0, 2.0), 200.0, 1.5),
        ("Rim", (0.0, 2.5, 2.5), 300.0, 0.8),
    ]
    lights = {}
    for label, offset, energy, size in light_specs:
        light_name = _unique(f"{name}_{label}")
        light_data = bpy.data.lights.new(
            name=light_name + "_Data", type="AREA")
        light_data.energy = float(energy)
        light_data.color = (1.0, 1.0, 1.0)
        try:
            light_data.size = float(size)
        except (AttributeError, TypeError):
            pass
        light_obj = bpy.data.objects.new(name=light_name,
                                         object_data=light_data)
        light_obj.location = target_v + Vector(offset)
        aim = target_v - light_obj.location
        if aim.length > 1e-9:
            light_obj.rotation_euler = aim.to_track_quat(
                "-Z", "Y").to_euler()
        _link(light_obj)
        created.append(light_obj.name)
        lights[label.lower()] = light_obj.name

    # Camera aimed at the target (front is -Y, so it sits at -Y).
    cam_name = _unique(name + "_Camera")
    cam_data = bpy.data.cameras.new(name=cam_name + "_Data")
    cam_data.lens = 50.0
    cam_obj = bpy.data.objects.new(name=cam_name, object_data=cam_data)
    cam_obj.location = target_v + Vector((0.7, -2.4, 0.5))
    aim = target_v - cam_obj.location
    cam_obj.rotation_euler = aim.to_track_quat("-Z", "Y").to_euler()
    _link(cam_obj)
    created.append(cam_obj.name)

    # Neutral world background.
    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new(name="World")
        scene.world = world
    world.use_nodes = True
    tree = world.node_tree
    background = next(
        (n for n in tree.nodes if n.type == "BACKGROUND"), None)
    if background is None:
        background = tree.nodes.new(type="ShaderNodeBackground")
    output = next(
        (n for n in tree.nodes if n.type == "OUTPUT_WORLD"), None)
    if output is None:
        output = tree.nodes.new(type="ShaderNodeOutputWorld")
    if "Color" in background.inputs:
        background.inputs["Color"].default_value = (0.18, 0.18, 0.18, 1.0)
    if "Strength" in background.inputs:
        background.inputs["Strength"].default_value = 1.0
    try:
        if ("Background" in background.outputs
                and "Surface" in output.inputs):
            linked = any(
                link.from_node == background and link.to_node == output
                for link in tree.links
            )
            if not linked:
                tree.links.new(background.outputs["Background"],
                               output.inputs["Surface"])
    except (AttributeError, RuntimeError):
        pass

    bpy.context.view_layer.update()
    return {
        "success": True,
        "studio": name,
        "backdrop": backdrop.name,
        "grounded": True,
        "lights": lights,
        "key": lights["key"],
        "fill": lights["fill"],
        "rim": lights["rim"],
        "camera": cam_obj.name,
        "world": world.name,
        "target": [round(float(v), 6) for v in target_v],
        "created": created,
    }


# ---------------------------------------------------------------------------
# Public function: quality report (read-only)
# ---------------------------------------------------------------------------

def character_quality_report(server, mesh_name, armature_name=None,
                             hair_objects=None) -> dict:
    """Inspect a character base and report structural quality (read-only)."""
    _ = server
    mesh_obj = _require_mesh(mesh_name)

    arm_obj = None
    if armature_name is not None:
        clean = _validate_name(armature_name, "armature_name")
        arm_obj = bpy.data.objects.get(clean)
        if arm_obj is None:
            raise ValueError(f"Armature '{clean}' not found")
        if arm_obj.type != "ARMATURE":
            raise ValueError(
                f"Object '{clean}' is not an armature (got {arm_obj.type})"
            )
    hair_objs = _validate_hair_objects(hair_objects)

    mesh_data = mesh_obj.data
    evaluated = mesh_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated.to_mesh()
    polygon_count = len(evaluated_mesh.polygons)

    # Non-manifold edge count via a throwaway bmesh (mesh is not modified).
    bm = bmesh.new()
    try:
        bm.from_mesh(evaluated_mesh)
        bm.edges.ensure_lookup_table()
        non_manifold = sum(
            1 for edge in bm.edges if not edge.is_manifold)
    finally:
        bm.free()
        evaluated.to_mesh_clear()

    materials = [s.name for s in mesh_data.materials if s is not None]
    uv_layers = [uv.name for uv in mesh_data.uv_layers]
    shape_keys = []
    try:
        if mesh_data.shape_keys is not None:
            shape_keys = sorted(
                block.name
                for block in mesh_data.shape_keys.key_blocks)
    except (AttributeError, ReferenceError):
        shape_keys = []
    vertex_groups = sorted(group.name for group in mesh_obj.vertex_groups)

    bones = []
    if arm_obj is not None:
        bones = sorted(bone.name for bone in arm_obj.data.bones)

    hair_details = []
    total_splines = 0
    total_points = 0
    for hair_obj in hair_objs:
        if hair_obj.type == "CURVE" and hair_obj.data is not None:
            splines = len(hair_obj.data.splines)
            points = 0
            for spline in hair_obj.data.splines:
                if spline.type == "BEZIER":
                    points += len(spline.bezier_points)
                else:
                    points += len(spline.points)
        else:
            splines = 0
            points = 0
        total_splines += splines
        total_points += points
        hair_details.append({
            "object": hair_obj.name,
            "type": hair_obj.type,
            "spline_count": splines,
            "point_count": points,
        })

    # Image textures referenced by the mesh materials.
    images = set()
    for mat in mesh_data.materials:
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        try:
            nodes = mat.node_tree.nodes
        except (AttributeError, ReferenceError):
            continue
        for node in nodes:
            try:
                if node.type == "TEX_IMAGE" and node.image is not None:
                    images.add(node.image.name)
            except (AttributeError, ReferenceError):
                continue
    image_textures = sorted(images)

    checks = [
        {
            "check": "has_geometry",
            "passed": polygon_count > 0,
            "message": (
                "mesh has polygons" if polygon_count > 0
                else f"mesh '{mesh_obj.name}' has no polygons"
            ),
        },
        {
            "check": "manifold",
            "passed": non_manifold == 0,
            "message": (
                "no non-manifold edges" if non_manifold == 0
                else f"{non_manifold} non-manifold edge(s) found"
            ),
        },
        {
            "check": "has_material",
            "passed": len(materials) > 0,
            "message": (
                "mesh has materials" if materials
                else f"mesh '{mesh_obj.name}' has no materials"
            ),
        },
        {
            "check": "has_uv",
            "passed": len(uv_layers) > 0,
            "message": (
                "mesh has UV layers" if uv_layers
                else f"mesh '{mesh_obj.name}' has no UV layers"
            ),
        },
    ]
    if arm_obj is not None:
        linked = any(mod.type == "ARMATURE" and mod.object == arm_obj and mod.show_viewport
                     for mod in mesh_obj.modifiers)
        group_ids = {group.index for group in mesh_obj.vertex_groups
                     if arm_obj.data.bones.get(group.name) and arm_obj.data.bones[group.name].use_deform}
        weighted = sum(any(group.group in group_ids and group.weight > 0
                           for group in vertex.groups) for vertex in mesh_data.vertices)
        bound = linked and weighted == len(mesh_data.vertices) and weighted > 0
        checks.append({
            "check": "armature_bound",
            "passed": bound,
            "message": (
                "all vertices have weights for the linked armature" if bound
                else f"armature binding incomplete (modifier_linked={linked}, "
                     f"weighted_vertices={weighted}/{len(mesh_data.vertices)})"
            ),
        })
    if hair_objs:
        groom_ok = total_splines > 0
        checks.append({
            "check": "groom_present",
            "passed": groom_ok,
            "message": (
                f"groom has {total_splines} spline(s)" if groom_ok
                else "hair objects contain no curve splines"
            ),
        })

    failures = [c for c in checks if not c["passed"]]
    passed = len(failures) == 0
    if passed:
        reasons = ["all structural checks passed"]
    else:
        reasons = [item["message"] for item in failures]

    return {
        "success": True,
        "mesh": mesh_obj.name,
        "armature": arm_obj.name if arm_obj is not None else None,
        "tier": _PROCEDURAL_TIER,
        "aaa_certified": False,
        "production_ready": passed,
        "production_ready_scope": "structural_base_only",
        "reasons": reasons,
        "missing_for_aaa": list(_MISSING_FOR_AAA),
        "passed": passed,
        "checks": checks,
        "polygon_count": polygon_count,
        "non_manifold_edges": non_manifold,
        "material_count": len(materials),
        "materials": materials,
        "uv_layer_count": len(uv_layers),
        "uv_layers": uv_layers,
        "shape_key_count": len(shape_keys),
        "shape_keys": shape_keys,
        "bone_count": len(bones),
        "bones": bones,
        "vertex_group_count": len(vertex_groups),
        "vertex_groups": vertex_groups,
        "hair_spline_count": total_splines,
        "hair_point_count": total_points,
        "hair_details": hair_details,
        "image_texture_count": len(image_textures),
        "image_textures": image_textures,
    }


__all__ = [
    "create_hair_groom",
    "create_eyebrow_groom",
    "create_eyelash_groom",
    "create_character_rig_pro",
    "create_character_studio",
    "character_quality_report",
]
