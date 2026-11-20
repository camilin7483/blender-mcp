"""Hardsurface modifiers: bevel, solidify, array, mirror and apply.

Blender 4.5 LTS and 5.2 LTS compatible. Uses only `bpy` and the
standard library. Public parameters use meters and degrees.
"""

import math

import bpy


def _get_mesh_object(object_name):
    if not isinstance(object_name, str) or not object_name.strip():
        raise ValueError("object_name must be a non-empty string.")
    cleaned = object_name.strip()
    obj = bpy.data.objects.get(cleaned)
    if obj is None:
        raise ValueError(f"Object '{cleaned}' not found.")
    if obj.type != "MESH" or obj.data is None:
        raise ValueError(f"Object '{obj.name}' is not a mesh object.")
    return obj


def _as_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number (got {value!r}).")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number (got {value!r}).")
    return result


def _as_int(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be an integer (got {value!r}).")
    if float(value) != int(value):
        raise ValueError(f"{label} must be an integer (got {value!r}).")
    return int(value)


def _check_range(value, label, minimum=None, maximum=None):
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {value}).")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {value}).")
    return value


def _as_bool(value, label):
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a bool (got {value!r}).")
    return value


def _validate_offset(offset):
    if not isinstance(offset, (list, tuple)) or len(offset) != 3:
        raise ValueError(
            f"offset must be a sequence of 3 numbers (got {offset!r})."
        )
    return tuple(_as_number(v, f"offset[{i}]") for i, v in enumerate(offset))


def _reuse_modifier(obj, mod_type):
    """Return first modifier of type, removing extras to avoid duplicates."""
    found = None
    for mod in list(obj.modifiers):
        if mod.type == mod_type:
            if found is None:
                found = mod
            else:
                obj.modifiers.remove(mod)
    if found is None:
        found = obj.modifiers.new(name=mod_type.capitalize(), type=mod_type)
    return found


def _set_mode_object(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass


def add_bevel_modifier(server, object_name, width=0.02, segments=2,
                       angle_limit=30.0) -> dict:
    """Add (or update) an ANGLE-limit bevel modifier on a mesh object."""
    del server
    obj = _get_mesh_object(object_name)
    width = _as_number(width, "width")
    _check_range(width, "width", minimum=0.0)
    if width <= 0.0:
        raise ValueError(f"width must be > 0 (got {width}).")
    segments = _as_int(segments, "segments")
    _check_range(segments, "segments", minimum=1, maximum=32)
    angle_limit = _as_number(angle_limit, "angle_limit")
    _check_range(angle_limit, "angle_limit", minimum=0.0, maximum=180.0)

    mod = _reuse_modifier(obj, "BEVEL")
    mod.limit_method = "ANGLE"
    mod.width = width
    mod.segments = segments
    mod.angle_limit = math.radians(angle_limit)

    return {
        "success": True,
        "object": obj.name,
        "modifier": mod.name,
        "modifier_type": mod.type,
        "width": width,
        "segments": segments,
        "angle_limit": angle_limit,
        "limit_method": mod.limit_method,
    }


def add_solidify_modifier(server, object_name, thickness=0.02,
                          offset=-1.0) -> dict:
    """Add (or update) a solidify modifier on a mesh object."""
    del server
    obj = _get_mesh_object(object_name)
    thickness = _as_number(thickness, "thickness")
    offset = _as_number(offset, "offset")
    _check_range(offset, "offset", minimum=-1.0, maximum=1.0)

    mod = _reuse_modifier(obj, "SOLIDIFY")
    mod.thickness = thickness
    mod.offset = offset

    return {
        "success": True,
        "object": obj.name,
        "modifier": mod.name,
        "modifier_type": mod.type,
        "thickness": thickness,
        "offset": offset,
    }


def add_array_modifier(server, object_name, count=3,
                       offset=(0.0, 0.0, 0.0), relative=False) -> dict:
    """Add (or update) an array modifier; constant or relative offset."""
    del server
    obj = _get_mesh_object(object_name)
    count = _as_int(count, "count")
    _check_range(count, "count", minimum=1)
    values = _validate_offset(offset)
    relative = _as_bool(relative, "relative")

    mod = _reuse_modifier(obj, "ARRAY")
    mod.count = count
    if relative:
        mod.use_relative_offset = True
        mod.use_constant_offset = False
        mod.relative_offset_displace = values
    else:
        mod.use_constant_offset = True
        mod.use_relative_offset = False
        mod.constant_offset_displace = values

    return {
        "success": True,
        "object": obj.name,
        "modifier": mod.name,
        "modifier_type": mod.type,
        "count": count,
        "offset": list(values),
        "relative": relative,
    }


def add_mirror_modifier(server, object_name, axis="X",
                        bisect=False) -> dict:
    """Add (or update) a mirror modifier on one axis, no mirror object."""
    del server
    obj = _get_mesh_object(object_name)
    if not isinstance(axis, str) or axis.strip().upper() not in ("X", "Y", "Z"):
        raise ValueError(f"axis must be one of ['X', 'Y', 'Z'] (got {axis!r}).")
    axis = axis.strip().upper()
    bisect = _as_bool(bisect, "bisect")

    mod = _reuse_modifier(obj, "MIRROR")
    mod.mirror_object = None
    index = {"X": 0, "Y": 1, "Z": 2}[axis]
    for i in range(3):
        mod.use_axis[i] = (i == index)
        mod.use_bisect_axis[i] = (i == index and bisect)

    return {
        "success": True,
        "object": obj.name,
        "modifier": mod.name,
        "modifier_type": mod.type,
        "axis": axis,
        "bisect": bisect,
    }


def apply_all_modifiers(server, object_name) -> dict:
    """Apply every modifier on a mesh object, in stack order."""
    del server
    obj = _get_mesh_object(object_name)
    names = [mod.name for mod in obj.modifiers]
    if not names:
        return {"success": True, "object": obj.name, "applied": []}

    _set_mode_object(obj)
    applied = []
    errors = []
    for name in names:
        if obj.modifiers.get(name) is None:
            continue
        try:
            bpy.ops.object.modifier_apply(modifier=name)
            applied.append(name)
        except Exception as exc:
            errors.append({"modifier": name, "error": str(exc)})
    if errors:
        return {
            "success": False,
            "object": obj.name,
            "applied": applied,
            "failed": [e["modifier"] for e in errors],
            "errors": errors,
            "error": f"Failed to apply {len(errors)} modifier(s) on '{obj.name}'.",
        }
    return {"success": True, "object": obj.name, "applied": applied}
