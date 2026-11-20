"""Hardsurface primitives: text objects, curve tubes, metaballs, conversion.

Blender 4.5 LTS and 5.2 LTS compatible. Uses only `bpy` and the
standard library.
"""

import math

import bpy

_VALID_ALIGN_X = ("LEFT", "CENTER", "RIGHT", "JUSTIFY", "FLUSH")
_DEFAULT_TUBE_POINTS = (
    (-1.0, 0.0, 0.0),
    (-0.33, 0.5, 0.2),
    (0.33, -0.5, 0.4),
    (1.0, 0.0, 0.6),
)
_CONVERTIBLE_TYPES = ("CURVE", "FONT", "SURFACE", "META")


def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def _as_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number.")
    return result


def _as_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    return value


def _check_range(value, label, minimum=None, maximum=None):
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum}.")
    return value


def _validate_vector(value, label, size=3):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(
            f"{label} must be a sequence of {size} numbers."
        )
    coords = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            raise ValueError(f"{label} coordinates must be finite numbers.")
        number = float(channel)
        if not math.isfinite(number):
            raise ValueError(f"{label} coordinates must be finite numbers.")
        coords.append(number)
    return tuple(coords)


def _link_object(obj):
    collection = getattr(bpy.context, "collection", None)
    if collection is None:
        collection = bpy.context.scene.collection
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


def _dimensions(obj):
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    try:
        return [float(v) for v in obj.dimensions]
    except Exception:
        return [0.0, 0.0, 0.0]


def _validate_points(points):
    if points is None:
        return [tuple(p) for p in _DEFAULT_TUBE_POINTS]
    if not isinstance(points, (list, tuple)) or len(points) < 2:
        raise ValueError(
            "points must be a sequence of at least two (x, y, z) coordinates."
        )
    if len(points) > 1024:
        raise ValueError("points must contain at most 1024 control points.")
    result = []
    for index, item in enumerate(points):
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise ValueError(
                f"points[{index}] must be an (x, y, z) sequence of 3 numbers."
            )
        coords = []
        for channel in item:
            if isinstance(channel, bool) or not isinstance(channel, (int, float)):
                raise ValueError(
                    f"points[{index}] coordinates must be finite numbers."
                )
            value = float(channel)
            if not math.isfinite(value):
                raise ValueError(
                    f"points[{index}] coordinates must be finite numbers."
                )
            coords.append(value)
        result.append(tuple(coords))
    return result


def _polyline_length(points):
    total = 0.0
    for first, second in zip(points, points[1:]):
        total += math.dist(first, second)
    return total


def create_text_object(server, text="Text", name="Text", size=1.0,
                       extrude=0.0, align_x="CENTER") -> dict:
    """Create a Blender Text (font curve) object with body/size/extrude."""
    del server
    if not isinstance(text, str):
        raise ValueError("text must be a string.")
    name = _validate_name(name)
    size = _as_number(size, "size")
    _check_range(size, "size", minimum=0.001, maximum=1000.0)
    extrude = _as_number(extrude, "extrude")
    _check_range(extrude, "extrude", minimum=0.0, maximum=1000.0)
    if not isinstance(align_x, str):
        raise ValueError(
            f"align_x must be one of {list(_VALID_ALIGN_X)} (got {align_x!r})."
        )
    align = align_x.strip().upper()
    if align not in _VALID_ALIGN_X:
        raise ValueError(
            f"align_x must be one of {list(_VALID_ALIGN_X)} (got {align_x!r})."
        )

    curve_data = bpy.data.curves.new(name + "Data", type="FONT")
    curve_data.body = text
    curve_data.size = size
    curve_data.extrude = extrude
    curve_data.align_x = align
    obj = bpy.data.objects.new(name, curve_data)
    _link_object(obj)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "type": obj.type,
        "text": text,
        "size": size,
        "extrude": extrude,
        "align_x": align,
        "dimensions": _dimensions(obj),
    }


