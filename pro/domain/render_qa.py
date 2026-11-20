"""Render configuration, turntable rendering and QA utilities.

Blender 4.5 LTS and 5.2 LTS compatible. Uses only `bpy`, `bmesh`,
`mathutils` and the standard library.
"""

import bmesh
import bpy
import math
import os
from mathutils import Vector

_VALID_ENGINES = (
    "BLENDER_EEVEE_NEXT",
    "BLENDER_EEVEE",
    "BLENDER_WORKBENCH",
    "CYCLES",
)

_PASS_ATTRS = {
    "AO": "use_pass_ambient_occlusion",
    "DEPTH": "use_pass_z",
    "NORMAL": "use_pass_normal",
    "MIST": "use_pass_mist",
    "EMIT": "use_pass_emit",
}

_TURNTABLE_CAMERA = "TurntableCamera"
_MAX_TURNTABLE_RES = 1024
_MAX_TURNTABLE_SAMPLES = 64
_MAX_TURNTABLE_FRAMES = 64
_MAX_SHEET_SOURCE_RES = 1024
_MAX_SHEET_RES = 4096
_MAX_COMPARE_RES = 2048
_MAX_GLARE_SIZE = 9


def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_int(value, label, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if isinstance(value, bool) or number != float(value):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {number})")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {number})")
    return number


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


def _validate_color(value, label):
    try:
        items = [float(item) for item in value]
    except (TypeError, ValueError):
        raise ValueError(
            f"{label} must be a sequence of 3 or 4 numbers (got {value!r})"
        )
    if len(items) not in (3, 4) or not all(math.isfinite(item) for item in items):
        raise ValueError(
            f"{label} must be a sequence of 3 or 4 finite numbers (got {value!r})"
        )
    if any(item < 0.0 or item > 1.0 for item in items):
        raise ValueError(f"{label} channels must be in [0, 1] (got {value!r})")
    if len(items) == 3:
        items.append(1.0)
    return items


def _set_if_exists(target, attr, value):
    if target is not None and hasattr(target, attr):
        setattr(target, attr, value)
        return True
    return False


def _unload_image(image):
    try:
        if image is not None and image.users == 0:
            bpy.data.images.remove(image)
    except (AttributeError, RuntimeError):
        pass


def _load_image_file(path, label):
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"{label} must be a non-empty string")
    resolved = os.path.abspath(os.path.expanduser(path.strip()))
    if not os.path.isfile(resolved):
        raise ValueError(f"{label} does not exist: '{resolved}'")
    try:
        return bpy.data.images.load(resolved)
    except RuntimeError as exc:
        raise ValueError(f"{label} could not be loaded: '{resolved}': {exc}")


def _scene_bounds():
    low = Vector((math.inf, math.inf, math.inf))
    high = Vector((-math.inf, -math.inf, -math.inf))
    found = False
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        try:
            corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        except (AttributeError, ValueError):
            continue
        for corner in corners:
            low.x = min(low.x, corner.x)
            low.y = min(low.y, corner.y)
            low.z = min(low.z, corner.z)
            high.x = max(high.x, corner.x)
            high.y = max(high.y, corner.y)
            high.z = max(high.z, corner.z)
        found = True
    if not found:
        return Vector((0.0, 0.0, 0.5)), 1.0
    center = (low + high) * 0.5
    size = high - low
    radius = max(size.x, size.y, size.z) * 0.5
    return center, max(radius, 0.1)


