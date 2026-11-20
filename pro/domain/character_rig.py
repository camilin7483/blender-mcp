"""Character rigging domain pack: face rigs, fingers, IK limbs, shape keys.

Real ``bpy`` / ``mathutils`` rigging on Blender's main thread. All functions
validate their inputs, raise ``ValueError`` with a precise message on bad
input and return plain JSON-serializable dictionaries.

Conventions: meters for distances, front of the character faces ``-Y``,
bilateral symmetry across ``X == 0`` (``_L`` bones mirror ``_R`` bones).
Blender 4.5 LTS and 5.2 LTS compatible.
"""

import math

import bpy
from mathutils import Vector

_DEFAULT_SHAPE_KEYS = (
    "brow_raise",
    "eye_blink_L",
    "eye_blink_R",
    "jaw_open",
    "smile",
)

_VALID_SIDES = ("L", "R")
_MIRROR_TOLERANCE = 1e-4


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_float(value, label, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number (got {value!r})")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number (got {value!r})")
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite (got {value!r})")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {number})")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {number})")
    return number


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


def _validate_side(value):
    if not isinstance(value, str):
        raise ValueError(
            f"side must be one of {list(_VALID_SIDES)} (got {value!r})"
        )
    side = value.strip().upper()
    if side not in _VALID_SIDES:
        raise ValueError(
            f"side must be one of {list(_VALID_SIDES)} (got {value!r})"
        )
    return side


def _get_armature(armature_name):
    name = _validate_name(armature_name, "armature_name")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Armature '{name}' not found")
    if obj.type != "ARMATURE":
        raise ValueError(
            f"Object '{name}' is not an armature (got {obj.type})"
        )
    if obj.data is None:
        raise ValueError(f"Armature '{name}' has no armature data")
    return obj


def _get_mesh(mesh_name):
    name = _validate_name(mesh_name, "mesh_name")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Mesh '{name}' not found")
    if obj.type != "MESH":
        raise ValueError(f"Object '{name}' is not a mesh (got {obj.type})")
    if obj.data is None:
        raise ValueError(f"Mesh '{name}' has no mesh data")
    return obj


def _get_target(target_name):
    name = _validate_name(target_name, "target_name")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Target object '{name}' not found")
    return obj


def _round3(values):
    return [round(float(value), 6) for value in values]


def _restore_mode(view_layer, target_obj, previous_active, previous_mode):
    """Return to OBJECT, then restore the previous active object and mode."""
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


def _run_in_edit_mode(arm_obj, build):
    """Run *build(edit_bones)* in Edit Mode with selection/mode restore."""
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
            result = build(arm_obj.data.edit_bones)
        finally:
            _restore_mode(view_layer, arm_obj, previous_active,
                           previous_mode)
    except ValueError:
        raise
    except RuntimeError as exc:
        raise ValueError(f"Could not edit armature '{arm_obj.name}': {exc}")
    view_layer.update()
    return result


def _new_edit_bone(edit_bones, name, head, tail, parent=None,
                   use_connect=False):
    if name in edit_bones:
        raise ValueError(f"Bone '{name}' already exists")
    if Vector(tail) - Vector(head) == Vector((0.0, 0.0, 0.0)):
        raise ValueError(f"Bone '{name}' has zero length (head == tail)")
    bone = edit_bones.new(name)
    bone.head = Vector(head)
    bone.tail = Vector(tail)
    if parent is not None:
        bone.parent = parent
        bone.use_connect = use_connect
    return bone


def _mesh_aabb_world(mesh_obj):
    corners = [mesh_obj.matrix_world @ Vector(corner)
               for corner in mesh_obj.bound_box]
    xs = [corner.x for corner in corners]
    ys = [corner.y for corner in corners]
    zs = [corner.z for corner in corners]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _check_segment(head, tail, label):
    if Vector(tail) - Vector(head) == Vector((0.0, 0.0, 0.0)):
        raise ValueError(f"{label} head and tail must differ (zero-length)")


def _validate_shape_names(names):
    if names is None:
        return list(_DEFAULT_SHAPE_KEYS)
    try:
        items = list(names)
    except TypeError:
        raise ValueError(
            f"names must be a sequence of non-empty strings "
            f"(got {names!r})"
        )
    if not items:
        raise ValueError("names must contain at least one shape key name")
    cleaned = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"names must be a sequence of non-empty strings "
                f"(got {names!r})"
            )
        cleaned.append(item.strip())
    if len(set(cleaned)) != len(cleaned):
        raise ValueError(f"names must not contain duplicates (got {names!r})")
    return cleaned


