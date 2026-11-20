"""Advanced rigging utilities: constraints, custom shapes, pose library and validation.

Blender 4.5 LTS and 5.2 LTS compatible. Uses only `bpy`, `mathutils`
and the standard library. Public parameters use meters and degrees.
"""

import math

import bpy

_VALID_TRACK_AXES = (
    "TRACK_X",
    "TRACK_NEGATIVE_X",
    "TRACK_Y",
    "TRACK_NEGATIVE_Y",
    "TRACK_Z",
    "TRACK_NEGATIVE_Z",
)

_VALID_MIRROR_AXES = ("X", "Y", "Z")


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


def _get_target(target_name):
    name = _validate_name(target_name, "target_name")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Target object '{name}' not found")
    return obj


def _validate_influence(influence):
    return _validate_float(influence, "influence", minimum=0.0, maximum=1.0)


def _snapshot_selection():
    view_layer = bpy.context.view_layer
    return (
        view_layer,
        view_layer.objects.active,
        list(bpy.context.selected_objects),
        getattr(view_layer.objects.active, "mode", "OBJECT"),
    )


def _restore_selection(snapshot):
    view_layer, active, selected, mode = snapshot
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    for obj in selected:
        try:
            obj.select_set(True)
        except Exception:
            continue
    try:
        view_layer.objects.active = active
    except Exception:
        pass
    if active is not None and mode not in (None, "OBJECT"):
        try:
            bpy.ops.object.mode_set(mode=mode)
        except Exception:
            pass


def _set_childof_inverse(arm_obj, pose_bone, constraint):
    """Preserve the bone transform after assigning a CHILD_OF target."""
    snapshot = _snapshot_selection()
    view_layer = snapshot[0]
    try:
        bpy.ops.object.select_all(action="DESELECT")
        arm_obj.select_set(True)
        view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode="POSE")
        try:
            arm_obj.data.bones.active = pose_bone.bone
        except Exception:
            pass
        bpy.ops.constraint.childof_set_inverse(
            constraint=constraint.name, owner="BONE"
        )
    except Exception:
        try:
            target = constraint.target
            if target is not None:
                bone_world = arm_obj.matrix_world @ pose_bone.bone.matrix_local
                constraint.inverse_matrix = (
                    target.matrix_world.inverted() @ bone_world
                ).inverted()
        except Exception:
            pass
    finally:
        _restore_selection(snapshot)


def _new_constraint(pose_bone, kind):
    try:
        return pose_bone.constraints.new(type=kind)
    except RuntimeError as exc:
        raise ValueError(
            f"Could not add {kind} constraint to "
            f"bone '{pose_bone.name}': {exc}"
        )


def _assign_action_slot(animation_data, action):
    try:
        slots = getattr(action, "slots", None)
    except Exception:
        return None
    if not slots:
        return None
    try:
        first = slots[0]
    except Exception:
        return None
    try:
        animation_data.action_slot = first
        return getattr(first, "name", None) or first.name
    except Exception:
        return None


def _round3(values):
    return [round(float(value), 6) for value in values]


def add_child_of_constraint(server, armature_name, bone_name,
                            target_name, influence=1.0) -> dict:
    """Add a CHILD_OF constraint on a pose bone targeting an object."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, bone_name)
    target_obj = _get_target(target_name)
    influence = _validate_influence(influence)

    constraint = _new_constraint(pose_bone, "CHILD_OF")
    constraint.target = target_obj
    constraint.influence = influence
    _set_childof_inverse(arm_obj, pose_bone, constraint)
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


def add_copy_location_constraint(server, armature_name, bone_name,
                                 target_name, influence=1.0) -> dict:
    """Add a COPY_LOCATION constraint on a pose bone targeting an object."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, bone_name)
    target_obj = _get_target(target_name)
    influence = _validate_influence(influence)

    constraint = _new_constraint(pose_bone, "COPY_LOCATION")
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


def add_damped_track_constraint(server, armature_name, bone_name,
                                target_name, track_axis="TRACK_Y",
                                influence=1.0) -> dict:
    """Add a DAMPED_TRACK constraint aiming a pose bone at an object."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, bone_name)
    target_obj = _get_target(target_name)
    if not isinstance(track_axis, str):
        raise ValueError(
            f"track_axis must be one of {list(_VALID_TRACK_AXES)} "
            f"(got {track_axis!r})"
        )
    axis = track_axis.strip().upper()
    if axis not in _VALID_TRACK_AXES:
        raise ValueError(
            f"track_axis must be one of {list(_VALID_TRACK_AXES)} "
            f"(got {track_axis!r})"
        )
    influence = _validate_influence(influence)

    constraint = _new_constraint(pose_bone, "DAMPED_TRACK")
    constraint.target = target_obj
    constraint.track_axis = axis
    constraint.influence = influence
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": pose_bone.name,
        "constraint": constraint.name,
        "constraint_type": constraint.type,
        "target": target_obj.name,
        "track_axis": constraint.track_axis,
        "influence": round(float(constraint.influence), 6),
    }


def add_stretch_to_constraint(server, armature_name, bone_name,
                              target_name, rest_length=0.0,
                              influence=1.0) -> dict:
    """Add a STRETCH_TO constraint; rest_length 0 means auto from bone length."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, bone_name)
    target_obj = _get_target(target_name)
    rest_length = _validate_float(rest_length, "rest_length", minimum=0.0)
    influence = _validate_influence(influence)

    auto = rest_length == 0.0
    if auto:
        bone = pose_bone.bone
        rest_length = float((bone.tail_local - bone.head_local).length)

    constraint = _new_constraint(pose_bone, "STRETCH_TO")
    constraint.target = target_obj
    constraint.rest_length = rest_length
    constraint.influence = influence
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": pose_bone.name,
        "constraint": constraint.name,
        "constraint_type": constraint.type,
        "target": target_obj.name,
        "rest_length": round(float(constraint.rest_length), 6),
        "rest_length_auto": auto,
        "influence": round(float(constraint.influence), 6),
    }