def create_curve_tube(server, name="Tube", points=None, radius=0.05,
                      resolution=12, cyclic=False) -> dict:
    """Create a 3D poly curve with a round bevel (tube), kept as a curve."""
    del server
    name = _validate_name(name)
    path = _validate_points(points)
    radius = _as_number(radius, "radius")
    _check_range(radius, "radius", minimum=0.0, maximum=1000.0)
    resolution = _as_int(resolution, "resolution")
    _check_range(resolution, "resolution", minimum=0, maximum=32)
    if not isinstance(cyclic, bool):
        raise ValueError(f"cyclic must be a boolean (got {cyclic!r}).")

    curve_data = bpy.data.curves.new(name + "Data", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = radius
    curve_data.bevel_resolution = resolution
    # Cap ends with a round profile when supported; ignore otherwise.
    try:
        curve_data.use_fill_caps = True
    except Exception:
        pass

    spline = curve_data.splines.new("POLY")
    spline.points.add(len(path) - 1)
    for spline_point, coords in zip(spline.points, path):
        spline_point.co = (coords[0], coords[1], coords[2], 1.0)
    spline.use_cyclic_u = cyclic

    obj = bpy.data.objects.new(name, curve_data)
    _link_object(obj)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "type": obj.type,
        "length": _polyline_length(path),
        "dimensions": _dimensions(obj),
        "radius": radius,
        "bevel_depth": float(curve_data.bevel_depth),
        "resolution": resolution,
        "cyclic": cyclic,
        "point_count": len(path),
        "converted": False,
    }


def create_metaball(server, name="Metaball", radius=0.5, stiffness=2.0,
                    location=(0.0, 0.0, 0.0)) -> dict:
    """Create a metaball object with a single element at location."""
    del server
    name = _validate_name(name)
    radius = _as_number(radius, "radius")
    _check_range(radius, "radius", minimum=0.001, maximum=1000.0)
    stiffness = _as_number(stiffness, "stiffness")
    _check_range(stiffness, "stiffness", minimum=0.001, maximum=1000.0)
    loc = _validate_vector(location, "location")

    mball = bpy.data.metaballs.new(name + "Data")
    resolution = max(0.02, min(float(radius) * 0.25, 0.2))
    mball.resolution = resolution
    mball.render_resolution = resolution
    if len(mball.elements) == 0:
        element = mball.elements.new()
    else:
        element = mball.elements[0]
    element.co = (0.0, 0.0, 0.0)
    element.radius = radius
    element.stiffness = stiffness

    obj = bpy.data.objects.new(name, mball)
    obj.location = loc
    _link_object(obj)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "type": obj.type,
        "radius": float(element.radius),
        "stiffness": float(element.stiffness),
        "location": [float(v) for v in obj.location],
        "resolution": float(resolution),
    }


def convert_to_mesh(server, object_name) -> dict:
    """Convert a CURVE/FONT/SURFACE/META object to MESH, preserving its name."""
    del server
    if not isinstance(object_name, str) or not object_name.strip():
        raise ValueError("object_name must be a non-empty string.")
    key = object_name.strip()
    obj = bpy.data.objects.get(key)
    if obj is None:
        raise ValueError(f"Object '{key}' not found.")
    if obj.type == "MESH":
        return {
            "success": True,
            "name": obj.name,
            "object": obj.name,
            "type": obj.type,
            "converted": False,
            "polygon_count": len(obj.data.polygons),
        }
    if obj.type not in _CONVERTIBLE_TYPES:
        raise ValueError(
            f"Object '{obj.name}' of type {obj.type} cannot be converted to MESH; "
            f"expected one of {list(_CONVERTIBLE_TYPES)}."
        )

    original_name = obj.name
    source_type = obj.type
    if obj.type == "META":
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.convert(target="MESH")
        converted = bpy.context.view_layer.objects.active
        if converted is None or converted.type != "MESH" or not converted.data.polygons:
            raise ValueError(
                f"Conversion of '{original_name}' produced an empty mesh."
            )
        if converted.name != original_name and bpy.data.objects.get(original_name) is None:
            converted.name = original_name
        return {
            "success": True,
            "name": converted.name,
            "object": converted.name,
            "type": converted.type,
            "converted": True,
            "polygon_count": len(converted.data.polygons),
            "source_type": source_type,
        }

    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(obj_eval)
    if mesh is None:
        raise ValueError(
            f"Could not convert object '{original_name}' to MESH."
        )
    if len(mesh.polygons) == 0:
        bpy.data.meshes.remove(mesh)
        raise ValueError(
            f"Conversion of '{original_name}' produced an empty mesh "
            "(check curve bevel depth / text body)."
        )

    # Preserve the original name: park the old object, reuse the name.
    obj.name = original_name + "_convert_src"
    new_obj = bpy.data.objects.new(original_name, mesh)
    new_obj.matrix_world = obj.matrix_world
    for collection in list(obj.users_collection):
        if new_obj.name not in collection.objects:
            collection.objects.link(new_obj)
    if not new_obj.users_collection:
        _link_object(new_obj)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    bpy.data.objects.remove(obj, do_unlink=True)

    return {
        "success": True,
        "name": new_obj.name,
        "object": new_obj.name,
        "type": new_obj.type,
        "converted": True,
        "polygon_count": len(mesh.polygons),
        "source_type": source_type,
    }
