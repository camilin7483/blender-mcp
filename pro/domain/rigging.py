"""Armature rigging utilities: bones, IK chains, constraints and skinning.

Blender 4.5 LTS and 5.2 LTS compatible. Uses only `bpy`, `mathutils`
and the standard library. Public parameters use meters and degrees.
"""

import math

import bpy
from mathutils import Euler, Vector

_VALID_AXES = ("X", "Y", "Z")


def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


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


def _validate_int(value, label, minimum=None):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if number != as_float:
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {number})")
    return number


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


def _get_object(object_name, label="object_name"):
    name = _validate_name(object_name, label)
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found")
    return obj


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


def _get_pose_bone(arm_obj, bone_name):
    name = _validate_name(bone_name, "bone_name")
    pose_bone = arm_obj.pose.bones.get(name)
    if pose_bone is None:
        raise ValueError(
            f"Bone '{name}' not found in armature '{arm_obj.name}'"
        )
    return pose_bone


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


def list_bones(server, armature_name) -> dict:
    """List bone names, parents and head/tail positions in armature space."""
    del server
    arm_obj = _get_armature(armature_name)

    bones = []
    for bone in arm_obj.data.bones:
        parent = bone.parent
        bones.append({
            "name": bone.name,
            "parent": parent.name if parent is not None else None,
            "head": _round3(bone.head_local),
            "tail": _round3(bone.tail_local),
        })
    bones.sort(key=lambda item: item["name"])

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone_count": len(bones),
        "bones": bones,
    }


def create_bone(server, armature_name, bone_name, head, tail,
                parent=None, connected=False) -> dict:
    """Create a bone in an armature, optionally parented to another bone."""
    del server
    arm_obj = _get_armature(armature_name)
    bone_name = _validate_name(bone_name, "bone_name")
    head = _validate_vector3(head, "head")
    tail = _validate_vector3(tail, "tail")
    if Vector(tail) - Vector(head) == Vector((0.0, 0.0, 0.0)):
        raise ValueError("head and tail must differ (zero-length bone)")
    if not isinstance(connected, bool):
        raise ValueError(
            f"connected must be a bool (got {connected!r})"
        )
    parent_name = None
    if parent is not None:
        parent_name = _validate_name(parent, "parent")
        if parent_name not in arm_obj.data.bones:
            raise ValueError(
                f"Parent bone '{parent_name}' not found "
                f"in armature '{arm_obj.name}'"
            )
        if parent_name == bone_name:
            raise ValueError("A bone cannot be its own parent")
    if connected and parent_name is None:
        raise ValueError("connected=True requires a parent bone")
    if bone_name in arm_obj.data.bones:
        raise ValueError(
            f"Bone '{bone_name}' already exists "
            f"in armature '{arm_obj.name}'"
        )

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
            edit_bone = arm_obj.data.edit_bones.new(bone_name)
            edit_bone.head = Vector(head)
            edit_bone.tail = Vector(tail)
            if parent_name is not None:
                edit_bone.parent = arm_obj.data.edit_bones.get(parent_name)
                if edit_bone.parent is None:
                    raise ValueError(
                        f"Parent bone '{parent_name}' not available "
                        "in Edit Mode"
                    )
                edit_bone.use_connect = connected
            final_head = _round3(edit_bone.head)
            final_tail = _round3(edit_bone.tail)
            final_parent = (
                edit_bone.parent.name if edit_bone.parent else None
            )
            final_connected = bool(edit_bone.use_connect)
        finally:
            _restore_mode(view_layer, arm_obj, previous_active,
                          previous_mode)
    except ValueError:
        raise
    except RuntimeError as exc:
        raise ValueError(f"Could not create bone '{bone_name}': {exc}")
    view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": bone_name,
        "head": final_head,
        "tail": final_tail,
        "parent": final_parent,
        "connected": final_connected,
    }


def create_ik_chain(server, armature_name, base_bone, target_name,
                    chain_count=2, pole_target=None) -> dict:
    """Add an IK constraint on a pose bone with target and chain length."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, base_bone)
    target_obj = _get_object(target_name, "target_name")
    chain_count = _validate_int(chain_count, "chain_count", minimum=1)
    pole_obj = None
    if pole_target is not None:
        pole_obj = _get_object(pole_target, "pole_target")

    constraint = pose_bone.constraints.new(type="IK")
    constraint.target = target_obj
    constraint.chain_count = chain_count
    if pole_obj is not None:
        constraint.pole_target = pole_obj
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": pose_bone.name,
        "constraint": constraint.name,
        "constraint_type": constraint.type,
        "target": target_obj.name,
        "chain_count": int(constraint.chain_count),
        "pole_target": pole_obj.name if pole_obj is not None else None,
        "influence": round(float(constraint.influence), 6),
    }


def add_copy_rotation_constraint(server, armature_name, bone_name,
                                 target_name, influence=1.0) -> dict:
    """Add a COPY_ROTATION constraint on a pose bone targeting an object."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, bone_name)
    target_obj = _get_object(target_name, "target_name")
    influence = _validate_float(influence, "influence", minimum=0.0,
                                maximum=1.0)

    constraint = pose_bone.constraints.new(type="COPY_ROTATION")
    constraint.target = target_obj
    constraint.influence = influence
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": pose_bone.name,
        "constraint": constraint.name,
        "constraint_type": constraint.type,
        "target": target_obj.name,
        "influence": round(float(constraint.influence), 6),
    }