def set_bone_custom_shape(server, armature_name, bone_name,
                          object_name) -> dict:
    """Assign an object as the custom shape of a pose bone."""
    del server
    arm_obj = _get_armature(armature_name)
    pose_bone = _get_pose_bone(arm_obj, bone_name)
    shape_obj = _get_target(object_name)

    pose_bone.custom_shape = shape_obj
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "bone": pose_bone.name,
        "custom_shape": shape_obj.name,
    }


def create_pose_library_action(server, armature_name,
                               action_name="Pose") -> dict:
    """Keyframe all pose bones and store the pose in a new action."""
    del server
    arm_obj = _get_armature(armature_name)
    action_name = _validate_name(action_name, "action_name")
    if not arm_obj.pose.bones:
        raise ValueError(f"Armature '{arm_obj.name}' has no pose bones")

    animation_data = arm_obj.animation_data
    if animation_data is None:
        animation_data = arm_obj.animation_data_create()
    action = bpy.data.actions.new(name=action_name)
    try:
        animation_data.action = action
    except (AttributeError, TypeError, RuntimeError) as exc:
        raise ValueError(
            f"Could not assign action '{action.name}' "
            f"to '{arm_obj.name}': {exc}"
        )
    slot_name = _assign_action_slot(animation_data, action)

    frame = int(bpy.context.scene.frame_current)
    keyframed = 0
    for pose_bone in arm_obj.pose.bones:
        rotation_path = (
            "rotation_quaternion"
            if pose_bone.rotation_mode == "QUATERNION"
            else "rotation_euler"
        )
        ok = True
        for path in ("location", rotation_path, "scale"):
            try:
                pose_bone.keyframe_insert(data_path=path, frame=frame)
            except (RuntimeError, TypeError):
                ok = False
        if ok:
            keyframed += 1
    if keyframed == 0:
        raise ValueError(
            f"Could not keyframe any bone of '{arm_obj.name}'"
        )
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "action": action.name,
        "action_slot": slot_name,
        "frame": frame,
        "bone_count": len(arm_obj.pose.bones),
        "keyframed_bones": keyframed,
        "keyframes": keyframed * 3,
    }


def mirror_pose(server, armature_name, axis="X") -> dict:
    """Mirror every pose bone transform across one axis (negate the other two)."""
    del server
    arm_obj = _get_armature(armature_name)
    if not isinstance(axis, str):
        raise ValueError(
            f"axis must be one of {list(_VALID_MIRROR_AXES)} "
            f"(got {axis!r})"
        )
    clean_axis = axis.strip().upper()
    if clean_axis not in _VALID_MIRROR_AXES:
        raise ValueError(
            f"axis must be one of {list(_VALID_MIRROR_AXES)} "
            f"(got {axis!r})"
        )
    if not arm_obj.pose.bones:
        raise ValueError(f"Armature '{arm_obj.name}' has no pose bones")

    mirror_index = _VALID_MIRROR_AXES.index(clean_axis)
    keep = {"X": 0, "Y": 1, "Z": 2}[clean_axis]
    mirrored = 0
    for pose_bone in arm_obj.pose.bones:
        location = list(pose_bone.location)
        location[mirror_index] = -location[mirror_index]
        pose_bone.location = location
        if pose_bone.rotation_mode == "QUATERNION":
            quat = list(pose_bone.rotation_quaternion)
            for index in range(1, 4):
                if index - 1 != keep:
                    quat[index] = -quat[index]
            pose_bone.rotation_quaternion = quat
        elif pose_bone.rotation_mode == "AXIS_ANGLE":
            axis_angle = list(pose_bone.rotation_axis_angle)
            for index in range(1, 4):
                if index - 1 != keep:
                    axis_angle[index] = -axis_angle[index]
            pose_bone.rotation_axis_angle = axis_angle
        else:
            euler = list(pose_bone.rotation_euler)
            for index in range(3):
                if index != keep:
                    euler[index] = -euler[index]
            pose_bone.rotation_euler = euler
        mirrored += 1
    bpy.context.view_layer.update()

    return {
        "success": True,
        "armature": arm_obj.name,
        "axis": clean_axis,
        "mirrored_bones": mirrored,
        "mirrored_count": mirrored,
        "bone_count": len(arm_obj.pose.bones),
    }