def configure_render(server, engine="BLENDER_EEVEE_NEXT", samples=32,
                     resolution_x=960, resolution_y=540,
                     film_transparent=False, fps=24) -> dict:
    """Set the scene render engine, resolution, samples and frame rate."""
    engine_name = str(engine).upper() if isinstance(engine, str) else ""
    if engine_name not in _VALID_ENGINES:
        raise ValueError(
            f"engine must be one of {list(_VALID_ENGINES)} (got {engine!r})"
        )
    resolution_x = _validate_int(resolution_x, "resolution_x", minimum=1)
    resolution_y = _validate_int(resolution_y, "resolution_y", minimum=1)
    samples = _validate_int(samples, "samples", minimum=1)
    fps = _validate_int(fps, "fps", minimum=1, maximum=240)
    if not isinstance(film_transparent, bool):
        raise ValueError(
            f"film_transparent must be a bool (got {film_transparent!r})"
        )

    scene = bpy.context.scene
    candidates = [engine_name]
    if engine_name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        for fallback in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            if fallback not in candidates:
                candidates.append(fallback)
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
        raise ValueError(
            f"Render engine '{engine_name}' is not available: {last_error}"
        )

    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = film_transparent
    scene.render.fps = fps

    samples_applied = False
    if applied_engine == "CYCLES":
        samples_applied = _set_if_exists(
            getattr(scene, "cycles", None), "samples", samples
        )
    else:
        eevee = getattr(scene, "eevee", None)
        for attr in ("taa_render_samples", "taa_samples", "samples"):
            if _set_if_exists(eevee, attr, samples):
                samples_applied = True
                break

    return {
        "success": True,
        "engine": scene.render.engine,
        "requested_engine": engine_name,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "resolution_percentage": scene.render.resolution_percentage,
        "samples": samples,
        "samples_applied": samples_applied,
        "film_transparent": bool(scene.render.film_transparent),
        "fps": scene.render.fps,
    }


def enable_render_pass(server, pass_name="AO", enabled=True) -> dict:
    """Enable or disable a named render pass on the active view layer."""
    if not isinstance(pass_name, str) or not pass_name.strip():
        raise ValueError("pass_name must be a non-empty string")
    key = pass_name.strip().upper()
    if key not in _PASS_ATTRS:
        raise ValueError(
            f"pass_name must be one of {sorted(_PASS_ATTRS)} (got {pass_name!r})"
        )
    if not isinstance(enabled, bool):
        raise ValueError(f"enabled must be a bool (got {enabled!r})")

    layer = bpy.context.view_layer
    attr = _PASS_ATTRS[key]
    if hasattr(layer, attr):
        setattr(layer, attr, enabled)
        return {
            "success": True,
            "pass": key,
            "attribute": attr,
            "enabled": enabled,
            "applied": True,
            "active": bool(getattr(layer, attr)),
        }
    return {
        "success": True,
        "pass": key,
        "attribute": attr,
        "enabled": enabled,
        "applied": False,
        "active": None,
    }