def add_limit_rotation_constraint(server, armature_name, bone_name,
                                  axes=("X", "Y", "Z"),
                                  limits=(-90.0, 90.0)) -> dict:
    """Add a LIMIT_ROTATION constraint with degree limits on chosen axes."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, bone_name)

    try:
        axes_list = list(axes)
    except TypeError:
        raise ValueError(
            f"axes must be a sequence with items from {list(_VALID_AXES)} "
            f"(got {axes!r})"
        )
    if not axes_list:
        raise ValueError("axes must contain at least one axis")
    normalized = []
    for axis in axes_list:
        text = str(axis).upper() if isinstance(axis, str) else ""
        if text not in _VALID_AXES:
            raise ValueError(
                f"axes must only contain items from {list(_VALID_AXES)} "
                f"(got {axes!r})"
            )
        if text not in normalized:
            normalized.append(text)

    try:
        limits_list = list(limits)
    except TypeError:
        raise ValueError(
            f"limits must be a (min, max) pair in degrees (got {limits!r})"
        )
    if len(limits_list) != 2:
        raise ValueError(
            f"limits must be a (min, max) pair in degrees (got {limits!r})"
        )
    minimum = _validate_float(limits_list[0], "limits[0]")
    maximum = _validate_float(limits_list[1], "limits[1]")
    if maximum < minimum:
        raise ValueError(
            f"limits max ({maximum}) must be >= min ({minimum})"
        )
    min_rad = math.radians(minimum)
    max_rad = math.radians(maximum)

    constraint = pose_bone.constraints.new(type="LIMIT_ROTATION")
    constraint.use_limit_x = "X" in normalized
    constraint.use_limit_y = "Y" in normalized
    constraint.use_limit_z = "Z" in normalized
    if "X" in normalized:
        constraint.min_x = min_rad
        constraint.max_x = max_rad
    if "Y" in normalized:
        constraint.min_y = min_rad
        constraint.max_y = max_rad
    if "Z" in normalized:
        constraint.min_z = min_rad
        constraint.max_z = max_rad
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": pose_bone.name,
        "constraint": constraint.name,
        "constraint_type": constraint.type,
        "axes": normalized,
        "limits_degrees": [minimum, maximum],
        "limits_radians": [round(min_rad, 6), round(max_rad, 6)],
        "influence": round(float(constraint.influence), 6),
    }


def set_bone_rotation(server, armature_name, bone_name,
                      rotation_degrees) -> dict:
    """Set a pose bone XYZ Euler rotation from degrees."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, bone_name)
    rotation = _validate_vector3(rotation_degrees, "rotation_degrees")

    radians = [math.radians(angle) for angle in rotation]
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler = Euler(radians, "XYZ")
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": pose_bone.name,
        "rotation_mode": pose_bone.rotation_mode,
        "rotation_degrees": _round3(rotation),
        "rotation_radians": _round3(radians),
    }


def set_bone_location(server, armature_name, bone_name,
                      location) -> dict:
    """Set a pose bone location in meters."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, bone_name)
    coords = _validate_vector3(location, "location")

    pose_bone.location = Vector(coords)
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": pose_bone.name,
        "location": _round3(pose_bone.location),
    }


def skin_mesh_to_armature(server, mesh_name, armature_name,
                          automatic=True) -> dict:
    """Parent a mesh to an armature with automatic weights or empty groups."""
    del server
    mesh_obj = _get_object(mesh_name, "mesh_name")
    if mesh_obj.type != "MESH":
        raise ValueError(
            f"Object '{mesh_obj.name}' is not a mesh (got {mesh_obj.type})"
        )
    arm_obj = _get_armature(armature_name)
    if not isinstance(automatic, bool):
        raise ValueError(
            f"automatic must be a bool (got {automatic!r})"
        )
    parent_type = "ARMATURE_AUTO" if automatic else "ARMATURE_NAME"

    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    try:
        previous_mode = previous_active.mode
    except Exception:
        previous_mode = "OBJECT"
    previous_selection = [
        obj for obj in bpy.context.selected_objects
    ]
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    try:
        bpy.ops.object.select_all(action="DESELECT")
        mesh_obj.select_set(True)
        arm_obj.select_set(True)
        view_layer.objects.active = arm_obj
        bpy.ops.object.parent_set(type=parent_type)
    except RuntimeError as exc:
        raise ValueError(
            f"Could not parent '{mesh_obj.name}' to "
            f"'{arm_obj.name}': {exc}"
        )
    finally:
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        for obj in previous_selection:
            try:
                obj.select_set(True)
            except Exception:
                continue
        _restore_mode(view_layer, arm_obj, previous_active, previous_mode)
    view_layer.update()

    groups = sorted(group.name for group in mesh_obj.vertex_groups)

    return {
        "success": True,
        "mesh": mesh_obj.name,
        "armature": arm_obj.name,
        "method": parent_type,
        "automatic": automatic,
        "vertex_groups": groups,
        "vertex_group_count": len(groups),
    }
