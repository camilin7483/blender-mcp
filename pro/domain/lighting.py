"""Lighting, camera, world background and still rendering tools.

Blender 4.5 LTS and 5.2 LTS compatible. Uses only `bpy`, `mathutils`
and the standard library. Public distances are in meters, angles in degrees.
"""

import math
import os
import time

import bpy
from mathutils import Euler, Vector

_VALID_LIGHT_TYPES = ("POINT", "SUN", "AREA", "SPOT")
_VALID_CAMERA_TYPES = ("PERSP", "ORTHO")
_VALID_ENGINES = (
    "BLENDER_EEVEE_NEXT",
    "BLENDER_EEVEE",
    "BLENDER_WORKBENCH",
    "CYCLES",
)


def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_float(value, label, minimum=None, maximum=None):
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


def _validate_int(value, label, minimum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if isinstance(value, bool) or number != float(value):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {number})")
    return number


def _validate_vector3(value, label):
    try:
        items = [float(item) for item in value]
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a sequence of 3 numbers (got {value!r})")
    if len(items) != 3 or not all(math.isfinite(item) for item in items):
        raise ValueError(f"{label} must be a sequence of 3 finite numbers (got {value!r})")
    return items


def _validate_color(value, label):
    try:
        items = [float(item) for item in value]
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a sequence of 3 or 4 numbers (got {value!r})")
    if len(items) not in (3, 4) or not all(math.isfinite(item) for item in items):
        raise ValueError(f"{label} must be a sequence of 3 or 4 finite numbers (got {value!r})")
    if any(item < 0.0 or item > 1.0 for item in items):
        raise ValueError(f"{label} channels must be in [0, 1] (got {value!r})")
    return items


def _set_if_exists(target, attr, value):
    if target is not None and hasattr(target, attr):
        setattr(target, attr, value)
        return True
    return False


def create_light(server, name="Light", light_type="POINT", energy=100.0,
                 color=(1.0, 1.0, 1.0), location=(0.0, 0.0, 3.0),
                 rotation=(0.0, 0.0, 0.0), size=0.1,
                 spot_size=45.0) -> dict:
    """Create a light object and link it to the active collection."""
    name = _validate_name(name)
    light_type = str(light_type).upper() if isinstance(light_type, str) else ""
    if light_type not in _VALID_LIGHT_TYPES:
        raise ValueError(
            f"light_type must be one of {list(_VALID_LIGHT_TYPES)} (got {light_type!r})"
        )
    energy = _validate_float(energy, "energy", minimum=0.0)
    rgb = _validate_color(color, "color")[:3]
    loc = _validate_vector3(location, "location")
    rot = _validate_vector3(rotation, "rotation")
    size = _validate_float(size, "size", minimum=0.0)
    spot_size = _validate_float(spot_size, "spot_size", minimum=1.0, maximum=180.0)

    light_data = bpy.data.lights.new(name=name, type=light_type)
    light_data.energy = energy
    light_data.color = (rgb[0], rgb[1], rgb[2])
    # `size` only exists on some light types/versions; spot angle is radians.
    _set_if_exists(light_data, "size", size)
    if light_type == "SPOT":
        _set_if_exists(light_data, "spot_size", math.radians(spot_size))

    light_obj = bpy.data.objects.new(name=name, object_data=light_data)
    light_obj.location = Vector(loc)
    light_obj.rotation_euler = Euler(
        (math.radians(rot[0]), math.radians(rot[1]), math.radians(rot[2])), "XYZ"
    )
    bpy.context.collection.objects.link(light_obj)
    bpy.context.view_layer.update()

    return {
        "success": True,
        "name": light_obj.name,
        "type": light_type,
        "energy": energy,
        "color": [round(c, 6) for c in rgb],
        "location": [round(c, 6) for c in light_obj.location],
        "rotation": [round(math.degrees(a), 6) for a in light_obj.rotation_euler],
        "size": size,
        "spot_size": spot_size,
    }


def create_camera(server, name="Camera", location=(7.0, -7.0, 5.0),
                  look_at=(0.0, 0.0, 1.0), lens=50.0, ortho_scale=6.0,
                  camera_type="PERSP") -> dict:
    """Create a camera aimed at `look_at` via a track quaternion."""
    name = _validate_name(name)
    camera_type = str(camera_type).upper() if isinstance(camera_type, str) else ""
    if camera_type not in _VALID_CAMERA_TYPES:
        raise ValueError(
            f"camera_type must be one of {list(_VALID_CAMERA_TYPES)} (got {camera_type!r})"
        )
    loc = _validate_vector3(location, "location")
    target = _validate_vector3(look_at, "look_at")
    lens = _validate_float(lens, "lens", minimum=0.001)
    ortho_scale = _validate_float(ortho_scale, "ortho_scale", minimum=0.001)

    direction = Vector(target) - Vector(loc)
    if direction.length < 1e-9:
        raise ValueError("look_at must differ from location")

    cam_data = bpy.data.cameras.new(name=name)
    cam_data.type = camera_type
    cam_data.lens = lens
    cam_data.ortho_scale = ortho_scale

    cam_obj = bpy.data.objects.new(name=name, object_data=cam_data)
    cam_obj.location = Vector(loc)
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.collection.objects.link(cam_obj)
    bpy.context.view_layer.update()

    scene = bpy.context.scene
    became_active = False
    if scene.camera is None:
        scene.camera = cam_obj
        became_active = True

    return {
        "success": True,
        "name": cam_obj.name,
        "type": camera_type,
        "lens": lens,
        "ortho_scale": ortho_scale,
        "location": [round(c, 6) for c in cam_obj.location],
        "look_at": [round(c, 6) for c in target],
        "rotation": [round(math.degrees(a), 6) for a in cam_obj.rotation_euler],
        "is_active_camera": scene.camera == cam_obj,
        "became_active_camera": became_active,
    }


