"""Animation FX tools: particle systems, trails and explosive effects.

Runs on Blender's main thread. Uses only ``bpy``, ``bmesh``,
``mathutils`` and the standard library. All functions validate their
inputs, raise ``ValueError`` with a precise message on bad input, and
return plain JSON-serializable dictionaries. Results are deterministic
when a ``seed`` is provided. Compatible with Blender 4.5 LTS and
5.2 LTS. No simulation baking is required by any function here.
"""

import math
import random

import bpy
import bmesh
from mathutils import Vector


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_int(value, label, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer (got {value!r})") from None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer (got {value!r})") from None
    if number != as_float:
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {number})")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {number})")
    return number


def _validate_float(value, label, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number (got {value!r})")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number (got {value!r})") from None
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
        ) from None
    if len(items) != 3 or not all(math.isfinite(item) for item in items):
        raise ValueError(
            f"{label} must be a sequence of 3 finite numbers (got {value!r})"
        )
    return items


def _validate_seed(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"seed must be an integer (got {value!r})")
    return value


def _get_object(object_name):
    if not isinstance(object_name, str) or not object_name.strip():
        raise ValueError("object_name must be a non-empty string")
    obj = bpy.data.objects.get(object_name.strip())
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")
    return obj


# ---------------------------------------------------------------------------
# Blender helpers
# ---------------------------------------------------------------------------

def _link_object(obj):
    collection = bpy.context.scene.collection
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return obj


def _set_socket(node, names, value):
    for candidate in names:
        socket = node.inputs.get(candidate)
        if socket is not None:
            socket.default_value = value
            return True
    return False


def _clear_tree(tree):
    for node in list(tree.nodes):
        tree.nodes.remove(node)


def _emission_material(name, color, strength=10.0):
    """Build a fresh Emission material (stable across Blender versions)."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    _clear_tree(tree)
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300.0, 0.0)
    emission = tree.nodes.new(type="ShaderNodeEmission")
    emission.location = (0.0, 0.0)
    _set_socket(emission, ("Color",), (color[0], color[1], color[2], 1.0))
    _set_socket(emission, ("Strength",), float(strength))
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def _transparent_emission_material(name, color, strength=5.0, mix_factor=0.4):
    """Build an Emission/Transparent mix material for rings and waves."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    _clear_tree(tree)
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (400.0, 0.0)
    mix = tree.nodes.new(type="ShaderNodeMixShader")
    mix.location = (200.0, 0.0)
    _set_socket(mix, ("Fac",), float(mix_factor))
    transparent = tree.nodes.new(type="ShaderNodeBsdfTransparent")
    transparent.location = (-100.0, 100.0)
    emission = tree.nodes.new(type="ShaderNodeEmission")
    emission.location = (-100.0, -100.0)
    _set_socket(emission, ("Color",), (color[0], color[1], color[2], 1.0))
    _set_socket(emission, ("Strength",), float(strength))
    tree.links.new(transparent.outputs["BSDF"], mix.inputs[1])
    tree.links.new(emission.outputs["Emission"], mix.inputs[2])
    tree.links.new(mix.outputs["Shader"], output.inputs["Surface"])
    try:
        material.blend_method = "BLEND"
    except (AttributeError, TypeError):
        pass
    return material


def _volume_material(name, color, density=2.0):
    """Build a volume material, falling back to scatter when needed."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    _clear_tree(tree)
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300.0, 0.0)
    try:
        volume = tree.nodes.new(type="ShaderNodeVolumePrincipled")
        volume.location = (0.0, 0.0)
        _set_socket(volume, ("Color",), (color[0], color[1], color[2], 1.0))
        _set_socket(volume, ("Density",), float(density))
        tree.links.new(volume.outputs["Volume"], output.inputs["Volume"])
        volume_type = "PRINCIPLED_VOLUME"
    except RuntimeError:
        scatter = tree.nodes.new(type="ShaderNodeVolumeScatter")
        scatter.location = (0.0, 0.0)
        _set_socket(scatter, ("Color",), (color[0], color[1], color[2], 1.0))
        _set_socket(scatter, ("Density",), float(density))
        tree.links.new(scatter.outputs["Volume"], output.inputs["Volume"])
        volume_type = "VOLUME_SCATTER"
    return material, volume_type


def _fire_material(name):
    """Build an Emission material tinted by noise (yellow core, red edge)."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    _clear_tree(tree)
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (600.0, 0.0)
    emission = tree.nodes.new(type="ShaderNodeEmission")
    emission.location = (400.0, 0.0)
    _set_socket(emission, ("Strength",), 10.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.location = (200.0, 0.0)
    try:
        stops = ramp.color_ramp.elements
        stops[0].position = 0.25
        stops[0].color = (1.0, 0.85, 0.2, 1.0)
        stops[1].position = 0.75
        stops[1].color = (1.0, 0.25, 0.05, 1.0)
    except (AttributeError, IndexError):
        pass
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.location = (0.0, 0.0)
    _set_socket(noise, ("Scale",), 4.0)
    _set_socket(noise, ("Detail",), 4.0)
    texcoord = tree.nodes.new(type="ShaderNodeTexCoord")
    texcoord.location = (-200.0, 0.0)
    try:
        tree.links.new(
            texcoord.outputs["Object"], noise.inputs["Vector"])
        tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        tree.links.new(ramp.outputs["Color"], emission.inputs["Color"])
        tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    except (KeyError, AttributeError):
        tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def _mesh_object(name, build):
    """Create a mesh object; `build(bm)` fills a fresh bmesh."""
    mesh = bpy.data.meshes.new(name + "Mesh")
    bm = bmesh.new()
    try:
        build(bm)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    return _link_object(obj)


def _attach_material(obj, material):
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)


