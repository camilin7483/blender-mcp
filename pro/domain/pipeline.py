"""Model import/export, LOD chains, image packing and asset manifests.

Runs on Blender's main thread. Uses only ``bpy``, ``bmesh``, ``mathutils``
and the standard library. File paths arrive already resolved by the add-on
wrapper; domain functions read the given input path and write only to the
given output path or directory. All functions validate their inputs, raise
``ValueError`` with a precise message on bad input, and return plain
JSON-serializable dictionaries. Compatible with Blender 4.5 LTS and 5.2 LTS.
"""

import json
import math
import os

import bmesh
import bpy
from mathutils import Vector

_IMPORT_FORMATS = ("FBX", "OBJ", "GLB", "GLTF")
_EXPORT_FORMATS = ("GLB", "GLTF", "FBX", "OBJ")
_IMAGE_FORMATS = {
    "PNG": ("PNG", ".png"),
    "JPEG": ("JPEG", ".jpg"),
    "JPG": ("JPEG", ".jpg"),
    "BMP": ("BMP", ".bmp"),
    "TARGA": ("TARGA", ".tga"),
    "TIFF": ("TIFF", ".tif"),
    "OPEN_EXR": ("OPEN_EXR", ".exr"),
}
_EXTENSION_TO_FORMAT = {
    ".fbx": "FBX",
    ".obj": "OBJ",
    ".glb": "GLB",
    ".gltf": "GLTF",
}
_FORMAT_TO_EXTENSION = {
    "FBX": ".fbx",
    "OBJ": ".obj",
    "GLB": ".glb",
    "GLTF": ".gltf",
}


# ---------------------------------------------------------------------------
# Validation and small helpers
# ---------------------------------------------------------------------------

def _require_non_empty_str(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string (got {value!r}).")
    return value.strip()


def _require_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number (got {value!r}).")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number (got {value!r}).")
    return result


def _require_object(object_name, label="object_name"):
    clean = _require_non_empty_str(object_name, label)
    obj = bpy.data.objects.get(clean)
    if obj is None:
        raise ValueError(f"Object '{clean}' not found.")
    return obj


def _require_mesh_object(obj):
    if obj.type != "MESH":
        raise ValueError(f"Object '{obj.name}' must be a MESH (got {obj.type}).")
    if obj.data is None:
        raise ValueError(f"Object '{obj.name}' has no mesh data.")
    return obj


def _mesh_counts(obj):
    mesh = obj.data
    return int(len(mesh.vertices)), int(len(mesh.polygons))


def _face_count_bmesh(obj):
    """Count faces through bmesh as an independent evaluated-data check."""
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        return int(len(bm.faces))
    finally:
        bm.free()


def _world_dimensions(obj):
    try:
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    except (AttributeError, TypeError, ValueError):
        try:
            return [round(float(axis), 6) for axis in obj.dimensions]
        except (AttributeError, TypeError):
            return [0.0, 0.0, 0.0]
    if not corners:
        return [0.0, 0.0, 0.0]
    mins = [min(corner[i] for corner in corners) for i in range(3)]
    maxs = [max(corner[i] for corner in corners) for i in range(3)]
    return [round(float(maxs[i] - mins[i]), 6) for i in range(3)]


def _set_object_mode():
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except (RuntimeError, TypeError):
        pass


def _deselect_all():
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except (RuntimeError, TypeError):
        for obj in bpy.context.selected_objects:
            obj.select_set(False)


def _snapshot_selection():
    selected = [obj.name for obj in bpy.context.selected_objects]
    active = bpy.context.view_layer.objects.active
    return selected, active.name if active is not None else None


def _restore_selection(selected_names, active_name):
    _deselect_all()
    for name in selected_names:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.select_set(True)
    active = bpy.data.objects.get(active_name) if active_name else None
    if active is not None:
        bpy.context.view_layer.objects.active = active


def _select_single(obj):
    _deselect_all()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _link_to_collection(obj, reference=None):
    collections = getattr(reference, "users_collection", None) if reference else None
    if collections:
        collections[0].objects.link(obj)
        return collections[0].name
    bpy.context.scene.collection.objects.link(obj)
    return bpy.context.scene.collection.name