def render_turntable(server, directory, frames=12, resolution_x=256,
                     resolution_y=256, samples=8) -> dict:
    """Render a 360-degree turntable around the scene bounds."""
    if not isinstance(directory, str) or not directory.strip():
        raise ValueError("directory must be a non-empty string")
    out_dir = os.path.abspath(os.path.expanduser(directory.strip()))
    os.makedirs(out_dir, exist_ok=True)
    frames = _validate_int(frames, "frames", minimum=1,
                           maximum=_MAX_TURNTABLE_FRAMES)
    resolution_x = _validate_int(resolution_x, "resolution_x", minimum=1,
                                 maximum=_MAX_TURNTABLE_RES)
    resolution_y = _validate_int(resolution_y, "resolution_y", minimum=1,
                                 maximum=_MAX_TURNTABLE_RES)
    samples = _validate_int(samples, "samples", minimum=1,
                            maximum=_MAX_TURNTABLE_SAMPLES)

    center, radius = _scene_bounds()
    distance = max(radius * 3.0, 2.0)
    cam_height = max(center.z + radius * 0.8, 0.5)

    cam_obj = bpy.data.objects.get(_TURNTABLE_CAMERA)
    if cam_obj is not None and cam_obj.type != "CAMERA":
        raise ValueError(
            f"Object '{_TURNTABLE_CAMERA}' exists and is not a camera"
        )
    if cam_obj is None:
        cam_data = bpy.data.cameras.new(_TURNTABLE_CAMERA)
        cam_obj = bpy.data.objects.new(_TURNTABLE_CAMERA, cam_data)
        bpy.context.collection.objects.link(cam_obj)
    else:
        cam_obj.location = Vector((center.x + distance, center.y, cam_height))

    scene = bpy.context.scene
    scene.camera = cam_obj
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    engine = scene.render.engine
    if engine == "CYCLES":
        _set_if_exists(getattr(scene, "cycles", None), "samples", samples)
    else:
        eevee = getattr(scene, "eevee", None)
        for attr in ("taa_render_samples", "taa_samples", "samples"):
            if _set_if_exists(eevee, attr, samples):
                break

    previous_filepath = scene.render.filepath
    files = []
    try:
        for index in range(frames):
            angle = 2.0 * math.pi * index / frames
            location = Vector((
                center.x + distance * math.cos(angle),
                center.y + distance * math.sin(angle),
                cam_height,
            ))
            cam_obj.location = location
            direction = center - location
            cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
            bpy.context.view_layer.update()
            path = os.path.join(out_dir, f"turntable_{index:04d}.png")
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            files.append(path)
    finally:
        scene.render.filepath = previous_filepath

    missing = [path for path in files if not os.path.isfile(path)]
    if missing:
        return {
            "success": False,
            "camera": cam_obj.name,
            "directory": out_dir,
            "files": files,
            "error": f"Render finished but {len(missing)} file(s) missing: {missing[0]}",
        }
    return {
        "success": True,
        "camera": cam_obj.name,
        "directory": out_dir,
        "files": files,
        "frames": frames,
        "resolution": [resolution_x, resolution_y],
        "samples": samples,
        "center": [round(center.x, 6), round(center.y, 6), round(center.z, 6)],
        "radius": round(radius, 6),
        "engine": scene.render.engine,
    }


def render_contact_sheet(server, image_paths, filepath,
                         columns=4) -> dict:
    """Tile small images into a grid contact sheet saved to `filepath`."""
    try:
        paths = list(image_paths)
    except TypeError:
        raise ValueError("image_paths must be a sequence of file paths")
    if not paths:
        raise ValueError("image_paths must contain at least one path")
    if not isinstance(filepath, str) or not filepath.strip():
        raise ValueError("filepath must be a non-empty string")
    columns = _validate_int(columns, "columns", minimum=1)
    out_path = os.path.abspath(os.path.expanduser(filepath.strip()))
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    loaded = []
    try:
        for path in paths:
            image = _load_image_file(path, "image_paths entry")
            width, height = int(image.size[0]), int(image.size[1])
            if width < 1 or height < 1:
                raise ValueError(f"Image '{path}' has invalid size {width}x{height}")
            if width > _MAX_SHEET_SOURCE_RES or height > _MAX_SHEET_SOURCE_RES:
                raise ValueError(
                    f"Image '{path}' is {width}x{height}; sources must be "
                    f"<= {_MAX_SHEET_SOURCE_RES}x{_MAX_SHEET_SOURCE_RES} "
                    "to bound memory"
                )
            loaded.append((image, width, height))

        count = len(loaded)
        columns = min(columns, count)
        rows = math.ceil(count / columns)
        cell_w = max(width for _, width, _ in loaded)
        cell_h = max(height for _, _, height in loaded)
        sheet_w = cell_w * columns
        sheet_h = cell_h * rows
        if sheet_w > _MAX_SHEET_RES or sheet_h > _MAX_SHEET_RES:
            raise ValueError(
                f"Contact sheet {sheet_w}x{sheet_h} exceeds the "
                f"{_MAX_SHEET_RES}x{_MAX_SHEET_RES} limit; use fewer or "
                "smaller images"
            )

        sheet = [0.0] * (sheet_w * sheet_h * 4)
        for index, (image, width, height) in enumerate(loaded):
            src = list(image.pixels[:])
            if len(src) != width * height * 4:
                raise ValueError(
                    f"Image '{paths[index]}' pixels do not match its "
                    f"{width}x{height} dimensions"
                )
            row = index // columns
            col = index % columns
            # First row goes at the top of the sheet.
            y0 = sheet_h - (row + 1) * cell_h
            x0 = col * cell_w
            for y in range(height):
                s = y * width * 4
                d = ((y0 + y) * sheet_w + x0) * 4
                sheet[d:d + width * 4] = src[s:s + width * 4]

        name = os.path.splitext(os.path.basename(out_path))[0] or "ContactSheet"
        sheet_image = bpy.data.images.new(name, sheet_w, sheet_h, alpha=True)
        try:
            sheet_image.pixels.foreach_set(sheet)
        except (AttributeError, RuntimeError, TypeError):
            sheet_image.pixels[:] = sheet
        sheet_image.update()
        sheet_image.file_format = "PNG"
        sheet_image.filepath_raw = out_path
        sheet_image.save()
        sheet_name = sheet_image.name
    finally:
        for image, _, _ in loaded:
            _unload_image(image)

    if not os.path.isfile(out_path):
        return {
            "success": False,
            "filepath": out_path,
            "error": f"Contact sheet was not written to '{out_path}'",
        }
    return {
        "success": True,
        "filepath": out_path,
        "image": sheet_name,
        "count": len(paths),
        "columns": columns,
        "rows": rows,
        "cell": [cell_w, cell_h],
        "dimensions": [sheet_w, sheet_h],
        "file_size_bytes": os.path.getsize(out_path),
    }


