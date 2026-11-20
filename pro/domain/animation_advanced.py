"""Advanced animation utilities: NLA tracks, camera shake, markers, motion paths.

Blender 4.5 LTS and 5.2 LTS compatible. Uses only `bpy`, `mathutils`
and the standard library. Layered-action-safe: fcurves are collected
through a safe fallback instead of assuming `action.fcurves` exists,
and NLA strips reference actions with their first slot when the
layered-action API is present.
"""

import math
import random

import bpy
from mathutils import Vector

# preset -> (interpolation, easing, auto_handles)
_PRESETS = {
    "linear": ("LINEAR", "AUTO", False),
    "constant": ("CONSTANT", "AUTO", False),
    "bezier": ("BEZIER", "AUTO", True),
    "ease_in": ("SINE", "EASE_IN", True),
    "ease_out": ("SINE", "EASE_OUT", True),
    "ease_in_out": ("CUBIC", "EASE_IN_OUT", True),
}


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


def _validate_bool(value, label):
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a bool (got {value!r})")
    return value


def _get_object(object_name, label="object_name"):
    name = _validate_name(object_name, label)
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found")
    return obj


def _get_camera(camera_name):
    obj = _get_object(camera_name, "camera_name")
    if obj.type != "CAMERA" or obj.data is None:
        raise ValueError(
            f"Object '{obj.name}' is not a camera (got {obj.type})"
        )
    return obj


def _get_action(action_name):
    name = _validate_name(action_name, "action_name")
    action = bpy.data.actions.get(name)
    if action is None:
        raise ValueError(f"Action '{name}' not found")
    return action


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


def _keyframe_frame_range(action):
    frames = []
    for fcurve in _iter_fcurves(action):
        try:
            points = list(fcurve.keyframe_points)
        except Exception:
            continue
        for point in points:
            try:
                frames.append(float(point.co.x))
            except Exception:
                continue
    if not frames:
        return None, None
    return min(frames), max(frames)


def _restore_context(view_layer, previous_active, previous_mode,
                     previous_selection):
    try:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        for obj in previous_selection:
            try:
                obj.select_set(True)
            except Exception:
                continue
        try:
            view_layer.objects.active = previous_active
        except Exception:
            pass
        if previous_active is not None and previous_mode not in (None,
                                                                  "OBJECT"):
            try:
                bpy.ops.object.mode_set(mode=previous_mode)
            except Exception:
                pass
    finally:
        try:
            view_layer.update()
        except Exception:
            pass


def _unique_marker_name(base):
    markers = bpy.context.scene.timeline_markers
    name = base
    counter = 1
    existing = {marker.name for marker in markers}
    while name in existing:
        counter += 1
        name = f"{base}.{counter:03d}"
    return name


def create_nla_track(server, object_name, action_name,
                     start_frame=1) -> dict:
    """Create an NLA track on an object with a strip of an action."""
    del server
    obj = _get_object(object_name)
    action = _get_action(action_name)
    start_frame = _validate_int(start_frame, "start_frame")

    animation_data = obj.animation_data
    if animation_data is None:
        animation_data = obj.animation_data_create()

    track = animation_data.nla_tracks.new()
    track.name = f"{action.name}_Track"
    try:
        strip = track.strips.new(action.name, start_frame, action)
    except (TypeError, ValueError, RuntimeError) as exc:
        try:
            animation_data.nla_tracks.remove(track)
        except Exception:
            pass
        raise ValueError(
            f"Could not create NLA strip of '{action.name}' "
            f"on '{obj.name}': {exc}"
        )
    # Layered actions (4.4+/5.x) resolve fcurves through a slot.
    try:
        slots = getattr(action, "slots", None)
        if slots:
            strip.action_slot = slots[0]
            slot_name = getattr(slots[0], "name", None)
        else:
            slot_name = None
    except Exception:
        slot_name = None
    try:
        strip_frame_start = float(strip.frame_start)
        strip_frame_end = float(strip.frame_end)
    except Exception:
        strip_frame_start = float(start_frame)
        strip_frame_end = float(start_frame)
    bpy.context.view_layer.update()

    return {
        "success": True,
        "object": obj.name,
        "action": action.name,
        "action_slot": slot_name,
        "track": track.name,
        "strip": strip.name,
        "start_frame": start_frame,
        "strip_frame_start": strip_frame_start,
        "strip_frame_end": strip_frame_end,
        "track_count": len(animation_data.nla_tracks),
    }