def _side_split(bone_name):
    for suffix in ("_L", "_R", ".L", ".R"):
        if bone_name.endswith(suffix):
            return bone_name[: -len(suffix)], suffix[-1]
    return bone_name, None


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def create_face_rig(server, mesh_name, armature_name="FaceRig") -> dict:
    """Create a compact face rig armature fitted to a head mesh AABB."""
    del server
    mesh_obj = _get_mesh(mesh_name)
    armature_name = _validate_name(armature_name, "armature_name")
    if bpy.data.objects.get(armature_name) is not None:
        raise ValueError(f"Object '{armature_name}' already exists")

    min_x, max_x, _min_y, max_y, min_z, max_z = _mesh_aabb_world(mesh_obj)
    cx = (min_x + max_x) / 2.0
    cy = (_min_y + max_y) / 2.0
    front_y = _min_y  # front of the character faces -Y
    height = max_z - min_z
    if height <= 0.0:
        raise ValueError(f"Mesh '{mesh_obj.name}' has zero height")
    top = max_z
    bottom = min_z
    eye_z = top - 0.36 * height
    brow_z = top - 0.30 * height
    mouth_z = top - 0.70 * height
    chin_z = top - 0.92 * height
    half_gap = max((max_x - min_x) * 0.18, 0.01)
    lid_y = front_y - 0.003
    lid_half = 0.012

    specs = [
        ("head", (cx, cy, bottom), (cx, cy, top), None),
        ("jaw", (cx, front_y - 0.002, mouth_z),
         (cx, front_y + 0.008, chin_z), "head"),
    ]
    for side, sign in (("L", 1.0), ("R", -1.0)):
        ex = cx + sign * half_gap
        specs.append((f"eye_{side}", (ex, lid_y, eye_z),
                      (ex, lid_y, eye_z + 0.012), "head"))
        specs.append((f"brow_{side}", (ex - sign * 0.015, lid_y, brow_z),
                      (ex + sign * 0.015, lid_y, brow_z), "head"))
        specs.append((f"eyelid_upper_{side}",
                      (ex - sign * lid_half, lid_y, eye_z + 0.007),
                      (ex + sign * lid_half, lid_y, eye_z + 0.007), "head"))
        specs.append((f"eyelid_lower_{side}",
                      (ex - sign * lid_half, lid_y, eye_z - 0.007),
                      (ex + sign * lid_half, lid_y, eye_z - 0.007), "head"))

    for name, head, tail, _parent in specs:
        _check_segment(head, tail, f"Bone '{name}'")

    arm_data = bpy.data.armatures.new(armature_name + "_Data")
    arm_obj = bpy.data.objects.new(armature_name, arm_data)
    _link(arm_obj)

    def _build(edit_bones):
        edit_map = {}
        for name, head, tail, parent in specs:
            parent_bone = edit_map.get(parent) if parent else None
            edit_map[name] = _new_edit_bone(
                edit_bones, name, head, tail,
                parent=parent_bone, use_connect=False,
            )
        return [
            {
                "name": name,
                "parent": edit_map[name].parent.name
                if edit_map[name].parent else None,
                "head": _round3(edit_map[name].head),
                "tail": _round3(edit_map[name].tail),
            }
            for name, _head, _tail, _parent in specs
        ]

    bones = _run_in_edit_mode(arm_obj, _build)

    return {
        "success": True,
        "armature": arm_obj.name,
        "mesh": mesh_obj.name,
        "bone_count": len(bones),
        "bones": bones,
        "top": round(top, 6),
        "bottom": round(bottom, 6),
        "eye_spacing": round(half_gap * 2.0, 6),
    }


def create_jaw_bone(server, armature_name, head, tail) -> dict:
    """Add a jaw bone with the given head/tail to an existing armature."""
    del server
    arm_obj = _get_armature(armature_name)
    head = _validate_vector3(head, "head")
    tail = _validate_vector3(tail, "tail")
    _check_segment(head, tail, "Jaw bone")
    if "jaw" in arm_obj.data.bones:
        raise ValueError(
            f"Bone 'jaw' already exists in armature '{arm_obj.name}'"
        )

    def _build(edit_bones):
        bone = _new_edit_bone(edit_bones, "jaw", head, tail)
        return {
            "head": _round3(bone.head),
            "tail": _round3(bone.tail),
        }

    result = _run_in_edit_mode(arm_obj, _build)

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": "jaw",
        "head": result["head"],
        "tail": result["tail"],
    }


