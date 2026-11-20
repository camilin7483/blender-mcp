"""Animation utilities: frame range, keyframing, rigs and actions.

Blender 4.5 LTS and 5.2 LTS compatible. Uses only `bpy`, `mathutils`
and the standard library. Works with both legacy actions (with
`action.fcurves`) and layered actions (layers/strips/channelbags):
fcurves are collected through a safe fallback instead of assuming
`action.fcurves` always exists.
"""

import math

import bpy
from mathutils import Vector

_VALID_INTERPOLATIONS = (
    "CONSTANT",
    "LINEAR",
    "BEZIER",
    "SINE",
    "QUAD",
    "CUBIC",
    "QUART",
    "QUINT",
    "EXPO",
    "CIRC",
    "BACK",
    "BOUNCE",
    "ELASTIC",
)

_VALID_AXES = ("X", "Y", "Z")

# Default path used by keyframe_path: a small arc in front of the origin.
_DEFAULT_ARC = (
    (-2.0, 0.0, 1.0),
    (-1.0, 1.0, 1.5),
    (0.0, 0.0, 2.0),
    (1.0, -1.0, 1.5),
    (2.0, 0.0, 1.0),
)


def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


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


def _get_object(object_name):
    if not isinstance(object_name, str) or not object_name.strip():
        raise ValueError("object_name must be a non-empty string")
    obj = bpy.data.objects.get(object_name.strip())
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")
    return obj


def _validate_interpolation(value, label="interpolation"):
    text = str(value).upper() if isinstance(value, str) else ""
    if text not in _VALID_INTERPOLATIONS:
        raise ValueError(
            f"{label} must be one of {list(_VALID_INTERPOLATIONS)} "
            f"(got {value!r})"
        )
    return text


def _iter_fcurves(action):
    """Yield fcurves from legacy or layered (4.4+/5.x) actions."""
    seen = set()

    def _yield_from(fcurves):
        for fcurve in fcurves:
            if id(fcurve) not in seen:
                seen.add(id(fcurve))
                yield fcurve

    try:
        legacy = getattr(action, "fcurves", None)
    except Exception:
        legacy = None
    if legacy is not None:
        try:
            yield from _yield_from(legacy)
        except Exception:
            pass

    try:
        layers = getattr(action, "layers", None)
    except Exception:
        layers = None
    if not layers:
        return
    try:
        layer_list = list(layers)
    except Exception:
        return
    for layer in layer_list:
        try:
            strips = list(getattr(layer, "strips", []) or [])
        except Exception:
            continue
        for strip in strips:
            bags = []
            try:
                single = getattr(strip, "channelbag", None)
            except Exception:
                single = None
            if single is not None:
                bags.append(single)
            try:
                multi = getattr(strip, "channelbags", None)
            except Exception:
                multi = None
            if multi:
                try:
                    bags.extend(list(multi))
                except Exception:
                    pass
            for bag in bags:
                try:
                    fcurves = getattr(bag, "fcurves", None)
                except Exception:
                    fcurves = None
                if fcurves is None:
                    continue
                try:
                    yield from _yield_from(fcurves)
                except Exception:
                    continue


def _count_keyframes(action):
    fcurve_count = 0
    keyframe_count = 0
    for fcurve in _iter_fcurves(action):
        fcurve_count += 1
        try:
            keyframe_count += len(fcurve.keyframe_points)
        except Exception:
            continue
    return fcurve_count, keyframe_count


def _apply_interpolation(action, interpolation):
    updated_fcurves = 0
    updated_keyframes = 0
    for fcurve in _iter_fcurves(action):
        touched = False
        try:
            points = list(fcurve.keyframe_points)
        except Exception:
            continue
        for keyframe in points:
            try:
                keyframe.interpolation = interpolation
                updated_keyframes += 1
                touched = True
            except Exception:
                continue
        if touched:
            updated_fcurves += 1
        try:
            fcurve.update()
        except Exception:
            pass
    return updated_fcurves, updated_keyframes


def _assign_action_slot(animation_data, action):
    """Point animation_data at the action's first slot when slots exist."""
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


def set_frame_range(server, start=1, end=250, fps=24) -> dict:
    """Set the scene frame range and render frame rate."""
    del server
    start = _validate_int(start, "start")
    end = _validate_int(end, "end")
    if end < start:
        raise ValueError(f"end ({end}) must be >= start ({start})")
    fps = _validate_float(fps, "fps", minimum=0.001, maximum=120.0)

    scene = bpy.context.scene
    scene.frame_start = start
    scene.frame_end = end
    scene.render.fps = max(1, int(fps))
    try:
        scene.render.fps_base = 1.0
    except (TypeError, ValueError, AttributeError):
        pass

    return {
        "success": True,
        "frame_start": start,
        "frame_end": end,
        "frame_count": end - start + 1,
        "fps": fps,
    }


