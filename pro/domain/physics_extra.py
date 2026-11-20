"""Extra physics tools: force fields, rigid body chains, cloth presets,
fluid domains and inflows, collision objects, baking and validation.

Runs on Blender's main thread. Uses only ``bpy``, ``mathutils`` and the
standard library. Attribute names that differ between Blender versions
are set through guarded helpers. Compatible with Blender 4.5 LTS and
5.2 LTS.
"""

import bpy
from mathutils import Vector

_VALID_FIELD_TYPES = ("WIND", "VORTEX", "TURBULENCE", "DRAG", "GRAVITY")
# Blender has no GRAVITY force field type; emulate it with a FORCE field.
_FIELD_TYPE_MAP = {
    "WIND": "WIND",
    "VORTEX": "VORTEX",
    "TURBULENCE": "TURBULENCE",
    "DRAG": "DRAG",
    "GRAVITY": "FORCE",
}

_CLOTH_PRESETS = {
    "silk": {"mass": 0.15, "air_damping": 1.0, "structural": 5.0},
    "cotton": {"mass": 0.30, "air_damping": 1.0, "structural": 15.0},
    "leather": {"mass": 0.80, "air_damping": 0.5, "structural": 80.0},
    "wool": {"mass": 0.50, "air_damping": 5.0, "structural": 25.0},
}

_MAX_BAKE_FRAME_END = 250
_MAX_DOMAIN_RESOLUTION = 512


def _require_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _require_object(object_name, label="object_name"):
    clean = _require_name(object_name, label)
    obj = bpy.data.objects.get(clean)
    if obj is None:
        raise ValueError(f"Object '{clean}' not found")
    return obj


def _require_float(value, label, minimum=None, maximum=None):
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


def _require_int(value, label, minimum=None, maximum=None):
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
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {number})")
    return number


def _require_vector3(value, label):
    try:
        items = [float(item) for item in value]
    except (TypeError, ValueError):
        raise ValueError(
            f"{label} must be a sequence of 3 numbers (got {value!r})"
        ) from None
    if len(items) != 3:
        raise ValueError(
            f"{label} must be a sequence of 3 numbers (got {value!r})"
        )
    if any(item != item or item in (float("inf"), float("-inf")) for item in items):
        raise ValueError(f"{label} must hold finite numbers (got {value!r})")
    return items


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


def _link_object(obj):
    collection = bpy.context.scene.collection
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    return collection.name


def _unit_cube_mesh(mesh_name):
    verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5),
        (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5),
        (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5),
        (0, 4, 5, 1), (1, 5, 6, 2),
        (2, 6, 7, 3), (3, 7, 4, 0),
    ]
    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def _fluid_modifier(obj, fluid_type):
    for modifier in obj.modifiers:
        if modifier.type == "FLUID" and getattr(
            modifier, "fluid_type", None
        ) == fluid_type:
            return modifier, False
    modifier = obj.modifiers.new(
        name="FluidDomain" if fluid_type == "DOMAIN" else "FluidFlow",
        type="FLUID",
    )
    if hasattr(modifier, "fluid_type"):
        modifier.fluid_type = fluid_type
    return modifier, True


def _baked_cache_labels(obj):
    labels = []
    try:
        modifiers = list(obj.modifiers)
    except (AttributeError, ReferenceError):
        return labels
    for modifier in modifiers:
        try:
            cache = getattr(modifier, "point_cache", None)
            baked = bool(getattr(cache, "is_baked", False)) if cache else False
        except (AttributeError, ReferenceError):
            continue
        if baked:
            labels.append(f"{obj.name}/{modifier.name}")
    try:
        systems = list(getattr(obj, "particle_systems", None) or [])
    except (AttributeError, ReferenceError):
        systems = []
    for system in systems:
        try:
            cache = getattr(system, "point_cache", None)
            baked = bool(getattr(cache, "is_baked", False)) if cache else False
            label = getattr(system, "name", "particles")
        except (AttributeError, ReferenceError):
            continue
        if baked:
            labels.append(f"{obj.name}/{label}")
    return labels