def create_eyelid_bones(server, armature_name, eye_spacing=0.065,
                        head_height=0.22) -> dict:
    """Add paired upper/lower eyelid bones for both eyes to an armature."""
    del server
    arm_obj = _get_armature(armature_name)
    eye_spacing = _validate_float(eye_spacing, "eye_spacing",
                                  minimum=0.01, maximum=0.5)
    head_height = _validate_float(head_height, "head_height",
                                  minimum=0.05, maximum=1.0)

    half = eye_spacing / 2.0
    lid_y = -head_height * 0.1
    lid_z = head_height
    lid_half = 0.012
    specs = []
    for side, sign in (("L", 1.0), ("R", -1.0)):
        ex = sign * half
        specs.append((f"eyelid_upper_{side}",
                      (ex - sign * lid_half, lid_y, lid_z + 0.006),
                      (ex + sign * lid_half, lid_y, lid_z + 0.006)))
        specs.append((f"eyelid_lower_{side}",
                      (ex - sign * lid_half, lid_y, lid_z - 0.006),
                      (ex + sign * lid_half, lid_y, lid_z - 0.006)))
    for name, _head, _tail in specs:
        if name in arm_obj.data.bones:
            raise ValueError(
                f"Bone '{name}' already exists "
                f"in armature '{arm_obj.name}'"
            )

    def _build(edit_bones):
        made = []
        for name, head, tail in specs:
            bone = _new_edit_bone(edit_bones, name, head, tail)
            made.append({
                "name": bone.name,
                "head": _round3(bone.head),
                "tail": _round3(bone.tail),
            })
        return made

    bones = _run_in_edit_mode(arm_obj, _build)

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone_count": len(bones),
        "bones": bones,
        "eye_spacing": eye_spacing,
        "head_height": head_height,
    }


def create_finger_rig(server, armature_name, side="L",
                      scale=1.0) -> dict:
    """Add 5 finger chains (thumb + 4 fingers) for one hand side."""
    del server
    arm_obj = _get_armature(armature_name)
    side = _validate_side(side)
    scale = _validate_float(scale, "scale", minimum=0.1, maximum=5.0)
    mirror = 1.0 if side == "L" else -1.0

    root_name = f"hand_{side}"
    chains = [
        ("thumb", 2, mirror * 0.055 * scale, 0.030 * scale),
        ("index", 3, mirror * 0.032 * scale, 0.028 * scale),
        ("middle", 3, mirror * 0.011 * scale, 0.028 * scale),
        ("ring", 3, mirror * -0.011 * scale, 0.026 * scale),
        ("pinky", 3, mirror * -0.032 * scale, 0.022 * scale),
    ]
    planned = [root_name]
    for finger, count, _base_x, _seg in chains:
        for index in range(count):
            planned.append(f"{finger}_{index + 1:02d}_{side}")
    existing = [name for name in planned if name in arm_obj.data.bones]
    if existing:
        raise ValueError(
            f"Bone(s) {sorted(existing)} already exist "
            f"in armature '{arm_obj.name}'"
        )

    base_y = -0.045 * scale

    def _build(edit_bones):
        made = []
        root = _new_edit_bone(
            edit_bones, root_name,
            (0.0, 0.03 * scale, 0.0), (0.0, -0.04 * scale, 0.0),
        )
        made.append(root)
        for finger, count, base_x, seg in chains:
            if finger == "thumb":
                direction = Vector(
                    (mirror * 0.75, -0.55, -0.1)).normalized()
            else:
                direction = Vector((0.0, -1.0, 0.0))
            tip = Vector((base_x, base_y, 0.0))
            parent = root
            for index in range(count):
                head = tip
                # Distal segments are slightly shorter for a natural taper.
                length = seg * (1.0 - 0.12 * index)
                tip = head + direction * length
                bone = _new_edit_bone(
                    edit_bones, f"{finger}_{index + 1:02d}_{side}",
                    head, tip, parent=parent, use_connect=False,
                )
                made.append(bone)
                parent = bone
        return [
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "head": _round3(bone.head),
                "tail": _round3(bone.tail),
            }
            for bone in made
        ]

    bones = _run_in_edit_mode(arm_obj, _build)

    return {
        "success": True,
        "armature": arm_obj.name,
        "side": side,
        "scale": scale,
        "root": root_name,
        "bone_count": len(bones),
        "bones": bones,
        "chains": [
            {"finger": finger, "bones": count} for finger, count, _x, _s
            in chains
        ],
    }