def add_camera_shake(server, camera_name, strength=0.05, frame_start=1,
                     frame_end=60, seed=0) -> dict:
    """Add deterministic location/rotation jitter keys to a camera."""
    del server
    camera = _get_camera(camera_name)
    strength = _validate_float(strength, "strength", minimum=0.0)
    frame_start = _validate_int(frame_start, "frame_start")
    frame_end = _validate_int(frame_end, "frame_end")
    if frame_end <= frame_start:
        raise ValueError(
            f"frame_end ({frame_end}) must be > frame_start ({frame_start})"
        )
    seed = _validate_int(seed, "seed")

    if getattr(camera, "rotation_mode", "XYZ") != "XYZ":
        camera.rotation_mode = "XYZ"
    base_location = Vector(camera.location)
    base_rotation = Vector(camera.rotation_euler)
    rotation_amplitude = strength * 0.2

    animation_data = camera.animation_data
    action = getattr(animation_data, "action", None) if animation_data else None
    _, keys_before = _count_keyframes(action) if action is not None else (0, 0)

    rng = random.Random(seed)
    frames = list(range(frame_start, frame_end + 1))
    for frame in frames:
        offset = Vector(
            (rng.random() - 0.5) * 2.0 * strength for _ in range(3)
        )
        tilt = Vector(
            (rng.random() - 0.5) * 2.0 * rotation_amplitude
            for _ in range(3)
        )
        camera.location = base_location + offset
        camera.rotation_euler = base_rotation + tilt
        camera.keyframe_insert(data_path="location", frame=frame)
        camera.keyframe_insert(data_path="rotation_euler", frame=frame)
    bpy.context.view_layer.update()

    animation_data = camera.animation_data
    action = getattr(animation_data, "action", None) if animation_data else None
    if action is None:
        raise ValueError(
            f"Could not create animation data for '{camera.name}'"
        )
    _, keys_after = _count_keyframes(action)

    return {
        "success": True,
        "camera": camera.name,
        "strength": strength,
        "rotation_amplitude": round(rotation_amplitude, 6),
        "frame_start": frame_start,
        "frame_end": frame_end,
        "frames_keyed": len(frames),
        "keyframes_added": keys_after - keys_before,
        "seed": seed,
    }


def add_timeline_marker(server, name, frame=1) -> dict:
    """Create a timeline marker at a frame."""
    del server
    name = _validate_name(name)
    frame = _validate_int(frame, "frame")

    scene = bpy.context.scene
    marker = scene.timeline_markers.new(name=name, frame=frame)

    return {
        "success": True,
        "marker": marker.name,
        "frame": int(marker.frame),
        "marker_count": len(scene.timeline_markers),
    }