def add_force_field(server, name="Wind", field_type="WIND", strength=1.0,
                    location=(0.0, 0.0, 0.0)) -> dict:
    """Create an empty force field using Blender's effector operator."""
    _ = server
    clean_name = _require_name(name)
    if not isinstance(field_type, str):
        raise ValueError(
            f"field_type must be one of {list(_VALID_FIELD_TYPES)} "
            f"(got {field_type!r})"
        )
    key = field_type.strip().upper()
    if key not in _VALID_FIELD_TYPES:
        raise ValueError(
            f"field_type must be one of {list(_VALID_FIELD_TYPES)} "
            f"(got {field_type!r})"
        )
    strength = _require_float(strength, "strength")
    loc = _require_vector3(location, "location")
    applied = _FIELD_TYPE_MAP[key]

    try:
        bpy.ops.object.effector_add(type=applied, location=loc)
    except (RuntimeError, TypeError) as exc:
        raise ValueError(f"Could not create force field '{key}': {exc}") from None
    obj = bpy.context.object
    if obj is None:
        raise ValueError(f"Could not create force field '{key}'")
    obj.name = clean_name
    field = getattr(obj, "field", None)
    if field is None:
        raise ValueError(f"Object '{obj.name}' cannot host a force field")
    field.strength = strength
    bpy.context.view_layer.update()
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "field_type": key,
        "applied_type": str(getattr(field, "type", applied)),
        "strength": float(getattr(field, "strength", strength)),
        "location": [round(c, 6) for c in loc],
        "dimensions": [0.0, 0.0, 0.0],
    }


def create_rigid_body_chain(server, object_names, mass=1.0) -> dict:
    """Add ACTIVE rigid bodies with the given mass to each mesh object."""
    _ = server
    if isinstance(object_names, str) or not isinstance(object_names, (list, tuple)):
        raise ValueError("object_names must be a non-empty list of object names")
    if len(object_names) == 0:
        raise ValueError("object_names must be a non-empty list of object names")
    mass = _require_float(mass, "mass", minimum=0.001)

    targets = []
    for entry in object_names:
        obj = _require_object(entry, "object_names entry")
        if obj.type != "MESH":
            raise ValueError(
                f"Rigid bodies need MESH objects "
                f"(got '{obj.name}' of type {obj.type})"
            )
        targets.append(obj)

    scene = bpy.context.scene
    if scene.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()

    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    previous_selected = [o for o in bpy.context.selected_objects]
    bpy.ops.object.select_all(action="DESELECT")
    try:
        for obj in targets:
            obj.select_set(True)
            view_layer.objects.active = obj
            if obj.rigid_body is None:
                bpy.ops.rigidbody.object_add()
            obj.rigid_body.type = "ACTIVE"
            obj.rigid_body.mass = mass
    finally:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in previous_selected:
            try:
                obj.select_set(True)
            except ReferenceError:
                continue
        view_layer.objects.active = previous_active

    return {
        "success": True,
        "count": len(targets),
        "objects": [obj.name for obj in targets],
        "body_type": "ACTIVE",
        "mass": mass,
    }


def create_cloth_preset(server, object_name, preset="silk") -> dict:
    """Add a CLOTH modifier tuned to a fabric preset."""
    _ = server
    obj = _require_object(object_name)
    if obj.type != "MESH":
        raise ValueError(
            f"Cloth needs a MESH object (got '{obj.name}' of type {obj.type})"
        )
    if not isinstance(preset, str):
        raise ValueError(
            f"preset must be one of {sorted(_CLOTH_PRESETS)} (got {preset!r})"
        )
    key = preset.strip().lower()
    if key not in _CLOTH_PRESETS:
        raise ValueError(
            f"Unknown cloth preset '{preset}'. "
            f"Expected one of {sorted(_CLOTH_PRESETS)}"
        )
    values = _CLOTH_PRESETS[key]

    modifier = obj.modifiers.new(name="Cloth", type="CLOTH")
    settings = modifier.settings
    _set_if_exists(settings, "mass", values["mass"])
    air_attr = _set_first_existing(settings, ("air_damping",), values["air_damping"])
    structural_attr = _set_first_existing(
        settings,
        ("structural_stiffness", "tension_stiffness", "tensile_stiffness"),
        values["structural"],
    )

    return {
        "success": True,
        "object": obj.name,
        "modifier": modifier.name,
        "modifier_type": modifier.type,
        "preset": key,
        "mass": values["mass"],
        "air_damping": values["air_damping"],
        "structural": values["structural"],
        "air_damping_attr": air_attr,
        "structural_attr": structural_attr,
    }