def _create_limb_ik(arm_obj, specs, end_bone, target_name, chain_count):
    target_obj = _get_target(target_name)
    for name, head, tail in specs:
        if name in arm_obj.data.bones:
            raise ValueError(
                f"Bone '{name}' already exists "
                f"in armature '{arm_obj.name}'"
            )

    def _build(edit_bones):
        edit_map = {}
        previous = None
        for name, head, tail in specs:
            edit_map[name] = _new_edit_bone(
                edit_bones, name, head, tail,
                parent=previous,
                use_connect=previous is not None,
            )
            previous = edit_map[name]
        return [
            {
                "name": name,
                "parent": edit_map[name].parent.name
                if edit_map[name].parent else None,
                "head": _round3(edit_map[name].head),
                "tail": _round3(edit_map[name].tail),
            }
            for name, _head, _tail in specs
        ]

    bones = _run_in_edit_mode(arm_obj, _build)

    pose_bone = arm_obj.pose.bones.get(end_bone)
    if pose_bone is None:
        raise ValueError(
            f"Bone '{end_bone}' not found in armature '{arm_obj.name}'"
        )
    constraint = pose_bone.constraints.new(type="IK")
    constraint.target = target_obj
    constraint.chain_count = chain_count
    bpy.context.view_layer.update()

    return bones, constraint, target_obj


def create_ik_leg_rig(server, armature_name, hip, knee, ankle,
                      target_name) -> dict:
    """Create a thigh/shin chain with a 2-bone IK constraint on the shin."""
    del server
    arm_obj = _get_armature(armature_name)
    hip = _validate_vector3(hip, "hip")
    knee = _validate_vector3(knee, "knee")
    ankle = _validate_vector3(ankle, "ankle")
    _check_segment(hip, knee, "Thigh (hip/knee)")
    _check_segment(knee, ankle, "Shin (knee/ankle)")
    _validate_name(target_name, "target_name")

    bones, constraint, target_obj = _create_limb_ik(
        arm_obj, [("thigh", hip, knee), ("shin", knee, ankle)],
        "shin", target_name, 2,
    )

    return {
        "success": True,
        "armature": arm_obj.name,
        "bones": [item["name"] for item in bones],
        "bone_details": bones,
        "constraint": constraint.name,
        "constraint_type": constraint.type,
        "constrained_bone": "shin",
        "target": target_obj.name,
        "chain_count": int(constraint.chain_count),
    }


def create_ik_arm_rig(server, armature_name, shoulder, elbow, wrist,
                      target_name) -> dict:
    """Create an upperarm/forearm chain with a 2-bone IK constraint."""
    del server
    arm_obj = _get_armature(armature_name)
    shoulder = _validate_vector3(shoulder, "shoulder")
    elbow = _validate_vector3(elbow, "elbow")
    wrist = _validate_vector3(wrist, "wrist")
    _check_segment(shoulder, elbow, "Upperarm (shoulder/elbow)")
    _check_segment(elbow, wrist, "Forearm (elbow/wrist)")
    _validate_name(target_name, "target_name")

    bones, constraint, target_obj = _create_limb_ik(
        arm_obj, [("upperarm", shoulder, elbow),
                  ("forearm", elbow, wrist)],
        "forearm", target_name, 2,
    )

    return {
        "success": True,
        "armature": arm_obj.name,
        "bones": [item["name"] for item in bones],
        "bone_details": bones,
        "constraint": constraint.name,
        "constraint_type": constraint.type,
        "constrained_bone": "forearm",
        "target": target_obj.name,
        "chain_count": int(constraint.chain_count),
    }


def add_face_shape_keys(server, mesh_name, names=None) -> dict:
    """Create facial expression shape keys (plus Basis) on a mesh."""
    del server
    mesh_obj = _get_mesh(mesh_name)
    wanted = _validate_shape_names(names)

    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    try:
        previous_mode = previous_active.mode
    except Exception:
        previous_mode = "OBJECT"
    try:
        view_layer.objects.active = mesh_obj
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        existing_blocks = []
        if mesh_obj.data.shape_keys is not None:
            existing_blocks = [
                block.name for block in mesh_obj.data.shape_keys.key_blocks
            ]
        created = []
        skipped = []
        for name in wanted:
            if name in existing_blocks or (
                mesh_obj.data.shape_keys is not None
                and name in mesh_obj.data.shape_keys.key_blocks
            ):
                skipped.append(name)
                continue
            try:
                mesh_obj.shape_key_add(name=name, from_mix=False)
            except RuntimeError as exc:
                raise ValueError(
                    f"Could not add shape key '{name}' "
                    f"to mesh '{mesh_obj.name}': {exc}"
                )
            created.append(name)
        if mesh_obj.data.shape_keys is None:
            raise ValueError(
                f"Mesh '{mesh_obj.name}' has no shape keys after creation"
            )
        key_names = sorted(
            block.name for block in mesh_obj.data.shape_keys.key_blocks
        )
    finally:
        _restore_mode(view_layer, mesh_obj, previous_active, previous_mode)
    view_layer.update()

    return {
        "success": True,
        "mesh": mesh_obj.name,
        "created": created,
        "existing": skipped,
        "shape_keys": key_names,
        "shape_key_count": len(key_names),
    }