def setup_world_background(server, color=(0.05, 0.05, 0.05),
                           strength=1.0) -> dict:
    """Create or reuse the scene World with a Background node."""
    rgb = _validate_color(color, "color")[:3]
    strength = _validate_float(strength, "strength", minimum=0.0)

    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new(name="World")
        scene.world = world
    world.use_nodes = True
    tree = world.node_tree

    background = next((n for n in tree.nodes if n.type == "BACKGROUND"), None)
    if background is None:
        background = tree.nodes.new(type="ShaderNodeBackground")
    output = next((n for n in tree.nodes if n.type == "OUTPUT_WORLD"), None)
    if output is None:
        output = tree.nodes.new(type="ShaderNodeOutputWorld")

    if "Color" in background.inputs:
        background.inputs["Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    if "Strength" in background.inputs:
        background.inputs["Strength"].default_value = strength
    if "Background" in background.outputs and "Surface" in output.inputs:
        linked = any(
            link.from_node == background and link.to_node == output
            for link in tree.links
        )
        if not linked:
            tree.links.new(background.outputs["Background"], output.inputs["Surface"])

    return {
        "success": True,
        "world": world.name,
        "color": [round(c, 6) for c in rgb],
        "strength": strength,
    }


def render_still(server, filepath, camera_name=None, resolution_x=960,
                 resolution_y=540, samples=32,
                 engine="BLENDER_EEVEE_NEXT", transparent=False) -> dict:
    """Render the scene to `filepath` and report timing and file size."""
    if not isinstance(filepath, str) or not filepath.strip():
        raise ValueError("filepath must be a non-empty string")
    path = os.path.abspath(os.path.expanduser(filepath.strip()))
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    engine_name = str(engine).upper() if isinstance(engine, str) else ""
    if engine_name not in _VALID_ENGINES:
        raise ValueError(
            f"engine must be one of {list(_VALID_ENGINES)} (got {engine!r})"
        )
    resolution_x = _validate_int(resolution_x, "resolution_x", minimum=1)
    resolution_y = _validate_int(resolution_y, "resolution_y", minimum=1)
    samples = _validate_int(samples, "samples", minimum=1)

    scene = bpy.context.scene
    if camera_name is not None:
        cam_obj = bpy.data.objects.get(str(camera_name))
        if cam_obj is None:
            raise ValueError(f"Camera '{camera_name}' not found")
        if cam_obj.type != "CAMERA":
            raise ValueError(
                f"Object '{camera_name}' is not a camera (got {cam_obj.type})"
            )
        scene.camera = cam_obj
    if scene.camera is None:
        raise ValueError("Scene has no active camera; create one with create_camera")

    # EEVEE was renamed to BLENDER_EEVEE_NEXT in 4.2; accept both spellings.
    candidates = [engine_name]
    if engine_name == "BLENDER_EEVEE_NEXT":
        candidates.append("BLENDER_EEVEE")
    applied_engine = None
    last_error = None
    for candidate in candidates:
        try:
            scene.render.engine = candidate
            applied_engine = candidate
            break
        except (TypeError, ValueError, AttributeError) as exc:
            last_error = exc
    if applied_engine is None:
        raise ValueError(f"Render engine '{engine_name}' is not available: {last_error}")

    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = bool(transparent)
    scene.render.filepath = path

    samples_applied = False
    if applied_engine == "CYCLES":
        cycles = getattr(scene, "cycles", None)
        samples_applied = _set_if_exists(cycles, "samples", samples)
    else:
        eevee = getattr(scene, "eevee", None)
        for attr in ("taa_render_samples", "taa_samples", "samples"):
            if _set_if_exists(eevee, attr, samples):
                samples_applied = True
                break

    started = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    elapsed = time.perf_counter() - started

    if not os.path.exists(path):
        return {
            "success": False,
            "filepath": path,
            "engine": applied_engine,
            "error": f"Render finished but no file was written to '{path}'",
        }

    return {
        "success": True,
        "filepath": path,
        "engine": applied_engine,
        "requested_engine": engine_name,
        "resolution": [resolution_x, resolution_y],
        "samples": samples,
        "samples_applied": samples_applied,
        "transparent": bool(transparent),
        "camera": scene.camera.name,
        "file_size_bytes": os.path.getsize(path),
        "render_time_seconds": round(elapsed, 3),
    }
