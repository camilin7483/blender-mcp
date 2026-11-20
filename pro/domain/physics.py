"""Physics tools: rigid bodies, collision, cloth and simulation baking.

Blender 4.5 LTS and 5.2 LTS compatible. Uses only `bpy` and the
standard library. Attribute names that differ between Blender versions
are set through guarded helpers so the tools degrade cleanly.
"""

import bpy

_VALID_BODY_TYPES = ("ACTIVE", "PASSIVE")
_VALID_COLLISION_SHAPES = (
    "BOX",
    "SPHERE",
    "CAPSULE",
    "CYLINDER",
    "CONE",
    "CONVEX_HULL",
    "MESH",
)


def _validate_object_name(object_name):
    if not isinstance(object_name, str) or not object_name.strip():
        raise ValueError("object_name must be a non-empty string")
    obj = bpy.data.objects.get(object_name.strip())
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")
    return obj


def _validate_float(value, label, minimum=None, maximum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number (got {value!r})")
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{label} must be finite (got {value!r})")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {number})")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {number})")
    return number


def _validate_int(value, label, minimum=None):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if number != float(value):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {number})")
    return number


def _set_if_exists(target, attr, value):
    if target is not None and hasattr(target, attr):
        setattr(target, attr, value)
        return True
    return False


def _set_first_existing(target, candidates, value):
    for attr in candidates:
        if target is not None and hasattr(target, attr):
            setattr(target, attr, value)
            return attr
    return None


def add_rigid_body(server, object_name, body_type="ACTIVE", mass=1.0,
                   friction=0.5, restitution=0.0) -> dict:
    """Add a rigid body to an object via `bpy.ops.rigidbody.object_add()`."""
    obj = _validate_object_name(object_name)
    body_type = str(body_type).upper() if isinstance(body_type, str) else ""
    if body_type not in _VALID_BODY_TYPES:
        raise ValueError(
            f"body_type must be one of {list(_VALID_BODY_TYPES)} (got {body_type!r})"
        )
    mass = _validate_float(mass, "mass", minimum=0.001)
    friction = _validate_float(friction, "friction", minimum=0.0)
    restitution = _validate_float(restitution, "restitution", minimum=0.0, maximum=1.0)

    previous_active = bpy.context.view_layer.objects.active
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        if obj.rigid_body is None:
            bpy.ops.rigidbody.object_add()
    finally:
        bpy.context.view_layer.objects.active = previous_active

    rigid_body = obj.rigid_body
    if rigid_body is None:
        return {
            "success": False,
            "object": obj.name,
            "error": f"Could not add a rigid body to '{obj.name}'",
        }
    rigid_body.type = body_type
    rigid_body.mass = mass
    rigid_body.friction = friction
    rigid_body.restitution = restitution

    return {
        "success": True,
        "object": obj.name,
        "body_type": rigid_body.type,
        "mass": float(rigid_body.mass),
        "friction": float(rigid_body.friction),
        "restitution": float(rigid_body.restitution),
    }


def add_collision(server, object_name, shape="CONVEX_HULL",
                  margin=0.04) -> dict:
    """Add a COLLISION modifier; apply shape/margin to a rigid body if present."""
    obj = _validate_object_name(object_name)
    shape = str(shape).upper() if isinstance(shape, str) else ""
    if shape not in _VALID_COLLISION_SHAPES:
        raise ValueError(
            f"shape must be one of {list(_VALID_COLLISION_SHAPES)} (got {shape!r})"
        )
    margin = _validate_float(margin, "margin", minimum=0.0)

    modifier = obj.modifiers.new(name="Collision", type="COLLISION")
    settings = getattr(modifier, "settings", None)
    applied = []
    for attr in ("thickness_outer", "thickness", "margin"):
        if _set_if_exists(settings, attr, margin):
            applied.append(attr)
            break
    _set_if_exists(settings, "thickness_inner", 0.0)

    # Keep a rigid body on the same object consistent with the requested shape.
    rigid_body = getattr(obj, "rigid_body", None)
    rigid_body_shape = None
    if rigid_body is not None:
        if _set_if_exists(rigid_body, "collision_shape", shape):
            rigid_body_shape = rigid_body.collision_shape
        _set_if_exists(rigid_body, "use_margin", True)
        _set_if_exists(rigid_body, "collision_margin", margin)

    return {
        "success": True,
        "object": obj.name,
        "modifier": modifier.name,
        "modifier_type": modifier.type,
        "shape": shape,
        "margin": margin,
        "modifier_thickness_attr": applied[0] if applied else None,
        "rigid_body_shape": rigid_body_shape,
    }


def add_cloth(server, object_name, quality=5, mass=0.3, tension=15.0,
              bending=0.5) -> dict:
    """Add a CLOTH modifier to a mesh object."""
    obj = _validate_object_name(object_name)
    if obj.type != "MESH":
        raise ValueError(
            f"Cloth needs a MESH object (got '{obj.name}' of type {obj.type})"
        )
    quality = _validate_int(quality, "quality", minimum=1)
    mass = _validate_float(mass, "mass", minimum=0.001)
    tension = _validate_float(tension, "tension", minimum=0.0)
    bending = _validate_float(bending, "bending", minimum=0.0)

    modifier = obj.modifiers.new(name="Cloth", type="CLOTH")
    settings = modifier.settings
    _set_if_exists(settings, "quality", quality)
    _set_if_exists(settings, "mass", mass)
    tension_attr = _set_first_existing(
        settings, ("tension_stiffness", "tensile_stiffness"), tension
    )
    bending_attr = _set_first_existing(settings, ("bending_stiffness",), bending)

    return {
        "success": True,
        "object": obj.name,
        "modifier": modifier.name,
        "modifier_type": modifier.type,
        "quality": quality,
        "mass": mass,
        "tension": tension,
        "bending": bending,
        "tension_attr": tension_attr,
        "bending_attr": bending_attr,
    }


def bake_simulation(server, frame_start=1, frame_end=250) -> dict:
    """Set the scene frame range and bake all point caches."""
    frame_start = _validate_int(frame_start, "frame_start", minimum=0)
    frame_end = _validate_int(frame_end, "frame_end", minimum=0)
    if frame_end < frame_start:
        raise ValueError(
            f"frame_end ({frame_end}) must be >= frame_start ({frame_start})"
        )

    scene = bpy.context.scene
    scene.frame_start = frame_start
    scene.frame_end = frame_end

    try:
        bpy.ops.ptcache.bake_all(bake=True)
    except Exception as exc:
        return {
            "success": False,
            "frame_start": frame_start,
            "frame_end": frame_end,
            "baked": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "baked": True,
    }