def create_studio_backdrop(server, name="Backdrop", width=6.0, depth=4.0,
                           height=3.0,
                           color=(0.5, 0.5, 0.5, 1.0)) -> dict:
    """Create a curved cyclorama studio backdrop grounded at Z=0."""
    name = _validate_name(name)
    width = _validate_float(width, "width", minimum=0.01, maximum=100.0)
    depth = _validate_float(depth, "depth", minimum=0.01, maximum=100.0)
    height = _validate_float(height, "height", minimum=0.01, maximum=100.0)
    rgba = _validate_color(color, "color")

    existing = bpy.data.objects.get(name)
    if existing is not None:
        if existing.type != "MESH":
            raise ValueError(f"Object '{name}' exists and is not a mesh")
        old_data = existing.data
        bpy.data.objects.remove(existing, do_unlink=True)
        try:
            if old_data is not None and old_data.users == 0:
                bpy.data.meshes.remove(old_data)
        except (AttributeError, RuntimeError):
            pass

    front_y = -depth * 0.5
    back_y = depth * 0.5
    radius = min(1.0, depth * 0.25, height * 0.5)
    radius = max(radius, min(depth * 0.25, height * 0.5, 0.5))
    if radius >= height:
        radius = height * 0.5
    if back_y - radius <= front_y:
        radius = max((back_y - front_y) * 0.25, 1e-4)

    profile = []
    floor_segments, curve_segments, wall_segments = 4, 8, 3
    curve_start = back_y - radius
    for i in range(floor_segments + 1):
        t = i / floor_segments
        profile.append((front_y + t * (curve_start - front_y), 0.0))
    for i in range(1, curve_segments + 1):
        angle = (i / curve_segments) * (math.pi * 0.5)
        profile.append((
            curve_start + radius * math.sin(angle),
            radius * (1.0 - math.cos(angle)),
        ))
    for i in range(1, wall_segments + 1):
        t = i / wall_segments
        profile.append((back_y, radius + t * (height - radius)))

    mesh = bpy.data.meshes.new(name)
    left_x, right_x = -width * 0.5, width * 0.5
    bm = bmesh.new()
    try:
        left_verts, right_verts = [], []
        for y, z in profile:
            left_verts.append(bm.verts.new((left_x, y, z)))
            right_verts.append(bm.verts.new((right_x, y, z)))
        bm.verts.ensure_lookup_table()
        for i in range(len(profile) - 1):
            bm.faces.new((
                left_verts[i], right_verts[i],
                right_verts[i + 1], left_verts[i + 1],
            ))
        bm.normal_update()
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.update()

    material_name = f"{obj.name}_Material"
    material = bpy.data.materials.get(material_name)
    if material is None:
        material = bpy.data.materials.new(material_name)
    material.use_nodes = True
    tree = material.node_tree
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        for node in list(tree.nodes):
            tree.nodes.remove(node)
        output = tree.nodes.new(type="ShaderNodeOutputMaterial")
        output.location = (300.0, 0.0)
        bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
        bsdf.location = (0.0, 0.0)
        tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    if "Base Color" in bsdf.inputs:
        bsdf.inputs["Base Color"].default_value = (
            rgba[0], rgba[1], rgba[2], rgba[3],
        )
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.9
    if mesh.materials:
        mesh.materials[0] = material
    else:
        mesh.materials.append(material)

    low_z = min(
        (obj.matrix_world @ Vector(corner))[2] for corner in obj.bound_box
    )
    return {
        "success": True,
        "name": obj.name,
        "width": width,
        "depth": depth,
        "height": height,
        "color": [round(c, 6) for c in rgba],
        "vertices": len(mesh.vertices),
        "faces": len(mesh.polygons),
        "material": material.name,
        "grounded": low_z >= -1e-6,
        "low_point_z": round(low_z, 6),
    }