# ---------------------------------------------------------------------------
# Particle system
# ---------------------------------------------------------------------------


def _torus(bm, major_rad, minor_rad, major_seg=32, minor_seg=10):
    """Create a torus in the XY plane with explicit quads."""
    major_rad = float(major_rad)
    minor_rad = float(minor_rad)
    major_seg = max(int(major_seg), 3)
    minor_seg = max(int(minor_seg), 3)
    rings = []
    for i in range(major_seg):
        theta = 2.0 * math.pi * i / major_seg
        ring = []
        for j in range(minor_seg):
            phi = 2.0 * math.pi * j / minor_seg
            radial = major_rad + minor_rad * math.cos(phi)
            ring.append(bm.verts.new((
                math.cos(theta) * radial,
                math.sin(theta) * radial,
                minor_rad * math.sin(phi),
            )))
        rings.append(ring)
    for i in range(major_seg):
        nxt = (i + 1) % major_seg
        for j in range(minor_seg):
            jn = (j + 1) % minor_seg
            bm.faces.new((rings[i][j], rings[nxt][j], rings[nxt][jn], rings[i][jn]))
    return [vertex for ring in rings for vertex in ring]


def create_particle_system(server, object_name, name="Particles",
                           count=500, lifetime=60) -> dict:
    """Add an emitter particle system with count and lifetime to an object."""
    _ = server
    obj = _get_object(object_name)
    if obj.type != "MESH":
        raise ValueError(
            f"Particle systems need a MESH emitter "
            f"(got '{obj.name}' of type {obj.type})"
        )
    clean_name = _validate_name(name)
    count = _validate_int(count, "count", minimum=1, maximum=100000)
    lifetime = _validate_int(lifetime, "lifetime", minimum=1, maximum=10000)

    modifier = obj.modifiers.new(name=clean_name, type="PARTICLE_SYSTEM")
    particle_system = getattr(modifier, "particle_system", None)
    if particle_system is None:
        systems = getattr(obj, "particle_systems", None)
        try:
            particle_system = systems[-1] if systems else None
        except (TypeError, IndexError):
            particle_system = None
    if particle_system is None:
        raise ValueError(
            f"Could not create a particle system on '{obj.name}'"
        )
    settings = particle_system.settings
    try:
        settings.name = clean_name
    except (AttributeError, TypeError):
        pass
    settings.count = count
    try:
        settings.lifetime = float(lifetime)
    except (AttributeError, TypeError):
        pass
    scene = bpy.context.scene
    frame_start = int(scene.frame_start)
    for attr, value in (("frame_start", frame_start),
                        ("frame_end", frame_start + lifetime),
                        ("emit_from", "FACE"),
                        ("distribution", "JIT")):
        try:
            if hasattr(settings, attr):
                setattr(settings, attr, value)
        except (AttributeError, TypeError, ValueError):
            pass
    _link_object(obj)

    return {
        "success": True,
        "object": obj.name,
        "name": clean_name,
        "modifier": modifier.name,
        "particle_system": particle_system.name,
        "settings": settings.name,
        "count": count,
        "lifetime": lifetime,
        "frame_start": frame_start,
        "frame_end": frame_start + lifetime,
    }


# ---------------------------------------------------------------------------
# Trail
# ---------------------------------------------------------------------------