def _normalize_import_format(value, filepath):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"format must be one of {list(('AUTO',) + _IMPORT_FORMATS)}.")
    key = value.strip().upper()
    if key == "AUTO":
        ext = os.path.splitext(filepath)[1].lower()
        detected = _EXTENSION_TO_FORMAT.get(ext)
        if detected is None:
            raise ValueError(
                f"Cannot detect import format from extension '{ext}'. "
                f"Supported extensions: {sorted(_EXTENSION_TO_FORMAT)}."
            )
        return detected
    if key not in _IMPORT_FORMATS:
        raise ValueError(
            f"format must be one of {list(('AUTO',) + _IMPORT_FORMATS)} (got {value!r})."
        )
    return key


def _normalize_export_format(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"format must be one of {list(_EXPORT_FORMATS)} (got {value!r}).")
    key = value.strip().upper()
    if key not in _EXPORT_FORMATS:
        raise ValueError(f"format must be one of {list(_EXPORT_FORMATS)} (got {value!r}).")
    return key


def _run_importer(format_key, path):
    if format_key == "FBX":
        bpy.ops.import_scene.fbx(filepath=path)
    elif format_key == "OBJ":
        # The legacy ``import_scene.obj`` operator was removed in Blender 4.x
        # in favour of the new ``wm.obj_import`` operator; support both so
        # the module works on 4.5 LTS and 5.2 LTS.
        if hasattr(bpy.ops.import_scene, "obj"):
            bpy.ops.import_scene.obj(filepath=path)
        else:
            bpy.ops.wm.obj_import(filepath=path)
    elif format_key in ("GLB", "GLTF"):
        bpy.ops.import_scene.gltf(filepath=path)
    else:  # pragma: no cover - guarded by validation
        raise ValueError(f"Unsupported import format '{format_key}'.")


def _run_exporter(format_key, path):
    if format_key == "GLB":
        bpy.ops.export_scene.gltf(
            filepath=path, use_selection=True, export_format="GLB"
        )
    elif format_key == "GLTF":
        bpy.ops.export_scene.gltf(
            filepath=path, use_selection=True, export_format="GLTF_SEPARATE"
        )
    elif format_key == "FBX":
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True)
    elif format_key == "OBJ":
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True)
    else:  # pragma: no cover - guarded by validation
        raise ValueError(f"Unsupported export format '{format_key}'.")


def _selected_mesh_objects():
    return [
        obj for obj in bpy.context.selected_objects
        if obj.type == "MESH" and obj.data is not None
    ]