def setup_compositor_glare(server, threshold=1.0, size=6,
                           mix=0.0) -> dict:
    """Enable the compositor and wire a Glare node after Render Layers."""
    threshold = _validate_float(threshold, "threshold", minimum=0.0)
    size = _validate_int(size, "size", minimum=0, maximum=_MAX_GLARE_SIZE)
    mix = _validate_float(mix, "mix", minimum=-1.0, maximum=1.0)

    scene = bpy.context.scene
    _set_if_exists(scene.render, "use_compositing", True)
    _set_if_exists(scene, "use_nodes", True)
    tree = getattr(scene, "node_tree", None)
    if tree is None:
        tree = getattr(scene, "compositing_node_group", None)
        if tree is None:
            try:
                tree = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
                scene.compositing_node_group = tree
            except Exception as exc:
                raise ValueError(f"Compositor node tree is not available: {exc}")
    if tree is None:
        raise ValueError("Compositor node tree is not available")

    layers = next((n for n in tree.nodes if n.type == "R_LAYERS"), None)
    if layers is None:
        layers = tree.nodes.new(type="CompositorNodeRLayers")
        layers.location = (-400.0, 0.0)
    composite = next(
        (n for n in tree.nodes if n.type in {"COMPOSITE", "GROUP_OUTPUT"}), None
    )
    if composite is None:
        try:
            composite = tree.nodes.new(type="CompositorNodeComposite")
        except (RuntimeError, TypeError):
            interface = getattr(tree, "interface", None)
            if interface is not None and not any(
                socket.name == "Image" for socket in interface.items_tree
            ):
                interface.new_socket(
                    name="Image", in_out="OUTPUT", socket_type="NodeSocketColor"
                )
            composite = tree.nodes.new(type="NodeGroupOutput")
        composite.location = (400.0, 0.0)
    glare = next((n for n in tree.nodes if n.type == "GLARE"), None)
    if glare is None:
        glare = tree.nodes.new(type="CompositorNodeGlare")
        glare.location = (0.0, 0.0)

    if hasattr(glare, "glare_type"):
        try:
            glare.glare_type = "FOG_GLOW"
        except (TypeError, ValueError, AttributeError):
            try:
                glare.glare_type = "BLOOM"
            except (TypeError, ValueError, AttributeError):
                pass
    _set_if_exists(glare, "threshold", float(threshold))
    if hasattr(glare, "size"):
        try:
            glare.size = int(size)
        except (TypeError, ValueError, AttributeError):
            pass
    _set_if_exists(glare, "mix", float(mix))

    linked = False
    try:
        if ("Image" in layers.outputs and "Image" in glare.inputs
                and "Image" in glare.outputs and "Image" in composite.inputs):
            already = any(
                link.from_node == layers and link.to_node == glare
                for link in tree.links
            )
            if not already:
                tree.links.new(layers.outputs["Image"], glare.inputs["Image"])
            already = any(
                link.from_node == glare and link.to_node == composite
                for link in tree.links
            )
            if not already:
                tree.links.new(glare.outputs["Image"], composite.inputs["Image"])
            linked = True
    except (AttributeError, RuntimeError, ValueError):
        linked = False

    return {
        "success": True,
        "node": glare.name,
        "glare_type": getattr(glare, "glare_type", None),
        "threshold": float(getattr(glare, "threshold", threshold)),
        "size": int(getattr(glare, "size", size)),
        "mix": float(getattr(glare, "mix", mix)),
        "linked": linked,
    }