def _sample_location_fcurves(obj, frames):
    """Evaluate location fcurves at `frames`; None when not keyframed."""
    animation_data = getattr(obj, "animation_data", None)
    action = getattr(animation_data, "action", None)
    if action is None:
        return None
    try:
        fcurves = list(getattr(action, "fcurves", []) or [])
    except Exception:
        return None
    by_index = {}
    for fcurve in fcurves:
        try:
            path = getattr(fcurve, "data_path", "")
            index = int(getattr(fcurve, "array_index", -1))
        except (TypeError, ValueError):
            continue
        if path == "location" and index in (0, 1, 2):
            by_index[index] = fcurve
    if len(by_index) != 3:
        return None
    points = []
    for frame in frames:
        try:
            points.append(Vector((
                by_index[0].evaluate(frame),
                by_index[1].evaluate(frame),
                by_index[2].evaluate(frame),
            )))
        except (AttributeError, TypeError):
            return None
    return points


def create_trail(server, object_name, name="Trail",
                 length=20) -> dict:
    """Create a curve trail sampling an object's animated path, or a line."""
    _ = server
    obj = _get_object(object_name)
    clean_name = _validate_name(name)
    length = _validate_int(length, "length", minimum=2, maximum=1024)

    scene = bpy.context.scene
    frame_start = int(scene.frame_start)
    frame_end = max(int(scene.frame_end), frame_start + 1)
    if length == 1:
        frames = [float(frame_start)]
    else:
        frames = [frame_start + (frame_end - frame_start) * i / (length - 1)
                  for i in range(length)]
    points = _sample_location_fcurves(obj, frames)
    if points is None:
        base = obj.matrix_world.translation.copy()
        points = [base + Vector((0.0, -0.1 * i, 0.0)) for i in range(length)]
        source = "static_line"
    else:
        source = "animation"

    curve_data = bpy.data.curves.new(clean_name + "Curve", type="CURVE")
    curve_data.dimensions = "3D"
    spline = curve_data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for spline_point, location in zip(spline.points, points):
        spline_point.co = (location.x, location.y, location.z, 1.0)
    curve_data.bevel_depth = 0.02
    trail_obj = bpy.data.objects.new(clean_name, curve_data)
    _link_object(trail_obj)

    material = _emission_material(
        clean_name + "_TrailMat", (0.3, 0.8, 1.0), strength=4.0)
    if material.name not in trail_obj.data.materials:
        trail_obj.data.materials.append(material)

    return {
        "success": True,
        "name": trail_obj.name,
        "object": trail_obj.name,
        "source_object": obj.name,
        "material": material.name,
        "point_count": len(points),
        "length": length,
        "source": source,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "bevel_depth": curve_data.bevel_depth,
    }


# ---------------------------------------------------------------------------
# Muzzle flash
# ---------------------------------------------------------------------------

def create_muzzle_flash(server, name="MuzzleFlash",
                        location=(0.0, 0.0, 1.0),
                        energy=200.0) -> dict:
    """Create a flash light plus an emissive cone at a muzzle location."""
    _ = server
    clean_name = _validate_name(name)
    loc = _validate_vector3(location, "location")
    energy = _validate_float(energy, "energy", minimum=0.0)

    light_data = bpy.data.lights.new(name=clean_name + "_Light", type="POINT")
    light_data.energy = energy
    light_data.color = (1.0, 0.75, 0.45)
    light_obj = bpy.data.objects.new(clean_name + "_Light", light_data)
    light_obj.location = Vector(loc)
    _link_object(light_obj)

    cone_depth = 0.9
    cone_radius = 0.3

    def _build(bm):
        bmesh.ops.create_cone(
            bm, cap_ends=True, segments=24,
            radius1=cone_radius, radius2=0.03, depth=cone_depth)

    flash_obj = _mesh_object(clean_name + "_Flash", _build)
    flash_obj.location = Vector((loc[0], loc[1] - cone_depth / 2.0, loc[2]))
    flash_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    _link_object(flash_obj)

    strength = max(4.0, energy / 10.0)
    material = _emission_material(
        clean_name + "_FlashMat", (1.0, 0.6, 0.15), strength=strength)
    _attach_material(flash_obj, material)

    return {
        "success": True,
        "name": clean_name,
        "light": light_obj.name,
        "flash": flash_obj.name,
        "material": material.name,
        "location": [round(c, 6) for c in loc],
        "energy": energy,
        "emission_strength": round(strength, 6),
        "cone_radius": cone_radius,
        "cone_depth": cone_depth,
        "dimensions": [round(cone_radius * 2.0, 6), round(cone_radius * 2.0, 6),
                       round(cone_depth, 6)],
    }