def _find_skinned_mesh(arm_obj, mesh_name):
    if mesh_name is not None:
        name = _validate_name(mesh_name, "mesh_name")
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise ValueError(f"Mesh '{name}' not found")
        if obj.type != "MESH":
            raise ValueError(
                f"Object '{name}' is not a mesh (got {obj.type})"
            )
        if obj.data is None:
            raise ValueError(f"Mesh '{name}' has no mesh data")
        return obj
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        try:
            modifiers = list(obj.modifiers)
        except Exception:
            modifiers = []
        for modifier in modifiers:
            try:
                is_armature = modifier.type == "ARMATURE"
                target = modifier.object
            except Exception:
                continue
            if is_armature and target == arm_obj:
                return obj
        try:
            if obj.parent == arm_obj:
                return obj
        except Exception:
            continue
    return None


def validate_rig(server, armature_name, mesh_name=None) -> dict:
    """Validate bones, parenting, skinning and vertex weights of a rig."""
    del server
    arm_obj = _get_armature(armature_name)
    mesh_obj = _find_skinned_mesh(arm_obj, mesh_name)

    failures = []
    bones = list(arm_obj.data.bones)
    bone_count = len(bones)
    if bone_count == 0:
        failures.append({
            "check": "bones",
            "message": f"Armature '{arm_obj.name}' has no bones",
        })

    cyclic = []
    for bone in bones:
        seen = {bone.name}
        current = bone.parent
        while current is not None:
            if current.name in seen:
                cyclic.append(bone.name)
                break
            seen.add(current.name)
            current = current.parent
    if cyclic:
        failures.append({
            "check": "parent_cycles",
            "message": "Parent cycles detected",
            "bones": sorted(cyclic),
        })

    deform_bones = [bone for bone in bones if bone.use_deform]
    missing_groups = []
    unweighted_count = 0
    unweighted_sample = []
    mesh_label = mesh_obj.name if mesh_obj is not None else None
    if mesh_name is not None or mesh_obj is not None:
        if mesh_obj is None:
            failures.append({
                "check": "mesh",
                "message": (
                    f"No mesh skinned to armature '{arm_obj.name}' found"
                ),
            })
        else:
            has_modifier = False
            try:
                modifiers = list(mesh_obj.modifiers)
            except Exception:
                modifiers = []
            for modifier in modifiers:
                try:
                    if (modifier.type == "ARMATURE"
                            and modifier.object == arm_obj):
                        has_modifier = True
                        break
                except Exception:
                    continue
            try:
                parented = mesh_obj.parent == arm_obj
            except Exception:
                parented = False
            if not has_modifier and not parented:
                failures.append({
                    "check": "armature_modifier",
                    "message": (
                        f"Mesh '{mesh_obj.name}' has no ARMATURE modifier "
                        f"or parent link to '{arm_obj.name}'"
                    ),
                })
            group_names = {group.name for group in mesh_obj.vertex_groups}
            missing_groups = sorted(
                bone.name for bone in deform_bones
                if bone.name not in group_names
            )
            if missing_groups:
                failures.append({
                    "check": "vertex_groups",
                    "message": (
                        f"Mesh '{mesh_obj.name}' is missing vertex groups "
                        f"for {len(missing_groups)} deform bone(s)"
                    ),
                    "bones": missing_groups,
                })
            try:
                vertices = list(mesh_obj.data.vertices)
            except Exception:
                vertices = []
            for vertex in vertices:
                try:
                    groups = list(vertex.groups)
                except Exception:
                    groups = []
                total = 0.0
                for entry in groups:
                    try:
                        total += float(entry.weight)
                    except Exception:
                        continue
                if total <= 0.0:
                    unweighted_count += 1
                    if len(unweighted_sample) < 10:
                        unweighted_sample.append(vertex.index)
            if unweighted_count:
                failures.append({
                    "check": "unweighted_vertices",
                    "message": (
                        f"Mesh '{mesh_obj.name}' has {unweighted_count} "
                        "vertex/vertices with no deform weight"
                    ),
                    "count": unweighted_count,
                    "sample": unweighted_sample,
                })

    try:
        constraint_count = sum(
            len(pose_bone.constraints)
            for pose_bone in arm_obj.pose.bones
        )
    except Exception:
        constraint_count = 0

    return {
        "success": True,
        "armature": arm_obj.name,
        "mesh": mesh_label,
        "bone_count": bone_count,
        "deform_bone_count": len(deform_bones),
        "constraint_count": constraint_count,
        "missing_vertex_groups": missing_groups,
        "unweighted_vertex_count": unweighted_count,
        "passed": len(failures) == 0,
        "failures": failures,
    }


__all__ = [
    "add_child_of_constraint",
    "add_copy_location_constraint",
    "add_damped_track_constraint",
    "add_stretch_to_constraint",
    "set_bone_custom_shape",
    "create_pose_library_action",
    "mirror_pose",
    "validate_rig",
]