def keyframe_path(server, object_name, points=None, frame_start=1,
                  frame_end=100, interpolation="BEZIER") -> dict:
    """Move an object along waypoints, keyframing location at each one."""
    del server
    obj = _get_object(object_name)
    frame_start = _validate_int(frame_start, "frame_start")
    frame_end = _validate_int(frame_end, "frame_end")
    if frame_end <= frame_start:
        raise ValueError(
            f"frame_end ({frame_end}) must be > frame_start ({frame_start})"
        )
    interpolation = _validate_interpolation(interpolation)

    if points is None:
        cleaned = [list(point) for point in _DEFAULT_ARC]
    else:
        try:
            raw = list(points)
        except TypeError:
            raise ValueError("points must be a sequence of 3D coordinates")
        if len(raw) < 2:
            raise ValueError(
                f"points must contain at least 2 entries (got {len(raw)})"
            )
        cleaned = [_validate_vector3(point, f"points[{i}]")
                   for i, point in enumerate(raw)]

    scene = bpy.context.scene
    scene.frame_start = frame_start
    scene.frame_end = frame_end

    count = len(cleaned)
    span = frame_end - frame_start
    for index, point in enumerate(cleaned):
        frame = frame_start + round(span * index / (count - 1))
        obj.location = Vector(point)
        obj.keyframe_insert(data_path="location", frame=frame)
    bpy.context.view_layer.update()

    animation_data = obj.animation_data
    action = getattr(animation_data, "action", None) if animation_data else None
    if action is None:
        raise ValueError(
            f"Could not create animation data for '{obj.name}'"
        )
    _apply_interpolation(action, interpolation)
    fcurve_count, keyframe_count = _count_keyframes(action)

    return {
        "success": True,
        "object": obj.name,
        "action": action.name,
        "keyframes": keyframe_count,
        "fcurves": fcurve_count,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "point_count": count,
        "interpolation": interpolation,
    }


def create_turntable_animation(server, object_name, frames=120,
                               axis="Z") -> dict:
    """Keyframe a full 0..360 degree spin around one local axis."""
    del server
    obj = _get_object(object_name)
    frames = _validate_int(frames, "frames", minimum=2)
    axis = str(axis).upper() if isinstance(axis, str) else ""
    if axis not in _VALID_AXES:
        raise ValueError(
            f"axis must be one of {list(_VALID_AXES)} (got {axis!r})"
        )

    axis_index = _VALID_AXES.index(axis)
    if getattr(obj, "rotation_mode", "XYZ") != "XYZ":
        obj.rotation_mode = "XYZ"

    scene = bpy.context.scene
    frame_start = int(scene.frame_start)
    frame_end = frame_start + frames - 1
    scene.frame_end = max(int(scene.frame_end), frame_end)

    start_rotation = [0.0, 0.0, 0.0]
    end_rotation = [0.0, 0.0, 0.0]
    end_rotation[axis_index] = math.tau

    obj.rotation_euler = start_rotation
    obj.keyframe_insert(data_path="rotation_euler", frame=frame_start)
    obj.rotation_euler = end_rotation
    obj.keyframe_insert(data_path="rotation_euler", frame=frame_end)
    bpy.context.view_layer.update()

    animation_data = obj.animation_data
    action = getattr(animation_data, "action", None) if animation_data else None
    if action is None:
        raise ValueError(
            f"Could not create animation data for '{obj.name}'"
        )
    # Linear spacing makes the loop seamless (cyclic-friendly).
    _apply_interpolation(action, "LINEAR")
    fcurve_count, keyframe_count = _count_keyframes(action)

    return {
        "success": True,
        "object": obj.name,
        "action": action.name,
        "axis": axis,
        "frames": frames,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "rotation_degrees": 360.0,
        "interpolation": "LINEAR",
        "cyclic_friendly": True,
        "fcurves": fcurve_count,
        "keyframes": keyframe_count,
    }