def set_motion_paths(server, object_name, enabled=True) -> dict:
    """Create or remove a baked polyline preview of an object/bone path."""
    del server
    obj = _get_object(object_name)
    enabled = _validate_bool(enabled, "enabled")
    curve_name = f"{object_name}_MotionPath"
    existing = bpy.data.objects.get(curve_name)
    if existing is not None:
        data = existing.data
        bpy.data.objects.remove(existing, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.curves.remove(data)
    if not enabled:
        return {
            "success": True,
            "object": obj.name,
            "enabled": False,
            "removed": existing is not None,
            "mode": "baked_curve",
        }

    action = obj.animation_data.action if obj.animation_data else None
    start, end = (1, 60)
    if action is not None:
        try:
            start = int(round(action.frame_range[0]))
            end = int(round(action.frame_range[1]))
        except Exception:
            pass
    if end <= start:
        end = start + 1
    step = max(1, (end - start) // 40)
    frames = list(range(start, end + 1, step))
    if frames[-1] != end:
        frames.append(end)

    scene = bpy.context.scene
    original_frame = scene.frame_current
    samples = {}
    try:
        for frame in frames:
            scene.frame_set(frame)
            if obj.type == "ARMATURE":
                for pose_bone in obj.pose.bones:
                    point = obj.matrix_world @ pose_bone.head
                    samples.setdefault(pose_bone.name, []).append(tuple(point))
            else:
                point = obj.matrix_world.translation.copy()
                samples.setdefault(obj.name, []).append(tuple(point))
    finally:
        scene.frame_set(original_frame)

    curve_data = bpy.data.curves.new(curve_name, type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 1
    for name, points in samples.items():
        if len(points) < 2:
            continue
        spline = curve_data.splines.new("POLY")
        spline.points.add(len(points) - 1)
        for index, point in enumerate(points):
            spline.points[index].co = (*point, 1.0)
        spline.use_cyclic_u = False
    curve_obj = bpy.data.objects.new(curve_name, curve_data)
    bpy.context.collection.objects.link(curve_obj)
    curve_obj.show_in_front = True
    return {
        "success": True,
        "object": obj.name,
        "enabled": True,
        "curve": curve_obj.name,
        "mode": "baked_curve",
        "frame_start": start,
        "frame_end": end,
        "samples": len(frames),
        "tracks": sorted(samples),
    }


def set_animation_curve_preset(server, object_name,
                               preset="ease_in_out") -> dict:
    """Set interpolation/easing of every keyframe to a named preset."""
    del server
    obj = _get_object(object_name)
    if not isinstance(preset, str):
        raise ValueError(
            f"preset must be one of {sorted(_PRESETS)} (got {preset!r})"
        )
    key = preset.strip().lower()
    if key not in _PRESETS:
        raise ValueError(
            f"preset must be one of {sorted(_PRESETS)} (got {preset!r})"
        )
    interpolation, easing, auto_handles = _PRESETS[key]

    animation_data = obj.animation_data
    action = getattr(animation_data, "action", None) if animation_data else None
    if action is None:
        raise ValueError(f"Object '{obj.name}' has no animation data")

    fcurve_count = 0
    keyframe_count = 0
    for fcurve in _iter_fcurves(action):
        touched = False
        try:
            points = list(fcurve.keyframe_points)
        except Exception:
            continue
        for point in points:
            try:
                point.interpolation = interpolation
            except Exception:
                continue
            try:
                point.easing = easing
            except Exception:
                pass
            if auto_handles:
                for side in ("handle_left_type", "handle_right_type"):
                    try:
                        setattr(point, side, "AUTO_CLAMPED")
                    except Exception:
                        continue
            keyframe_count += 1
            touched = True
        if touched:
            fcurve_count += 1
        try:
            fcurve.update()
        except Exception:
            pass
    if keyframe_count == 0:
        raise ValueError(f"Object '{obj.name}' has no keyframes")

    return {
        "success": True,
        "object": obj.name,
        "action": action.name,
        "preset": key,
        "interpolation": interpolation,
        "easing": easing,
        "auto_handles": auto_handles,
        "fcurves": fcurve_count,
        "keyframes": keyframe_count,
    }


def retime_action(server, object_name, factor=1.0) -> dict:
    """Scale all keyframe times of an object's action by a factor."""
    del server
    obj = _get_object(object_name)
    factor = _validate_float(factor, "factor", minimum=1e-06)

    animation_data = obj.animation_data
    action = getattr(animation_data, "action", None) if animation_data else None
    if action is None:
        raise ValueError(f"Object '{obj.name}' has no animation data")

    old_start, old_end = _keyframe_frame_range(action)
    if old_start is None:
        raise ValueError(f"Object '{obj.name}' has no keyframes")

    fcurve_count = 0
    keyframe_count = 0
    for fcurve in _iter_fcurves(action):
        touched = False
        try:
            points = list(fcurve.keyframe_points)
        except Exception:
            continue
        for point in points:
            try:
                point.co.x *= factor
                point.handle_left.x *= factor
                point.handle_right.x *= factor
            except Exception:
                continue
            keyframe_count += 1
            touched = True
        if touched:
            fcurve_count += 1
        try:
            fcurve.update()
        except Exception:
            pass
    if keyframe_count == 0:
        raise ValueError(f"Object '{obj.name}' has no keyframes")
    bpy.context.view_layer.update()

    new_start, new_end = _keyframe_frame_range(action)

    return {
        "success": True,
        "object": obj.name,
        "action": action.name,
        "factor": factor,
        "fcurves": fcurve_count,
        "keyframes": keyframe_count,
        "old_frame_start": old_start,
        "old_frame_end": old_end,
        "new_frame_start": new_start,
        "new_frame_end": new_end,
    }


def create_camera_cut(server, camera_names, frame_ranges) -> dict:
    """Bind cameras to timeline markers, one marker per frame range."""
    del server
    try:
        names = list(camera_names)
    except TypeError:
        raise ValueError("camera_names must be a sequence of strings")
    try:
        ranges = list(frame_ranges)
    except TypeError:
        raise ValueError("frame_ranges must be a sequence of [start, end]")
    if not names:
        raise ValueError("camera_names must contain at least one camera")
    if len(names) != len(ranges):
        raise ValueError(
            f"camera_names ({len(names)}) and frame_ranges ({len(ranges)}) "
            "must have the same length"
        )

    cameras = [_get_camera(name) for name in names]
    parsed_ranges = []
    for index, entry in enumerate(ranges):
        try:
            pair = list(entry)
        except TypeError:
            raise ValueError(
                f"frame_ranges[{index}] must be a [start, end] pair "
                f"(got {entry!r})"
            )
        if len(pair) != 2:
            raise ValueError(
                f"frame_ranges[{index}] must be a [start, end] pair "
                f"(got {entry!r})"
            )
        start = _validate_int(pair[0], f"frame_ranges[{index}][0]")
        end = _validate_int(pair[1], f"frame_ranges[{index}][1]")
        if end < start:
            raise ValueError(
                f"frame_ranges[{index}] end ({end}) must be >= "
                f"start ({start})"
            )
        parsed_ranges.append((start, end))

    scene = bpy.context.scene
    cuts = []
    for index, (camera, (start, end)) in enumerate(
            zip(cameras, parsed_ranges)):
        marker_name = _unique_marker_name(f"Cut_{index + 1:02d}_{camera.name}")
        marker = scene.timeline_markers.new(name=marker_name, frame=start)
        marker.camera = camera
        cuts.append({
            "marker": marker.name,
            "camera": camera.name,
            "frame_start": start,
            "frame_end": end,
        })

    scene.frame_start = min(start for start, _ in parsed_ranges)
    scene.frame_end = max(end for _, end in parsed_ranges)
    scene.camera = cameras[0]
    bpy.context.view_layer.update()

    return {
        "success": True,
        "cuts": cuts,
        "cut_count": len(cuts),
        "scene_camera": scene.camera.name,
        "frame_start": int(scene.frame_start),
        "frame_end": int(scene.frame_end),
        "marker_count": len(scene.timeline_markers),
    }


def validate_animation(server, object_name) -> dict:
    """Validate an object's action, range, fcurves and scene cameras."""
    del server
    obj = _get_object(object_name)

    failures = []
    warnings = []
    animation_data = obj.animation_data
    action = getattr(animation_data, "action", None) if animation_data else None
    action_name = getattr(action, "name", None) if action is not None else None
    fcurve_count = 0
    keyframe_count = 0
    frame_start = None
    frame_end = None
    if action is None:
        failures.append(f"Object '{obj.name}' has no action assigned")
    else:
        fcurve_count, keyframe_count = _count_keyframes(action)
        if fcurve_count == 0:
            failures.append(
                f"Action '{action.name}' has no fcurves"
            )
        if keyframe_count == 0:
            failures.append(
                f"Action '{action.name}' has no keyframes"
            )
        frame_start, frame_end = _keyframe_frame_range(action)
        if (frame_start is not None and frame_end is not None
                and frame_end <= frame_start):
            failures.append(
                f"Action '{action.name}' spans a single frame "
                f"({frame_start:g})"
            )

    cameras = sorted(
        item.name for item in bpy.data.objects if item.type == "CAMERA"
    )
    if not cameras:
        warnings.append("Scene contains no camera objects")

    scene = bpy.context.scene
    markers = []
    for marker in scene.timeline_markers:
        try:
            bound = marker.camera
        except Exception:
            bound = None
        markers.append({
            "name": marker.name,
            "frame": int(marker.frame),
            "camera": bound.name if bound is not None else None,
        })
    markers.sort(key=lambda item: (item["frame"], item["name"]))
    if not markers:
        warnings.append("Scene contains no timeline markers")
    if obj.type == "CAMERA" and not any(
            item["camera"] == obj.name for item in markers):
        warnings.append(
            f"Camera '{obj.name}' is not bound to any timeline marker"
        )

    return {
        "success": True,
        "object": obj.name,
        "object_type": obj.type,
        "passed": len(failures) == 0,
        "failures": failures,
        "warnings": warnings,
        "action": action_name,
        "fcurves": fcurve_count,
        "keyframes": keyframe_count,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "cameras": cameras,
        "camera_count": len(cameras),
        "markers": markers,
        "marker_count": len(markers),
    }