# ---------------------------------------------------------------------------
# Explosion
# ---------------------------------------------------------------------------

def create_explosion(server, name="Explosion",
                     location=(0.0, 0.0, 1.0),
                     radius=2.0) -> dict:
    """Create a fireball sphere, shockwave ring and smoke plume, no baking."""
    _ = server
    clean_name = _validate_name(name)
    loc = _validate_vector3(location, "location")
    radius = _validate_float(radius, "radius", minimum=0.05, maximum=100.0)

    core_radius = radius * 0.6

    def _build_core(bm):
        bmesh.ops.create_uvsphere(
            bm, u_segments=32, v_segments=16, radius=core_radius)

    core = _mesh_object(clean_name + "_Fireball", _build_core)
    core.location = Vector(loc)
    _link_object(core)
    fire_mat = _emission_material(
        clean_name + "_FireMat", (1.0, 0.45, 0.1), strength=30.0)
    _attach_material(core, fire_mat)

    ring_major = radius
    ring_minor = max(0.02, radius * 0.06)

    def _build_ring(bm):
        _torus(bm, ring_major, ring_minor, 48, 12)

    ring = _mesh_object(clean_name + "_ShockRing", _build_ring)
    ring.location = Vector(loc)
    _link_object(ring)
    ring_mat = _transparent_emission_material(
        clean_name + "_RingMat", (1.0, 0.8, 0.5), strength=8.0)
    _attach_material(ring, ring_mat)

    plume_height = radius * 1.5
    plume_radius = max(0.2, radius * 0.5)

    def _build_plume(bm):
        bmesh.ops.create_cone(
            bm, cap_ends=True, segments=24,
            radius1=plume_radius, radius2=plume_radius * 0.4,
            depth=plume_height)

    plume = _mesh_object(clean_name + "_Smoke", _build_plume)
    plume.location = Vector((loc[0], loc[1], loc[2] + plume_height / 2.0))
    _link_object(plume)
    smoke_mat, volume_type = _volume_material(
        clean_name + "_SmokeMat", (0.25, 0.24, 0.24), density=2.0)
    _attach_material(plume, smoke_mat)

    return {
        "success": True,
        "name": clean_name,
        "core": core.name,
        "shockwave_ring": ring.name,
        "smoke_plume": plume.name,
        "materials": {
            "fire": fire_mat.name,
            "ring": ring_mat.name,
            "smoke": smoke_mat.name,
        },
        "volume_type": volume_type,
        "location": [round(c, 6) for c in loc],
        "radius": radius,
        "core_radius": round(core_radius, 6),
        "ring_radius": round(ring_major, 6),
        "plume_height": round(plume_height, 6),
        "dimensions": [round(radius * 2.0, 6), round(radius * 2.0, 6),
                       round(radius * 2.0 + plume_height, 6)],
    }


# ---------------------------------------------------------------------------
# Smoke plume
# ---------------------------------------------------------------------------

def create_smoke_plume(server, name="Smoke",
                       location=(0.0, 0.0, 0.0),
                       height=4.0, seed=0) -> dict:
    """Create a bent, jittered cone with a smoke volume material."""
    _ = server
    clean_name = _validate_name(name)
    loc = _validate_vector3(location, "location")
    height = _validate_float(height, "height", minimum=0.1, maximum=100.0)
    seed = _validate_seed(seed)

    rng = random.Random(seed)
    base_radius = max(0.2, height * 0.15)
    bend = rng.uniform(-0.15, 0.15) * height

    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    bm = bmesh.new()
    try:
        bmesh.ops.create_cone(
            bm, cap_ends=True, segments=24,
            radius1=base_radius, radius2=base_radius * 0.45, depth=height)
        for vert in bm.verts:
            t = (vert.co.z + height / 2.0) / height  # 0 at base, 1 at top
            vert.co.x += bend * t * t
            vert.co.x += rng.uniform(-1.0, 1.0) * base_radius * 0.06 * t
            vert.co.y += rng.uniform(-1.0, 1.0) * base_radius * 0.06 * t
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    obj.location = Vector((loc[0], loc[1], loc[2] + height / 2.0))
    _link_object(obj)

    material, volume_type = _volume_material(
        clean_name + "_SmokeMat", (0.4, 0.4, 0.42), density=2.0)
    _attach_material(obj, material)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "volume_type": volume_type,
        "location": [round(c, 6) for c in loc],
        "height": height,
        "base_radius": round(base_radius, 6),
        "bend": round(bend, 6),
        "dimensions": [round(base_radius * 2.0 + abs(bend), 6),
                       round(base_radius * 2.0, 6), round(height, 6)],
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Fire
# ---------------------------------------------------------------------------