def validate_character_rig(server, armature_name, mesh_name=None) -> dict:
    """Validate bones, L/R symmetry, constraints and mesh shape keys."""
    del server
    arm_obj = _get_armature(armature_name)
    mesh_obj = None
    if mesh_name is not None:
        mesh_obj = _get_mesh(mesh_name)

    failures = []
    bones = list(arm_obj.data.bones)
    bone_count = len(bones)
    if bone_count == 0:
        failures.append({
            "check": "bones",
            "message": f"Armature '{arm_obj.name}' has no bones",
        })

    # Left/right symmetry: every sided bone needs its counterpart, and
    # each pair must mirror across X == 0 within tolerance.
    stems = {}
    for bone in bones:
        stem, side = _side_split(bone.name)
        if side is not None:
            stems.setdefault(stem, {})[side] = bone
    asymmetric = sorted(
        stem for stem, pair in stems.items() if set(pair) != {"L", "R"}
    )
    if asymmetric:
        failures.append({
            "check": "left_right_symmetry",
            "message": (
                f"{len(asymmetric)} bone stem(s) lack an L/R counterpart"
            ),
            "bones": asymmetric,
        })
    mirrored = []
    for stem, pair in sorted(stems.items()):
        if set(pair) != {"L", "R"}:
            continue
        left, right = pair["L"], pair["R"]
        points = [
            ("head", left.head_local, right.head_local),
            ("tail", left.tail_local, right.tail_local),
        ]
        ok = True
        for _label, left_pt, right_pt in points:
            if (abs(left_pt.x + right_pt.x) > _MIRROR_TOLERANCE
                    or abs(left_pt.y - right_pt.y) > _MIRROR_TOLERANCE
                    or abs(left_pt.z - right_pt.z) > _MIRROR_TOLERANCE):
                ok = False
                break
        if not ok:
            mirrored.append(stem)
    if mirrored:
        failures.append({
            "check": "mirror_positions",
            "message": (
                f"{len(mirrored)} L/R bone pair(s) are not mirrored "
                f"across X == 0"
            ),
            "bones": sorted(mirrored),
        })

    constraints = []
    try:
        for pose_bone in arm_obj.pose.bones:
            for constraint in pose_bone.constraints:
                constraints.append({
                    "bone": pose_bone.name,
                    "constraint": constraint.name,
                    "type": constraint.type,
                })
    except Exception:
        constraints = []
    constraints.sort(key=lambda item: (item["bone"], item["constraint"]))

    shape_keys = None
    if mesh_obj is not None:
        try:
            blocks = mesh_obj.data.shape_keys.key_blocks
            shape_keys = sorted(block.name for block in blocks)
        except Exception:
            shape_keys = []
        if not shape_keys:
            failures.append({
                "check": "shape_keys",
                "message": (
                    f"Mesh '{mesh_obj.name}' has no shape keys "
                    f"for armature '{arm_obj.name}'"
                ),
            })

    return {
        "success": True,
        "armature": arm_obj.name,
        "mesh": mesh_obj.name if mesh_obj is not None else None,
        "bone_count": bone_count,
        "bones": sorted(bone.name for bone in bones),
        "symmetric": not asymmetric and not mirrored,
        "asymmetric_bones": asymmetric,
        "unmirrored_pairs": sorted(mirrored),
        "constraint_count": len(constraints),
        "constraints": constraints,
        "shape_keys": shape_keys,
        "passed": len(failures) == 0,
        "failures": failures,
    }


__all__ = [
    "create_face_rig",
    "create_jaw_bone",
    "create_eyelid_bones",
    "create_finger_rig",
    "create_ik_leg_rig",
    "create_ik_arm_rig",
    "add_face_shape_keys",
    "validate_character_rig",
]