def create_fluid_domain(server, domain_name, size=(2.0, 2.0, 2.0),
                        resolution=32) -> dict:
    """Create or configure a FLUID DOMAIN cube with resolution and size."""
    _ = server
    clean_name = _require_name(domain_name, "domain_name")
    dims = _require_vector3(size, "size")
    if any(item <= 0.0 for item in dims):
        raise ValueError(f"size components must be > 0 (got {size!r})")
    resolution = _require_int(
        resolution, "resolution", minimum=1, maximum=_MAX_DOMAIN_RESOLUTION
    )

    obj = bpy.data.objects.get(clean_name)
    created = obj is None
    if created:
        mesh = _unit_cube_mesh(clean_name + "Mesh")
        obj = bpy.data.objects.new(clean_name, mesh)
        _link_object(obj)
    elif obj.type != "MESH":
        raise ValueError(
            f"Fluid domain needs a MESH object "
            f"(got '{obj.name}' of type {obj.type})"
        )

    bpy.context.view_layer.update()
    obj.dimensions = Vector(dims)
    bpy.context.view_layer.update()

    modifier, _ = _fluid_modifier(obj, "DOMAIN")
    settings = getattr(modifier, "domain_settings", None)
    domain_type_attr = _set_if_exists(settings, "domain_type", "LIQUID")
    resolution_attr = _set_first_existing(
        settings, ("resolution_max", "resolution"), resolution
    )

    bpy.context.view_layer.update()
    return {
        "success": True,
        "object": obj.name,
        "domain": obj.name,
        "modifier": modifier.name,
        "modifier_type": modifier.type,
        "created": created,
        "size": [round(c, 6) for c in dims],
        "dimensions": [round(abs(c), 6) for c in obj.dimensions],
        "resolution": resolution,
        "resolution_attr": resolution_attr,
        "domain_type": str(
            getattr(settings, "domain_type", "LIQUID")
        ) if settings is not None else None,
        "domain_type_attr": "domain_type" if domain_type_attr else None,
    }


def create_fluid_inflow(server, object_name, domain_name,
                        velocity=(0.0, 0.0, -1.0)) -> dict:
    """Add a FLUID INFLOW modifier pointing at a fluid domain object."""
    _ = server
    flow_obj = _require_object(object_name)
    if flow_obj.type != "MESH":
        raise ValueError(
            f"Fluid inflow needs a MESH object "
            f"(got '{flow_obj.name}' of type {flow_obj.type})"
        )
    domain_obj = _require_object(domain_name, "domain_name")
    has_domain = any(
        modifier.type == "FLUID"
        and getattr(modifier, "fluid_type", None) == "DOMAIN"
        for modifier in domain_obj.modifiers
    )
    if not has_domain:
        raise ValueError(
            f"Object '{domain_obj.name}' is not a fluid domain "
            f"(no FLUID DOMAIN modifier)"
        )
    vel = _require_vector3(velocity, "velocity")

    modifier, _ = _fluid_modifier(flow_obj, "FLOW")
    flow = getattr(modifier, "flow_settings", None)
    behavior_attr = _set_first_existing(flow, ("flow_behavior",), "INFLOW")
    flow_type_attr = _set_first_existing(flow, ("flow_type",), "LIQUID")
    domain_attr = _set_first_existing(flow, ("domain_object",), domain_obj)
    _set_if_exists(flow, "use_initial_velocity", True)
    velocity_attr = _set_first_existing(
        flow,
        ("initial_velocity", "inflow_velocity", "velocity"),
        Vector(vel),
    )

    return {
        "success": True,
        "object": flow_obj.name,
        "modifier": modifier.name,
        "modifier_type": modifier.type,
        "domain": domain_obj.name,
        "velocity": [round(c, 6) for c in vel],
        "velocity_attr": velocity_attr,
        "behavior_attr": behavior_attr,
        "flow_type_attr": flow_type_attr,
        "domain_attr": domain_attr,
    }


