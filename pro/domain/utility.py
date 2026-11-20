"""Project info and health diagnostics (read-only).

Runs on Blender's main thread. Uses only ``bpy`` and the standard library.
Both functions are read-only: they never create, modify or delete data.
Compatible with Blender 4.5 LTS and 5.2 LTS.
"""

import sys
import threading

import bpy


def _addon_version():
    """Best-effort add-on version from registered add-ons, else None."""
    try:
        preferences = bpy.context.preferences
    except (AttributeError, RuntimeError):
        return None
    try:
        addons = preferences.addons
    except (AttributeError, RuntimeError):
        return None
    for addon in addons:
        module_name = str(getattr(addon, "module", "") or "")
        if "blender_mcp" not in module_name.lower():
            continue
        info = getattr(sys.modules.get(module_name, None), "bl_info", None)
        if isinstance(info, dict):
            version = info.get("version")
            if isinstance(version, (list, tuple)):
                return [int(part) for part in version]
    return None


def _domain_packs():
    """Best-effort domain pack names from the loaded domain package."""
    module = sys.modules.get("blender_mcp_domain")
    packs = getattr(module, "PACKS", None)
    if isinstance(packs, dict):
        return sorted(str(key) for key in packs)
    return None


def _memory_rss_bytes():
    """Best-effort resident memory in bytes, else None (read-only)."""
    try:
        import resource

        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    except (ImportError, AttributeError, OSError, ValueError):
        return None


def project_info(server) -> dict:
    """Report Blender version, scene stats, units, engine and file path."""
    _ = server
    try:
        version_tuple = tuple(int(part) for part in bpy.app.version)
    except (AttributeError, TypeError, ValueError):
        version_tuple = []
    try:
        version_string = str(bpy.app.version_string)
    except (AttributeError, RuntimeError):
        version_string = ".".join(str(part) for part in version_tuple)

    try:
        scene = bpy.context.scene
    except (AttributeError, RuntimeError):
        scene = None
    scene_name = str(getattr(scene, "name", "")) if scene is not None else ""

    object_count = len(bpy.data.objects)
    type_counts = {}
    for obj in bpy.data.objects:
        key = str(getattr(obj, "type", "UNKNOWN"))
        type_counts[key] = type_counts.get(key, 0) + 1

    total_vertices = 0
    total_polygons = 0
    for mesh in bpy.data.meshes:
        try:
            total_vertices += int(len(mesh.vertices))
            total_polygons += int(len(mesh.polygons))
        except (AttributeError, RuntimeError, TypeError):
            continue

    units = {}
    render_engine = ""
    if scene is not None:
        try:
            settings = scene.unit_settings
            units = {
                "system": str(getattr(settings, "system", "")),
                "scale_length": float(getattr(settings, "scale_length", 1.0)),
                "length_unit": str(getattr(settings, "length_unit", "")),
            }
        except (AttributeError, RuntimeError, TypeError, ValueError):
            units = {}
        try:
            render_engine = str(scene.render.engine)
        except (AttributeError, RuntimeError):
            render_engine = ""

    try:
        filepath = str(bpy.data.filepath or "")
    except (AttributeError, RuntimeError):
        filepath = ""

    pack_names = _domain_packs()

    return {
        "success": True,
        "blender_version": list(version_tuple),
        "blender_version_string": version_string,
        "addon_version": _addon_version(),
        "scene": scene_name,
        "object_count": int(object_count),
        "objects_by_type": type_counts,
        "mesh_count": int(len(bpy.data.meshes)),
        "material_count": int(len(bpy.data.materials)),
        "image_count": int(len(bpy.data.images)),
        "units": units,
        "render_engine": render_engine,
        "total_vertices": int(total_vertices),
        "total_polygons": int(total_polygons),
        "filepath": filepath,
        "domain_pack_count": len(pack_names) if pack_names is not None else None,
        "domain_packs": pack_names,
    }


def health_check(server) -> dict:
    """Run read-only sanity checks on context, thread and runtime."""
    checks = []

    def _record(name, passed, detail=""):
        checks.append({"name": name, "passed": bool(passed), "detail": str(detail)})

    try:
        context = bpy.context
    except (AttributeError, RuntimeError) as exc:
        context = None
        _record("bpy_context", False, f"bpy.context unavailable: {exc}.")
    if context is not None:
        _record("bpy_context", True, "bpy.context is available.")

    scene = None
    if context is not None:
        try:
            scene = context.scene
        except (AttributeError, RuntimeError) as exc:
            _record("scene", False, f"Scene lookup failed: {exc}.")
    if scene is not None:
        _record("scene", True, f"Active scene is '{scene.name}'.")
    elif context is not None and not any(item["name"] == "scene" for item in checks):
        _record("scene", False, "No active scene.")

    view_layer = None
    if context is not None:
        try:
            view_layer = context.view_layer
        except (AttributeError, RuntimeError) as exc:
            _record("view_layer", False, f"View layer lookup failed: {exc}.")
    if view_layer is not None:
        _record("view_layer", True, "View layer is available.")
    elif context is not None and not any(
        item["name"] == "view_layer" for item in checks
    ):
        _record("view_layer", False, "No active view layer.")

    try:
        is_main = threading.current_thread() is threading.main_thread()
    except RuntimeError as exc:
        is_main = False
        _record("main_thread", False, f"Thread check failed: {exc}.")
    else:
        _record(
            "main_thread",
            is_main,
            "Running on Blender's main thread."
            if is_main
            else "Not on Blender's main thread; bpy access may be unsafe.",
        )

    try:
        background = bool(bpy.app.background)
    except (AttributeError, RuntimeError):
        background = False
    _record(
        "background_mode",
        True,
        "Running headless (background mode)." if background else "Running with UI.",
    )

    addon_ok = server is not None or any(
        "blender_mcp" in str(name).lower() for name in sys.modules
    )
    _record(
        "addon_handle",
        addon_ok,
        "Add-on server handle or module is visible."
        if addon_ok
        else "No add-on server handle or module found.",
    )

    python_version = ""
    try:
        python_version = str(sys.version.split()[0])
    except (AttributeError, IndexError):
        python_version = ""
    _record(
        "python_version",
        bool(python_version),
        f"Python {python_version}." if python_version else "Python version unknown.",
    )

    rss = _memory_rss_bytes()
    _record(
        "memory_estimate",
        True,
        f"Peak RSS ~{rss} bytes." if rss is not None else "Memory estimate unavailable.",
    )

    passed = all(item["passed"] for item in checks)
    return {
        "success": True,
        "passed": passed,
        "background": background,
        "main_thread": is_main,
        "python_version": python_version,
        "memory_rss_bytes": rss,
        "checks": checks,
    }