def create_fire_effect(server, name="Fire", radius=0.5,
                       height=1.5) -> dict:
    """Create a noise-displaced flame mesh with a fire emission material."""
    _ = server
    clean_name = _validate_name(name)
    radius = _validate_float(radius, "radius", minimum=0.05, maximum=50.0)
    height = _validate_float(height, "height", minimum=0.1, maximum=50.0)

    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    bm = bmesh.new()
    try:
        bmesh.ops.create_cone(
            bm, cap_ends=True, segments=24,
            radius1=radius, radius2=0.02, depth=height)
        bm.faces.ensure_lookup_table()
        for vert in bm.verts:
            t = (vert.co.z + height / 2.0) / height  # 0 at base, 1 at tip
            angle = math.atan2(vert.co.y, vert.co.x)
            wobble = (math.sin(angle * 5.0 + t * 6.0) * 0.12
                      + math.sin(angle * 3.0 - t * 9.0) * 0.08)
            scale = 1.0 + wobble * (0.3 + 0.7 * t)
            vert.co.x *= scale
            vert.co.y *= scale
            vert.co.z += math.sin(angle * 4.0) * height * 0.03 * t
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    obj.location = Vector((0.0, 0.0, height / 2.0))
    _link_object(obj)

    material = _fire_material(clean_name + "_FireMat")
    _attach_material(obj, material)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "radius": radius,
        "height": height,
        "location": [round(c, 6) for c in obj.location],
        "dimensions": [round(radius * 2.0, 6), round(radius * 2.0, 6),
                       round(height, 6)],
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
    }


# ---------------------------------------------------------------------------
# Sparks
# ---------------------------------------------------------------------------

def create_spark_burst(server, name="Sparks",
                       location=(0.0, 0.0, 1.0),
                       count=100, seed=0) -> dict:
    """Create deterministic spark streaks radiating from a location."""
    _ = server
    clean_name = _validate_name(name)
    loc = _validate_vector3(location, "location")
    count = _validate_int(count, "count", minimum=1, maximum=20000)
    seed = _validate_seed(seed)

    rng = random.Random(seed)
    verts = []
    edges = []
    for i in range(count):
        theta = rng.uniform(0.0, math.tau)
        z = rng.uniform(-1.0, 1.0)
        radial = math.sqrt(max(0.0, 1.0 - z * z))
        direction = Vector((radial * math.cos(theta),
                            radial * math.sin(theta), z))
        start = Vector(loc) + direction * rng.uniform(0.02, 0.1)
        end = start + direction * rng.uniform(0.1, 0.4)
        verts.append((start.x, start.y, start.z))
        verts.append((end.x, end.y, end.z))
        edges.append((2 * i, 2 * i + 1))

    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    mesh.from_pydata(verts, edges, [])
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)

    material = _emission_material(
        clean_name + "_SparkMat", (1.0, 0.85, 0.4), strength=20.0)
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "location": [round(c, 6) for c in loc],
        "count": count,
        "dimensions": [round(1.0, 6), round(1.0, 6), round(1.0, 6)],
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Shockwave
# ---------------------------------------------------------------------------

def create_shockwave(server, name="Shockwave",
                     location=(0.0, 0.0, 1.0),
                     radius=3.0) -> dict:
    """Create an expanding-ring torus with a transparent emission material."""
    _ = server
    clean_name = _validate_name(name)
    loc = _validate_vector3(location, "location")
    radius = _validate_float(radius, "radius", minimum=0.05, maximum=200.0)

    minor = max(0.02, radius * 0.03)

    def _build(bm):
        _torus(bm, radius, minor, 64, 12)

    obj = _mesh_object(clean_name, _build)
    obj.location = Vector(loc)
    _link_object(obj)

    material = _transparent_emission_material(
        clean_name + "_WaveMat", (0.7, 0.85, 1.0), strength=5.0)
    _attach_material(obj, material)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "location": [round(c, 6) for c in loc],
        "radius": radius,
        "tube_radius": round(minor, 6),
        "dimensions": [round((radius + minor) * 2.0, 6),
                       round((radius + minor) * 2.0, 6),
                       round(minor * 2.0, 6)],
        "vertex_count": len(obj.data.vertices),
        "face_count": len(obj.data.polygons),
    }