def _export_single_selected(format_key, path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _run_exporter(format_key, path)
    if not os.path.exists(path):
        raise ValueError(f"Export finished but no file was written to '{path}'.")
    return path, int(os.path.getsize(path))


def _lod_sort_key(name):
    tail = name.rsplit("_LOD", 1)[-1] if "_LOD" in name else name
    digits = "".join(ch for ch in tail if ch.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def _safe_filename(value):
    cleaned = "".join(
        ch if (ch.isalnum() or ch in ("-", "_", ".")) else "_" for ch in value
    ).strip(" .")
    return cleaned or "image"


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------

def import_model(server, filepath, format="AUTO") -> dict:
    """Import a model file and report the new objects and mesh counts."""
    _ = server
    clean_path = _require_non_empty_str(filepath, "filepath")
    path = os.path.abspath(os.path.expanduser(clean_path))
    if not os.path.isfile(path):
        raise ValueError(f"Import file '{path}' does not exist.")
    format_key = _normalize_import_format(format, path)

    before = set(bpy.data.objects)
    try:
        _run_importer(format_key, path)
    except (RuntimeError, TypeError, OSError) as exc:
        raise ValueError(f"Failed to import '{path}' as {format_key}: {exc}.")
    bpy.context.view_layer.update()

    imported = sorted(
        (obj for obj in bpy.data.objects if obj not in before),
        key=lambda obj: obj.name,
    )
    vertex_total = 0
    polygon_total = 0
    details = []
    for obj in imported:
        vertices, polygons = (0, 0)
        if obj.type == "MESH" and obj.data is not None:
            vertices, polygons = _mesh_counts(obj)
        vertex_total += vertices
        polygon_total += polygons
        details.append({
            "name": obj.name,
            "type": obj.type,
            "vertices": vertices,
            "polygons": polygons,
        })
    return {
        "success": True,
        "filepath": path,
        "format": format_key,
        "imported": [obj.name for obj in imported],
        "object_names": [obj.name for obj in imported],
        "object_count": len(imported),
        "vertex_count": vertex_total,
        "polygon_count": polygon_total,
        "objects": details,
    }


def export_selected(server, filepath, format="GLB") -> dict:
    """Export the selected mesh objects to a file, keeping the scene intact."""
    _ = server
    clean_path = _require_non_empty_str(filepath, "filepath")
    path = os.path.abspath(os.path.expanduser(clean_path))
    format_key = _normalize_export_format(format)

    meshes = _selected_mesh_objects()
    if not meshes:
        raise ValueError("No mesh objects selected; select at least one mesh to export.")

    names = sorted(obj.name for obj in meshes)
    try:
        written, size = _export_single_selected(format_key, path)
    except (RuntimeError, TypeError, OSError) as exc:
        raise ValueError(f"Failed to export {names} as {format_key}: {exc}.")
    return {
        "success": True,
        "path": written,
        "filepath": written,
        "bytes": size,
        "file_size_bytes": size,
        "format": format_key,
        "object_count": len(names),
        "objects": names,
        "object_names": names,
    }


def batch_export(server, object_names, directory, format="GLB") -> dict:
    """Export each named object to its own file without altering the scene."""
    _ = server
    if not isinstance(object_names, (list, tuple)) or not object_names:
        raise ValueError("object_names must be a non-empty list of object names.")
    targets = []
    for entry in object_names:
        obj = _require_object(entry)
        _require_mesh_object(obj)
        targets.append(obj)
    clean_dir = _require_non_empty_str(directory, "directory")
    out_dir = os.path.abspath(os.path.expanduser(clean_dir))
    os.makedirs(out_dir, exist_ok=True)
    format_key = _normalize_export_format(format)
    extension = _FORMAT_TO_EXTENSION[format_key]

    selected_names, active_name = _snapshot_selection()
    outputs = []
    try:
        for obj in targets:
            _set_object_mode()
            _select_single(obj)
            path = os.path.join(out_dir, f"{_safe_filename(obj.name)}{extension}")
            try:
                written, size = _export_single_selected(format_key, path)
            except (RuntimeError, TypeError, OSError) as exc:
                raise ValueError(
                    f"Failed to export '{obj.name}' as {format_key}: {exc}."
                )
            outputs.append({
                "object": obj.name,
                "path": written,
                "filepath": written,
                "bytes": size,
                "file_size_bytes": size,
                "format": format_key,
            })
    finally:
        _set_object_mode()
        _restore_selection(selected_names, active_name)
    return {
        "success": True,
        "directory": out_dir,
        "format": format_key,
        "count": len(outputs),
        "object_count": len(outputs),
        "outputs": outputs,
    }


# ---------------------------------------------------------------------------
# LOD chains
# ---------------------------------------------------------------------------

def create_lod_chain(server, object_name, ratios=(1.0, 0.5, 0.25),
                     suffix="_LOD") -> dict:
    """Duplicate a mesh once per ratio, decimating each copy in place."""
    _ = server
    base = _require_mesh_object(_require_object(object_name))
    if not isinstance(ratios, (list, tuple)) or not ratios:
        raise ValueError("ratios must be a non-empty sequence of numbers in (0, 1].")
    clean_ratios = []
    for ratio in ratios:
        value = _require_number(ratio, "ratios entry")
        if not 0.0 < value <= 1.0:
            raise ValueError(f"ratios entries must be in (0, 1] (got {ratio!r}).")
        clean_ratios.append(float(value))
    clean_suffix = _require_non_empty_str(suffix, "suffix")

    _set_object_mode()
    selected_names, active_name = _snapshot_selection()
    lods = []
    try:
        for index, ratio in enumerate(clean_ratios):
            lod_name = f"{base.name}{clean_suffix}{index}"
            existing = bpy.data.objects.get(lod_name)
            if existing is not None:
                data = existing.data
                bpy.data.objects.remove(existing, do_unlink=True)
                if data is not None and getattr(data, "users", 0) == 0:
                    bpy.data.meshes.remove(data)
            clone = base.copy()
            clone.data = base.data.copy()
            clone.name = lod_name
            _link_to_collection(clone, base)
            bpy.context.view_layer.update()
            if ratio < 1.0 - 1e-9:
                modifier = clone.modifiers.new(name="Decimate", type="DECIMATE")
                modifier.ratio = ratio
                _select_single(clone)
                try:
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
                except (RuntimeError, TypeError) as exc:
                    raise ValueError(
                        f"Failed to apply Decimate on '{lod_name}': {exc}."
                    )
            bpy.context.view_layer.update()
            vertices, polygons = _mesh_counts(clone)
            lods.append({
                "name": clone.name,
                "ratio": ratio,
                "vertices": vertices,
                "polygons": polygons,
                "dimensions": _world_dimensions(clone),
                "materials": [
                    slot.name for slot in clone.data.materials if slot is not None
                ],
                "uv_layers": [layer.name for layer in clone.data.uv_layers],
            })
    finally:
        _set_object_mode()
        _restore_selection(selected_names, active_name)

    return {
        "success": True,
        "object": base.name,
        "suffix": clean_suffix,
        "ratios": clean_ratios,
        "lod_names": [entry["name"] for entry in lods],
        "names": [entry["name"] for entry in lods],
        "polygon_counts": [entry["polygons"] for entry in lods],
        "lods": lods,
    }


def validate_lod_chain(server, object_name, suffix="_LOD") -> dict:
    """Check that sibling LODs shrink in polygon count and keep their size."""
    _ = server
    base = _require_mesh_object(_require_object(object_name))
    clean_suffix = _require_non_empty_str(suffix, "suffix")

    prefix = base.name + clean_suffix
    siblings = sorted(
        (
            obj for obj in bpy.data.objects
            if obj.name != base.name
            and obj.name.startswith(prefix)
            and obj.type == "MESH"
            and obj.data is not None
        ),
        key=lambda obj: (_lod_sort_key(obj.name), obj.name),
    )
    failures = []
    if not siblings:
        failures.append(f"No LOD objects starting with '{prefix}' found.")
    counts = [_face_count_bmesh(obj) for obj in siblings]
    for first, second in zip(counts, counts[1:]):
        if not first > second:
            failures.append(
                f"Polygon counts are not strictly decreasing: {counts}."
            )
            break
    base_dims = _world_dimensions(base)
    for obj in siblings:
        lod_dims = _world_dimensions(obj)
        for axis, (low, high) in enumerate(zip(base_dims, lod_dims)):
            if low > 1e-9:
                if abs(high - low) / low > 0.05 + 1e-9:
                    failures.append(
                        f"LOD '{obj.name}' axis {axis} dimension {high} differs "
                        f"from base {low} by more than 5%."
                    )
            elif abs(high - low) > 1e-6:
                failures.append(
                    f"LOD '{obj.name}' axis {axis} dimension {high} differs "
                    f"from degenerate base dimension {low}."
                )
    return {
        "success": True,
        "object": base.name,
        "suffix": clean_suffix,
        "passed": len(failures) == 0,
        "failures": failures,
        "lods": [obj.name for obj in siblings],
        "lod_names": [obj.name for obj in siblings],
        "polygon_counts": counts,
        "base_polygons": _mesh_counts(base)[1],
        "base_dimensions": base_dims,
    }


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def pack_images(server) -> dict:
    """Pack every image that references an external file into the blend file."""
    _ = server
    packed = []
    skipped = []
    for image in bpy.data.images:
        if not image.filepath or not image.filepath.strip():
            continue
        try:
            image.pack()
        except (RuntimeError, TypeError) as exc:
            skipped.append({"image": image.name, "error": str(exc)})
            continue
        packed.append(image.name)
    packed.sort()
    return {
        "success": True,
        "packed": packed,
        "names": list(packed),
        "packed_count": len(packed),
        "count": len(packed),
        "skipped": skipped,
    }


def save_images(server, directory, format="PNG") -> dict:
    """Save every image holding pixel data into a directory."""
    _ = server
    clean_dir = _require_non_empty_str(directory, "directory")
    out_dir = os.path.abspath(os.path.expanduser(clean_dir))
    os.makedirs(out_dir, exist_ok=True)
    if not isinstance(format, str) or not format.strip():
        raise ValueError(f"format must be one of {sorted(_IMAGE_FORMATS)}.")
    format_key = format.strip().upper()
    if format_key not in _IMAGE_FORMATS:
        raise ValueError(
            f"format must be one of {sorted(_IMAGE_FORMATS)} (got {format!r})."
        )
    file_format, extension = _IMAGE_FORMATS[format_key]

    outputs = []
    for image in bpy.data.images:
        try:
            has_data = bool(image.has_data)
        except (AttributeError, RuntimeError):
            has_data = True
        if not has_data:
            continue
        try:
            if image.size[0] <= 0 or image.size[1] <= 0:
                continue
        except (AttributeError, TypeError, IndexError):
            continue
        path = os.path.join(out_dir, f"{_safe_filename(image.name)}{extension}")
        previous = image.file_format
        try:
            image.file_format = file_format
            image.save_render(path)
        except (RuntimeError, TypeError, OSError) as exc:
            raise ValueError(f"Failed to save image '{image.name}': {exc}.")
        finally:
            try:
                image.file_format = previous
            except (TypeError, ValueError):
                pass
        if not os.path.exists(path):
            raise ValueError(
                f"Saving image '{image.name}' produced no file at '{path}'."
            )
        outputs.append({
            "image": image.name,
            "path": path,
            "filepath": path,
            "bytes": int(os.path.getsize(path)),
            "file_size_bytes": int(os.path.getsize(path)),
            "format": format_key,
        })
    outputs.sort(key=lambda entry: entry["image"])
    return {
        "success": True,
        "directory": out_dir,
        "format": format_key,
        "count": len(outputs),
        "outputs": outputs,
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def generate_asset_manifest(server, object_names, filepath) -> dict:
    """Write a JSON manifest describing objects, written atomically."""
    _ = server
    if not isinstance(object_names, (list, tuple)) or not object_names:
        raise ValueError("object_names must be a non-empty list of object names.")
    targets = [_require_object(entry) for entry in object_names]
    clean_path = _require_non_empty_str(filepath, "filepath")
    path = os.path.abspath(os.path.expanduser(clean_path))
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    entries = []
    for obj in targets:
        vertex_count = 0
        polygon_count = 0
        materials = []
        modifiers = []
        if obj.type == "MESH" and obj.data is not None:
            vertex_count, polygon_count = _mesh_counts(obj)
            materials = sorted({
                slot.name for slot in obj.data.materials if slot is not None
            })
        for modifier in getattr(obj, "modifiers", []):
            modifiers.append({"name": modifier.name, "type": modifier.type})
        siblings = sorted(
            other.name for other in bpy.data.objects
            if other.name != obj.name and other.name.startswith(obj.name)
        )
        entries.append({
            "name": obj.name,
            "type": obj.type,
            "dimensions": _world_dimensions(obj),
            "location": [round(float(axis), 6) for axis in obj.location],
            "vertices": vertex_count,
            "vertex_count": vertex_count,
            "polygons": polygon_count,
            "polygon_count": polygon_count,
            "materials": materials,
            "modifiers": modifiers,
            "lod_siblings": siblings,
        })
    manifest = {
        "objects": entries,
        "object_count": len(entries),
        "count": len(entries),
    }
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    except OSError as exc:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise ValueError(f"Failed to write manifest to '{path}': {exc}.")
    return {
        "success": True,
        "path": path,
        "filepath": path,
        "object_count": len(entries),
        "count": len(entries),
        "file_size_bytes": int(os.path.getsize(path)),
        "bytes": int(os.path.getsize(path)),
    }