def create_collision_object(server, object_name,
                            thickness=0.02) -> dict:
    """Add a COLLISION modifier with the given thickness."""
    _ = server
    obj = _require_object(object_name)
    thickness = _require_float(thickness, "thickness", minimum=0.0)

    modifier = obj.modifiers.new(name="Collision", type="COLLISION")
    settings = getattr(modifier, "settings", None)
    applied = None
    for attr in ("thickness_outer", "thickness"):
        if _set_if_exists(settings, attr, thickness):
            applied = attr
            break
    _set_if_exists(settings, "thickness_inner", 0.0)

    return {
        "success": True,
        "object": obj.name,
        "modifier": modifier.name,
        "modifier_type": modifier.type,
        "thickness": thickness,
        "thickness_attr": applied,
    }


def bake_physics(server, frame_end=60) -> dict:
    """Set the frame range and bake all point caches."""
    _ = server
    frame_end = _require_int(frame_end, "frame_end", minimum=1)
    bounded = min(frame_end, _MAX_BAKE_FRAME_END)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = bounded

    try:
        bpy.ops.ptcache.bake_all(bake=True)
    except Exception as exc:
        return {
            "success": False,
            "frame_start": scene.frame_start,
            "frame_end": bounded,
            "requested_frame_end": frame_end,
            "baked": False,
            "error": str(exc),
        }

    baked = []
    for obj in scene.objects:
        baked.extend(_baked_cache_labels(obj))
    return {
        "success": True,
        "frame_start": scene.frame_start,
        "frame_end": bounded,
        "requested_frame_end": frame_end,
        "bounded": bounded != frame_end,
        "baked": True,
        "baked_caches": baked,
        "baked_cache_count": len(baked),
    }


def validate_physics(server, object_name=None) -> dict:
    """List rigid bodies, cloth/fluid/collision modifiers and caches."""
    _ = server
    if object_name is None:
        targets = list(bpy.context.scene.objects)
        scope = "scene"
    else:
        targets = [_require_object(object_name)]
        scope = targets[0].name

    rigid_bodies = []
    cloth_objects = []
    fluid_domains = []
    fluid_flows = []
    fluid_objects = []
    collision_objects = []
    baked_caches = []
    for obj in targets:
        try:
            has_rigid_body = getattr(obj, "rigid_body", None) is not None
            modifiers = list(obj.modifiers)
        except (AttributeError, ReferenceError):
            continue
        if has_rigid_body:
            rigid_bodies.append(obj.name)
        for modifier in modifiers:
            if modifier.type == "CLOTH":
                cloth_objects.append(f"{obj.name}/{modifier.name}")
            elif modifier.type == "COLLISION":
                collision_objects.append(f"{obj.name}/{modifier.name}")
            elif modifier.type == "FLUID":
                fluid_objects.append(f"{obj.name}/{modifier.name}")
                if getattr(modifier, "fluid_type", None) == "DOMAIN":
                    fluid_domains.append(f"{obj.name}/{modifier.name}")
                elif getattr(modifier, "fluid_type", None) == "FLOW":
                    fluid_flows.append(f"{obj.name}/{modifier.name}")
        baked_caches.extend(_baked_cache_labels(obj))

    issues = []
    if fluid_flows and not fluid_domains:
        issues.append(
            "Fluid FLOW objects exist but no fluid DOMAIN was found "
            f"in scope '{scope}'"
        )

    return {
        "success": True,
        "scope": scope,
        "object": None if object_name is None else targets[0].name,
        "rigid_bodies": rigid_bodies,
        "rigid_body_count": len(rigid_bodies),
        "cloth": cloth_objects,
        "cloth_count": len(cloth_objects),
        "fluid": fluid_objects,
        "fluid_count": len(fluid_objects),
        "fluid_domains": fluid_domains,
        "fluid_flows": fluid_flows,
        "collision": collision_objects,
        "collision_count": len(collision_objects),
        "baked_caches": baked_caches,
        "baked_cache_count": len(baked_caches),
        "issues": issues,
        "passed": len(issues) == 0,
    }