def create_camera_rig(server, name="CameraRig", target=(0.0, 0.0, 1.0),
                      distance=6.0, height=3.0) -> dict:
    """Create a camera aimed at an empty target via a Track To constraint."""
    del server
    name = _validate_name(name)
    target_location = _validate_vector3(target, "target")
    distance = _validate_float(distance, "distance", minimum=0.001)
    height = _validate_float(height, "height")

    camera_location = [
        target_location[0],
        target_location[1] - distance,
        target_location[2] + height,
    ]

    empty = bpy.data.objects.new(name=f"{name}_Target", object_data=None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.location = Vector(target_location)
    bpy.context.collection.objects.link(empty)

    camera_data = bpy.data.cameras.new(name=f"{name}_Camera")
    camera = bpy.data.objects.new(name=f"{name}_Camera",
                                  object_data=camera_data)
    camera.location = Vector(camera_location)
    bpy.context.collection.objects.link(camera)

    track = camera.constraints.new(type="TRACK_TO")
    track.target = empty
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    bpy.context.view_layer.update()

    return {
        "success": True,
        "rig": name,
        "camera": camera.name,
        "target": empty.name,
        "constraint": track.name,
        "constraint_type": track.type,
        "camera_location": [round(c, 6) for c in camera.location],
        "target_location": [round(c, 6) for c in empty.location],
        "distance": distance,
        "height": height,
    }


def add_follow_path_constraint(server, object_name, curve_name,
                               offset=0.0) -> dict:
    """Add a FOLLOW_PATH constraint targeting a curve object."""
    del server
    obj = _get_object(object_name)
    if not isinstance(curve_name, str) or not curve_name.strip():
        raise ValueError("curve_name must be a non-empty string")
    curve = bpy.data.objects.get(curve_name.strip())
    if curve is None:
        raise ValueError(f"Curve '{curve_name}' not found")
    if curve.type != "CURVE":
        raise ValueError(
            f"Object '{curve.name}' is not a curve (got {curve.type})"
        )
    offset = _validate_float(offset, "offset")

    constraint = obj.constraints.new(type="FOLLOW_PATH")
    constraint.target = curve
    try:
        forward = getattr(constraint, "forward_axis", None)
    except Exception:
        forward = None
    if forward is None:
        try:
            constraint.forward_axis = "TRACK_NEGATIVE_Y"
        except Exception:
            pass
    applied_offset = None
    if 0.0 <= offset <= 1.0:
        try:
            if hasattr(constraint, "offset_factor"):
                constraint.offset_factor = offset
                applied_offset = offset
        except Exception:
            pass
    if applied_offset is None:
        try:
            if hasattr(constraint, "offset"):
                constraint.offset = offset
                applied_offset = offset
        except Exception:
            pass
    bpy.context.view_layer.update()

    try:
        influence = float(constraint.influence)
    except Exception:
        influence = 1.0

    return {
        "success": True,
        "object": obj.name,
        "constraint": constraint.name,
        "constraint_type": constraint.type,
        "curve": curve.name,
        "offset": applied_offset if applied_offset is not None else offset,
        "influence": influence,
    }


def set_keyframe_interpolation(server, object_name,
                               interpolation="LINEAR") -> dict:
    """Set the interpolation of every keyframe on an animated object."""
    del server
    obj = _get_object(object_name)
    interpolation = _validate_interpolation(interpolation)

    animation_data = obj.animation_data
    action = getattr(animation_data, "action", None) if animation_data else None
    if action is None:
        raise ValueError(f"Object '{obj.name}' has no animation data")

    fcurve_count, keyframe_count = _apply_interpolation(action, interpolation)
    if keyframe_count == 0:
        raise ValueError(f"Object '{obj.name}' has no keyframes")

    return {
        "success": True,
        "object": obj.name,
        "action": action.name,
        "interpolation": interpolation,
        "fcurves": fcurve_count,
        "keyframes": keyframe_count,
    }


def create_action(server, object_name, name="Action") -> dict:
    """Create a new action and assign it to an object, preserving the object."""
    del server
    obj = _get_object(object_name)
    name = _validate_name(name)

    animation_data = obj.animation_data
    if animation_data is None:
        animation_data = obj.animation_data_create()
    previous = None
    try:
        current = getattr(animation_data, "action", None)
    except Exception:
        current = None
    if current is not None:
        previous = getattr(current, "name", None)

    action = bpy.data.actions.new(name=name)
    animation_data.action = action
    slot_name = _assign_action_slot(animation_data, action)

    return {
        "success": True,
        "object": obj.name,
        "action": action.name,
        "previous_action": previous,
        "action_slot": slot_name,
    }


def clear_animation(server, object_name) -> dict:
    """Remove an object's animation data, keeping constraints intact."""
    del server
    obj = _get_object(object_name)

    animation_data = obj.animation_data
    if animation_data is None:
        return {
            "success": True,
            "object": obj.name,
            "previous_action": None,
            "cleared": False,
        }
    try:
        current = getattr(animation_data, "action", None)
    except Exception:
        current = None
    previous = getattr(current, "name", None) if current is not None else None
    obj.animation_data_clear()

    return {
        "success": True,
        "object": obj.name,
        "previous_action": previous,
        "cleared": True,
    }