def validate_render(server, filepath, min_width=1,
                    min_height=1) -> dict:
    """Check that a rendered file exists and meets minimum dimensions."""
    if not isinstance(filepath, str) or not filepath.strip():
        raise ValueError("filepath must be a non-empty string")
    path = os.path.abspath(os.path.expanduser(filepath.strip()))
    if not os.path.isfile(path):
        raise ValueError(f"filepath does not exist: '{path}'")
    min_width = _validate_int(min_width, "min_width", minimum=1)
    min_height = _validate_int(min_height, "min_height", minimum=1)

    image = _load_image_file(path, "filepath")
    try:
        width, height = int(image.size[0]), int(image.size[1])
    finally:
        _unload_image(image)

    valid = width >= min_width and height >= min_height
    if not valid:
        return {
            "success": False,
            "valid": False,
            "filepath": path,
            "width": width,
            "height": height,
            "min_width": min_width,
            "min_height": min_height,
            "file_size_bytes": os.path.getsize(path),
            "error": (
                f"Render '{path}' is {width}x{height}, "
                f"below minimum {min_width}x{min_height}"
            ),
        }
    return {
        "success": True,
        "valid": True,
        "filepath": path,
        "width": width,
        "height": height,
        "min_width": min_width,
        "min_height": min_height,
        "file_size_bytes": os.path.getsize(path),
    }


def compare_renders(server, image_a, image_b) -> dict:
    """Compare two renders pixel by pixel and report the difference."""
    img_a = _load_image_file(image_a, "image_a")
    try:
        img_b = _load_image_file(image_b, "image_b")
        try:
            width_a, height_a = int(img_a.size[0]), int(img_a.size[1])
            width_b, height_b = int(img_b.size[0]), int(img_b.size[1])
            for label, w, h in (("image_a", width_a, height_a),
                                ("image_b", width_b, height_b)):
                if w < 1 or h < 1:
                    raise ValueError(f"{label} has invalid size {w}x{h}")
                if w > _MAX_COMPARE_RES or h > _MAX_COMPARE_RES:
                    raise ValueError(
                        f"{label} is {w}x{h}; images must be "
                        f"<= {_MAX_COMPARE_RES}x{_MAX_COMPARE_RES} "
                        "to bound memory"
                    )
            if (width_a, height_a) != (width_b, height_b):
                raise ValueError(
                    f"Image sizes differ: image_a is {width_a}x{height_a}, "
                    f"image_b is {width_b}x{height_b}"
                )
            pixels_a = list(img_a.pixels[:])
            pixels_b = list(img_b.pixels[:])
            expected = width_a * height_a * 4
            if len(pixels_a) != expected or len(pixels_b) != expected:
                raise ValueError(
                    "Image pixels do not match their dimensions "
                    f"({width_a}x{height_a})"
                )
            total = 0.0
            peak = 0.0
            for a, b in zip(pixels_a, pixels_b):
                diff = abs(a - b)
                total += diff
                if diff > peak:
                    peak = diff
            mean_abs = total / expected if expected else 0.0
        finally:
            _unload_image(img_b)
    finally:
        _unload_image(img_a)

    return {
        "success": True,
        "width": width_a,
        "height": height_a,
        "pixel_count": width_a * height_a,
        "mean_absolute_difference": mean_abs,
        "max_channel_difference": peak,
        "identical": peak == 0.0,
    }
