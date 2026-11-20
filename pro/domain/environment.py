"""Environment dressing tools: sky, fog, clouds, ground, cliff, beach, biome scatter and shore (domain pack).

Runs on Blender's main thread. Uses only ``bpy``, ``bmesh``, ``mathutils``
and the standard library. All functions validate their inputs, raise
``ValueError`` with a precise message on bad input, and return plain
JSON-serializable dictionaries. Results are deterministic for a given
``seed``. Compatible with Blender 4.5 LTS and 5.2 LTS.
"""

import bisect
import math
import random

import bpy
import bmesh
from mathutils import Euler, Matrix, Quaternion, Vector

_MASK64 = 0xFFFFFFFFFFFFFFFF
_NORM64 = 18446744073709551616.0

_GROUND_STYLES = {
    "grass": {"color": (0.16, 0.36, 0.10, 1.0), "roughness": 0.9, "relief": 0.25},
    "dirt": {"color": (0.32, 0.22, 0.12, 1.0), "roughness": 0.95, "relief": 0.20},
    "sand": {"color": (0.76, 0.68, 0.48, 1.0), "roughness": 0.9, "relief": 0.12},
}
_CLIFF_ROCK_LIGHT = (0.45, 0.40, 0.34, 1.0)
_CLIFF_ROCK_DARK = (0.25, 0.21, 0.17, 1.0)
_SHORE_SAND = (0.76, 0.68, 0.48, 1.0)
_SHORE_ROCK = (0.45, 0.42, 0.38, 1.0)
_WATER_TINT = (0.05, 0.25, 0.35, 1.0)


# ---------------------------------------------------------------------------
# Deterministic value noise (pure Python, platform independent)
# ---------------------------------------------------------------------------

def _mix_hash(state):
    """Avalanche an integer state into a float in [0, 1)."""
    state = (state + 0x9E3779B97F4A7C15) & _MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    z = (z ^ (z >> 31)) & _MASK64
    return z / _NORM64


def _hash2(ix, iy, seed):
    key = ((ix * 0x8DA6B343) ^ (iy * 0xD8163841) ^ (seed * 0x9E3779B9)) & _MASK64
    return _mix_hash(key ^ 0x6A09E667F3BCC909)


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _value_noise2(x, y, seed):
    xi = math.floor(x)
    yi = math.floor(y)
    xf = x - xi
    yf = y - yi
    u = _fade(xf)
    v = _fade(yf)
    a = _hash2(xi, yi, seed)
    b = _hash2(xi + 1, yi, seed)
    c = _hash2(xi, yi + 1, seed)
    d = _hash2(xi + 1, yi + 1, seed)
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v


def _fbm2(x, y, octaves, seed):
    total = 0.0
    amplitude = 0.5
    frequency = 1.0
    norm = 0.0
    for octave in range(octaves):
        total += amplitude * _value_noise2(x * frequency, y * frequency, seed + octave * 7919)
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return total / norm if norm else 0.0


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _require_number(value, label):
    if not _is_number(value) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite number (got {value!r})")
    return float(value)


def _require_positive(value, label):
    number = _require_number(value, label)
    if number <= 0.0:
        raise ValueError(f"{label} must be > 0 (got {value!r})")
    return number


def _require_non_negative(value, label):
    number = _require_number(value, label)
    if number < 0.0:
        raise ValueError(f"{label} must be >= 0 (got {value!r})")
    return number


def _require_seed(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"seed must be an integer (got {value!r})")
    return value


def _require_int(value, label, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {value})")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {value})")
    return value


def _require_vector3(value, label):
    try:
        items = [float(item) for item in value]
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a sequence of 3 numbers (got {value!r})") from None
    if len(items) != 3 or not all(math.isfinite(item) for item in items):
        raise ValueError(f"{label} must be a sequence of 3 finite numbers (got {value!r})")
    return items


def _require_color3(value, label="color"):
    try:
        items = [float(item) for item in value]
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a sequence of 3 numbers in [0, 1] (got {value!r})") from None
    if len(items) != 3 or not all(math.isfinite(item) for item in items):
        raise ValueError(f"{label} must be a sequence of 3 finite numbers (got {value!r})")
    if any(item < 0.0 or item > 1.0 for item in items):
        raise ValueError(f"{label} channels must be in [0, 1] (got {value!r})")
    return items


def _require_object(object_name, label="object_name"):
    clean = _require_name(object_name, label)
    obj = bpy.data.objects.get(clean)
    if obj is None:
        raise ValueError(f"Object '{clean}' not found")
    return obj


# ---------------------------------------------------------------------------
# Blender helpers
# ---------------------------------------------------------------------------

def _link_object(obj, reference=None):
    collections = getattr(reference, "users_collection", None) if reference else None
    target = collections[0] if collections else bpy.context.scene.collection
    if obj.name not in target.objects:
        target.objects.link(obj)
    return target.name


def _set_smooth(mesh, smooth=True):
    try:
        for polygon in mesh.polygons:
            polygon.use_smooth = smooth
    except AttributeError:
        pass
    mesh.update()


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


def _solid_material(name, color, roughness):
    """Get or rebuild a Principled BSDF solid-color material."""
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    _clear_tree(tree)
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0.0, 0.0)
    _set_socket(bsdf, ("Base Color",), (color[0], color[1], color[2], 1.0))
    _set_socket(bsdf, ("Roughness",), float(roughness))
    _set_socket(bsdf, ("Metallic",), 0.0)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return material, bsdf


def _add_noise_tint(tree, bsdf, base_color, scale, seed, tint=(1.0, 1.0, 1.0)):
    """Mix subtle procedural variation into a Principled base color."""
    tex_coord = tree.nodes.new(type="ShaderNodeTexCoord")
    tex_coord.location = (-700.0, 200.0)
    mapping = tree.nodes.new(type="ShaderNodeMapping")
    mapping.location = (-500.0, 200.0)
    # Deterministic offset derived from the seed (no RNG state needed).
    _set_socket(mapping, ("Location",), (
        float((seed * 12.9898) % 17.0),
        float((seed * 78.233) % 17.0),
        0.0,
    ))
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.location = (-300.0, 200.0)
    _set_socket(noise, ("Scale",), float(scale))
    _set_socket(noise, ("Detail",), 2.0)
    mix = tree.nodes.new(type="ShaderNodeMix")
    mix.location = (-100.0, 0.0)
    try:
        mix.data_type = "RGBA"
    except (AttributeError, TypeError):
        pass
    _set_socket(mix, ("Factor",), 0.25)
    socket_a = mix.inputs.get("A")
    if socket_a is not None:
        socket_a.default_value = (base_color[0], base_color[1], base_color[2], 1.0)
    socket_b = mix.inputs.get("B")
    if socket_b is not None:
        socket_b.default_value = (
            min(1.0, base_color[0] * tint[0]),
            min(1.0, base_color[1] * tint[1]),
            min(1.0, base_color[2] * tint[2]),
            1.0,
        )
    tree.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    factor_socket = mix.inputs.get("Factor")
    if factor_socket is not None:
        tree.links.new(noise.outputs["Fac"], factor_socket)
    target = bsdf.inputs.get("Base Color")
    result = mix.outputs.get("Result")
    if target is not None and result is not None:
        tree.links.new(result, target)


def _mesh_bounds(obj):
    bpy.context.view_layer.update()
    matrix = obj.matrix_world.copy()
    world = [matrix @ vertex.co for vertex in obj.data.vertices]
    lo = [min(v[i] for v in world) for i in range(3)]
    hi = [max(v[i] for v in world) for i in range(3)]
    return [round(hi[i] - lo[i], 6) for i in range(3)], [round(v, 6) for v in lo], [round(v, 6) for v in hi]


# ---------------------------------------------------------------------------
# Sky + Sun
# ---------------------------------------------------------------------------

def create_sky_lighting(server, name="Sky", sun_elevation=45.0,
                         sun_rotation=135.0, sun_energy=3.0,
                         sky_strength=1.0) -> dict:
    """Create a Sky Texture world background plus an oriented Sun light."""
    _ = server
    clean_name = _require_name(name)
    elevation = _require_number(sun_elevation, "sun_elevation")
    if elevation < 0.0 or elevation > 90.0:
        raise ValueError(f"sun_elevation must be in [0, 90] degrees (got {sun_elevation!r})")
    azimuth = _require_number(sun_rotation, "sun_rotation")
    sun_energy = _require_non_negative(sun_energy, "sun_energy")
    sky_strength = _require_non_negative(sky_strength, "sky_strength")

    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new(name=clean_name)
        scene.world = world
    world.use_nodes = True
    tree = world.node_tree

    output = next((n for n in tree.nodes if n.type == "OUTPUT_WORLD"), None)
    if output is None:
        output = tree.nodes.new(type="ShaderNodeOutputWorld")
    background = next((n for n in tree.nodes if n.type == "BACKGROUND"), None)
    if background is None:
        background = tree.nodes.new(type="ShaderNodeBackground")
    sky = next((n for n in tree.nodes if n.type == "TEX_SKY"), None)
    if sky is None:
        sky = tree.nodes.new(type="ShaderNodeTexSky")
        sky.location = (-300.0, 0.0)
    sky_type = "NISHITA"
    try:
        sky.sky_type = sky_type
    except (AttributeError, TypeError):
        sky_type = getattr(sky, "sky_type", "NISHITA")
    sky.sun_elevation = math.radians(elevation)
    sky.sun_rotation = math.radians(azimuth % 360.0)
    _set_socket(background, ("Strength",), sky_strength)
    if sky.outputs.get("Color") and background.inputs.get("Color"):
        already = any(
            link.from_node == sky and link.to_node == background
            for link in tree.links
        )
        if not already:
            tree.links.new(sky.outputs["Color"], background.inputs["Color"])
    if background.outputs.get("Background") and output.inputs.get("Surface"):
        already = any(
            link.from_node == background and link.to_node == output
            for link in tree.links
        )
        if not already:
            tree.links.new(background.outputs["Background"], output.inputs["Surface"])

    elev_rad = math.radians(elevation)
    azim_rad = math.radians(azimuth % 360.0)
    sun_dir = Vector((
        math.cos(elev_rad) * math.cos(azim_rad),
        math.cos(elev_rad) * math.sin(azim_rad),
        math.sin(elev_rad),
    ))
    light_data = bpy.data.lights.new(name=clean_name + "_Sun", type="SUN")
    light_data.energy = sun_energy
    sun_obj = bpy.data.objects.new(name=clean_name + "_Sun", object_data=light_data)
    _link_object(sun_obj)
    sun_obj.location = sun_dir * 30.0
    sun_obj.rotation_euler = (-sun_dir).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()

    sun_angle = round(math.degrees(getattr(light_data, "angle", 0.0093)), 6)
    return {
        "success": True,
        "name": clean_name,
        "world": world.name,
        "sun": sun_obj.name,
        "sky_type": sky_type,
        "sun_elevation": elevation,
        "sun_rotation": azimuth,
        "sun_energy": sun_energy,
        "sky_strength": sky_strength,
        "sun_angle": sun_angle,
        "sun_location": [round(c, 6) for c in sun_obj.location],
        "dimensions": [0.0, 0.0, 0.0],
    }


# ---------------------------------------------------------------------------
# Fog volume
# ---------------------------------------------------------------------------

def create_fog_volume(server, name="Fog", size=20.0, density=0.02,
                      color=(0.8, 0.85, 0.9),
                      location=(0.0, 0.0, 0.0)) -> dict:
    """Create a cube volume with a Principled Volume fog material."""
    _ = server
    clean_name = _require_name(name)
    size = _require_positive(size, "size")
    density = _require_non_negative(density, "density")
    rgb = _require_color3(color)
    loc = _require_vector3(location, "location")

    half = size / 2.0
    verts = [
        (-half, -half, -half), (half, -half, -half),
        (half, half, -half), (-half, half, -half),
        (-half, -half, half), (half, -half, half),
        (half, half, half), (-half, half, half),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5),
        (0, 4, 5, 1), (1, 5, 6, 2),
        (2, 6, 7, 3), (3, 7, 4, 0),
    ]
    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)
    obj.location = Vector(loc)

    material = bpy.data.materials.get(clean_name + "_Fog")
    if material is None:
        material = bpy.data.materials.new(clean_name + "_Fog")
    material.use_nodes = True
    tree = material.node_tree
    _clear_tree(tree)
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300.0, 0.0)
    try:
        volume = tree.nodes.new(type="ShaderNodeVolumePrincipled")
        volume.location = (0.0, 0.0)
        _set_socket(volume, ("Color",), (rgb[0], rgb[1], rgb[2], 1.0))
        _set_socket(volume, ("Density",), float(density))
        tree.links.new(volume.outputs["Volume"], output.inputs["Volume"])
        volume_type = "PRINCIPLED_VOLUME"
    except RuntimeError:
        scatter = tree.nodes.new(type="ShaderNodeVolumeScatter")
        _set_socket(scatter, ("Color",), (rgb[0], rgb[1], rgb[2], 1.0))
        _set_socket(scatter, ("Density",), float(density))
        tree.links.new(scatter.outputs["Volume"], output.inputs["Volume"])
        volume_type = "VOLUME_SCATTER"
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    bpy.context.view_layer.update()

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "volume_type": volume_type,
        "size": size,
        "dimensions": [round(size, 6), round(size, 6), round(size, 6)],
        "density": density,
        "color": [round(c, 6) for c in rgb],
        "location": [round(c, 6) for c in loc],
    }


# ---------------------------------------------------------------------------
# Cloud layer
# ---------------------------------------------------------------------------

def create_cloud_layer(server, name="Clouds", size=20.0, altitude=10.0,
                       density=1.0, seed=0) -> dict:
    """Create a noise-displaced cloud plane with a procedural alpha material."""
    _ = server
    clean_name = _require_name(name)
    size = _require_positive(size, "size")
    altitude = _require_non_negative(altitude, "altitude")
    density = _require_non_negative(density, "density")
    seed = _require_seed(seed)

    seed_masked = seed & _MASK64
    rng = random.Random(seed)
    offset_x = rng.uniform(-64.0, 64.0)
    offset_y = rng.uniform(-64.0, 64.0)
    res = 32
    half = size / 2.0
    amplitude = size * 0.04
    verts = []
    for j in range(res + 1):
        y = -half + size * j / res
        for i in range(res + 1):
            x = -half + size * i / res
            noise = _fbm2(x / size * 4.0 + offset_x, y / size * 4.0 + offset_y, 4, seed_masked)
            verts.append((x, y, (noise - 0.5) * 2.0 * amplitude))
    faces = []
    row = res + 1
    for j in range(res):
        for i in range(res):
            a = j * row + i
            faces.append((a, a + 1, a + 1 + row, a + row))
    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)
    obj.location = Vector((0.0, 0.0, altitude))
    _set_smooth(mesh, True)

    material = bpy.data.materials.get(clean_name + "_Clouds")
    if material is None:
        material = bpy.data.materials.new(clean_name + "_Clouds")
    material.use_nodes = True
    tree = material.node_tree
    _clear_tree(tree)
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (400.0, 0.0)
    mix = tree.nodes.new(type="ShaderNodeMixShader")
    mix.location = (200.0, 0.0)
    transparent = tree.nodes.new(type="ShaderNodeBsdfTransparent")
    transparent.location = (0.0, 150.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0.0, -150.0)
    _set_socket(bsdf, ("Base Color",), (1.0, 1.0, 1.0, 1.0))
    _set_socket(bsdf, ("Roughness",), 1.0)
    tex_coord = tree.nodes.new(type="ShaderNodeTexCoord")
    tex_coord.location = (-600.0, 0.0)
    mapping = tree.nodes.new(type="ShaderNodeMapping")
    mapping.location = (-400.0, 0.0)
    _set_socket(mapping, ("Location",), (
        float((seed * 12.9898) % 17.0), float((seed * 78.233) % 17.0), 0.0))
    noise_node = tree.nodes.new(type="ShaderNodeTexNoise")
    noise_node.location = (-200.0, 0.0)
    _set_socket(noise_node, ("Scale",), 3.0)
    _set_socket(noise_node, ("Detail",), 4.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.location = (0.0, 150.0)
    # Higher density pushes the opaque stop lower so more of the layer shows.
    low = max(0.0, min(0.9, 0.65 - density * 0.3))
    ramp.color_ramp.elements[0].position = low
    ramp.color_ramp.elements[0].color = (1.0, 1.0, 1.0, 1.0)
    ramp.color_ramp.elements[1].position = min(1.0, low + 0.3)
    ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 0.0)
    tree.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], noise_node.inputs["Vector"])
    tree.links.new(noise_node.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Alpha"], mix.inputs["Fac"])
    tree.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    tree.links.new(transparent.outputs["BSDF"], mix.inputs[2])
    tree.links.new(mix.outputs["Shader"], output.inputs["Surface"])
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    bpy.context.view_layer.update()

    dims, _, _ = _mesh_bounds(obj)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "size": size,
        "dimensions": dims,
        "altitude": altitude,
        "density": density,
        "seed": seed,
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
    }


# ---------------------------------------------------------------------------
# Ground
# ---------------------------------------------------------------------------

def create_ground(server, name="Ground", size=20.0, subdivisions=16,
                  style="grass", seed=0) -> dict:
    """Create a subdivided ground plane with a grass/dirt/sand material, top at Z=0."""
    _ = server
    clean_name = _require_name(name)
    size = _require_positive(size, "size")
    subdivisions = _require_int(subdivisions, "subdivisions", minimum=1, maximum=256)
    if not isinstance(style, str):
        raise ValueError(f"style must be a string (got {style!r})")
    style_key = style.strip().lower()
    if style_key not in _GROUND_STYLES:
        raise ValueError(
            f"Unknown style '{style}'. Expected one of {sorted(_GROUND_STYLES)}"
        )
    seed = _require_seed(seed)

    preset = _GROUND_STYLES[style_key]
    seed_masked = seed & _MASK64
    rng = random.Random(seed)
    offset_x = rng.uniform(-64.0, 64.0)
    offset_y = rng.uniform(-64.0, 64.0)
    half = size / 2.0
    amplitude = min(preset["relief"], size * 0.02)

    raw = []
    for j in range(subdivisions + 1):
        y = -half + size * j / subdivisions
        for i in range(subdivisions + 1):
            x = -half + size * i / subdivisions
            noise = _fbm2(x / size * 3.0 + offset_x, y / size * 3.0 + offset_y, 3, seed_masked)
            raw.append((noise - 0.5) * 2.0 * amplitude)
    top = max(raw)
    verts = []
    index = 0
    for j in range(subdivisions + 1):
        y = -half + size * j / subdivisions
        for i in range(subdivisions + 1):
            x = -half + size * i / subdivisions
            verts.append((x, y, raw[index] - top))
            index += 1
    row = subdivisions + 1
    faces = []
    for j in range(subdivisions):
        for i in range(subdivisions):
            a = j * row + i
            faces.append((a, a + 1, a + 1 + row, a + row))

    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)
    _set_smooth(mesh, True)

    material, bsdf = _solid_material(
        clean_name + "_Ground", preset["color"], preset["roughness"])
    _add_noise_tint(material.node_tree, bsdf, preset["color"], 4.0, seed,
                    tint=(0.85, 0.85, 0.8))
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    bpy.context.view_layer.update()

    world_z = [v.co.z for v in mesh.vertices]
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "style": style_key,
        "size": size,
        "dimensions": [round(size, 6), round(size, 6), round(max(world_z) - min(world_z), 6)],
        "subdivisions": subdivisions,
        "seed": seed,
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
        "top_z": round(max(world_z), 6),
        "min_z": round(min(world_z), 6),
    }


# ---------------------------------------------------------------------------
# Cliff
# ---------------------------------------------------------------------------

def create_cliff(server, name="Cliff", width=5.0, height=3.0, depth=2.0,
                 seed=0, subdivisions=24) -> dict:
    """Create a closed displaced cliff block with rock strata, grounded at Z=0."""
    _ = server
    clean_name = _require_name(name)
    width = _require_positive(width, "width")
    height = _require_positive(height, "height")
    depth = _require_positive(depth, "depth")
    seed = _require_seed(seed)
    subdivisions = _require_int(subdivisions, "subdivisions", minimum=1, maximum=128)

    seed_masked = seed & _MASK64
    rng = random.Random(seed)
    offset_x = rng.uniform(-64.0, 64.0)
    offset_z = rng.uniform(-64.0, 64.0)
    cols = subdivisions + 1
    rows = subdivisions + 1

    def _face_offset(x, z):
        strata = math.sin(z / max(height, 1e-6) * math.pi * 6.0
                          + _fbm2(x + offset_x, z + offset_z, 2, seed_masked) * 4.0)
        lumps = _fbm2(x / max(width, 1e-6) * 3.0 + offset_x,
                      z / max(height, 1e-6) * 3.0 + offset_z, 4, seed_masked)
        return strata * depth * 0.08 + (lumps - 0.5) * depth * 0.9

    front = [[None] * cols for _ in range(rows)]
    back = [[None] * cols for _ in range(rows)]
    bm = bmesh.new()
    for j in range(rows):
        z = height * j / subdivisions
        for i in range(cols):
            x = -width / 2.0 + width * i / subdivisions
            front[j][i] = bm.verts.new((x, _face_offset(x, z), z))
            back[j][i] = bm.verts.new((x, -depth, z))
    bm.verts.ensure_lookup_table()
    for j in range(rows - 1):
        for i in range(cols - 1):
            bm.faces.new((front[j][i], front[j][i + 1], front[j + 1][i + 1], front[j + 1][i]))
            bm.faces.new((back[j][i], back[j + 1][i], back[j + 1][i + 1], back[j][i + 1]))
    for i in range(cols - 1):
        bm.faces.new((front[0][i], back[0][i], back[0][i + 1], front[0][i + 1]))
        bm.faces.new((front[rows - 1][i], front[rows - 1][i + 1],
                      back[rows - 1][i + 1], back[rows - 1][i]))
    for j in range(rows - 1):
        bm.faces.new((front[j][0], front[j + 1][0], back[j + 1][0], back[j][0]))
        bm.faces.new((front[j][cols - 1], back[j][cols - 1],
                      back[j + 1][cols - 1], front[j + 1][cols - 1]))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)
    _set_smooth(mesh, True)

    material = bpy.data.materials.get(clean_name + "_Cliff")
    if material is None:
        material = bpy.data.materials.new(clean_name + "_Cliff")
    material.use_nodes = True
    tree = material.node_tree
    _clear_tree(tree)
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0.0, 0.0)
    _set_socket(bsdf, ("Roughness",), 0.9)
    tex_coord = tree.nodes.new(type="ShaderNodeTexCoord")
    tex_coord.location = (-400.0, 200.0)
    separate = tree.nodes.new(type="ShaderNodeSeparateXYZ")
    separate.location = (-200.0, 200.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.location = (-100.0, 200.0)
    ramp.color_ramp.interpolation = "CONSTANT"
    elements = ramp.color_ramp.elements
    while len(elements) < 5:
        elements.new(0.5)
    stops = [0.0, 0.25, 0.5, 0.75, 1.0]
    tones = [_CLIFF_ROCK_DARK, _CLIFF_ROCK_LIGHT, _CLIFF_ROCK_DARK,
             _CLIFF_ROCK_LIGHT, _CLIFF_ROCK_DARK]
    for element, position, tone in zip(elements, stops, tones):
        element.position = position
        element.color = tone
    noise_node = tree.nodes.new(type="ShaderNodeTexNoise")
    noise_node.location = (-200.0, -100.0)
    _set_socket(noise_node, ("Scale",), 5.0)
    bump = tree.nodes.new(type="ShaderNodeBump")
    bump.location = (0.0, -150.0)
    _set_socket(bump, ("Strength",), 0.4)
    tree.links.new(tex_coord.outputs["Generated"], separate.inputs["Vector"])
    tree.links.new(separate.outputs["Z"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    tree.links.new(tex_coord.outputs["Object"], noise_node.inputs["Vector"])
    tree.links.new(noise_node.outputs["Fac"], bump.inputs["Height"])
    normal_socket = bsdf.inputs.get("Normal")
    if normal_socket is not None:
        tree.links.new(bump.outputs["Normal"], normal_socket)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    bpy.context.view_layer.update()

    dims, lo, hi = _mesh_bounds(obj)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "width": width,
        "height": height,
        "depth": depth,
        "dimensions": dims,
        "bounds_min": lo,
        "bounds_max": hi,
        "subdivisions": subdivisions,
        "seed": seed,
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
        "min_z": lo[2],
    }


# ---------------------------------------------------------------------------
# Beach
# ---------------------------------------------------------------------------

def create_beach(server, name="Beach", width=20.0, depth=10.0,
                 slope=0.08, seed=0) -> dict:
    """Create a sloped sand beach with an explicit waterline edge at Z=0."""
    _ = server
    clean_name = _require_name(name)
    width = _require_positive(width, "width")
    depth = _require_positive(depth, "depth")
    slope = _require_non_negative(slope, "slope")
    seed = _require_seed(seed)

    seed_masked = seed & _MASK64
    rng = random.Random(seed)
    offset_x = rng.uniform(-64.0, 64.0)
    offset_y = rng.uniform(-64.0, 64.0)
    nx, ny = 32, 16
    half_w = width / 2.0
    half_d = depth / 2.0
    verts = []
    for j in range(ny + 1):
        y = -half_d + depth * j / ny
        inland = (y + half_d) / depth
        for i in range(nx + 1):
            x = -half_w + width * i / nx
            ripple = (_fbm2(x / width * 6.0 + offset_x, y / depth * 6.0 + offset_y,
                            3, seed_masked) - 0.5) * 0.1 * inland
            verts.append((x, y, (y + half_d) * slope + ripple))
    faces = []
    row = nx + 1
    for j in range(ny):
        for i in range(nx):
            a = j * row + i
            faces.append((a, a + 1, a + 1 + row, a + row))
    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)
    _set_smooth(mesh, True)

    # Explicit waterline edge: the shoreline row at y = -depth/2 sits at Z=0.
    group = obj.vertex_groups.new(name="Waterline")
    group.add(list(range(nx + 1)), 1.0, "REPLACE")

    material, bsdf = _solid_material(
        clean_name + "_Sand", _SHORE_SAND, 0.9)
    _add_noise_tint(material.node_tree, bsdf, _SHORE_SAND, 6.0, seed,
                    tint=(0.9, 0.88, 0.82))
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    bpy.context.view_layer.update()

    dims, lo, hi = _mesh_bounds(obj)
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "width": width,
        "depth": depth,
        "slope": slope,
        "dimensions": dims,
        "bounds_min": lo,
        "bounds_max": hi,
        "seed": seed,
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
        "waterline_group": group.name,
        "waterline_z": 0.0,
        "waterline_width": round(width, 6),
    }


# ---------------------------------------------------------------------------
# Biome scatter
# ---------------------------------------------------------------------------

def _sample_surface_points(target, count, rng):
    """Return `count` area-weighted (point, normal) samples on a mesh."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = target.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    try:
        polygons = eval_mesh.polygons
        if len(polygons) == 0:
            raise ValueError(f"Object '{target.name}' has no faces to scatter on")
        matrix = eval_obj.matrix_world.copy()
        rotation = matrix.to_3x3()
        areas = [float(p.area) for p in polygons]
        total_area = sum(areas)
        if total_area <= 0.0:
            raise ValueError(f"Object '{target.name}' has no surface area to scatter on")
        cumulative = []
        running = 0.0
        for area in areas:
            running += area
            cumulative.append(running)
        samples = []
        for _ in range(count):
            pick = rng.random() * total_area
            poly = polygons[min(bisect.bisect_left(cumulative, pick, 0, len(cumulative) - 1),
                                len(polygons) - 1)]
            corners = [matrix @ eval_mesh.vertices[i].co for i in poly.vertices]
            normal = (rotation @ poly.normal).normalized()
            tri_total = 0.0
            tri_areas = []
            for k in range(1, len(corners) - 1):
                area = 0.5 * (corners[k] - corners[0]).cross(corners[k + 1] - corners[0]).length
                tri_areas.append(area)
                tri_total += area
            if tri_total <= 0.0:
                samples.append((corners[0].copy(), normal))
                continue
            choice = rng.random() * tri_total
            acc = 0.0
            tri = 0
            for k, area in enumerate(tri_areas):
                acc += area
                if choice <= acc:
                    tri = k
                    break
            a, b, c = corners[0], corners[tri + 1], corners[tri + 2]
            r1, r2 = rng.random(), rng.random()
            if r1 + r2 > 1.0:
                r1, r2 = 1.0 - r1, 1.0 - r2
            samples.append((a + (b - a) * r1 + (c - a) * r2, normal))
    finally:
        eval_obj.to_mesh_clear()
    return samples


def _place_instances(source, target, samples, rng, tag):
    """Link scaled copies of `source` over sampled surface points."""
    target_matrix = target.matrix_world.copy()
    source_quat = source.matrix_world.to_quaternion()
    source_scale = source.matrix_world.to_scale()
    up = Vector((0.0, 0.0, 1.0))
    names = []
    for i, (point, normal) in enumerate(samples):
        factor = rng.uniform(0.8, 1.2)
        src_up = (source_quat @ up).normalized()
        if src_up.length < 1e-9:
            src_up = up
        quat = Quaternion(normal, rng.uniform(0.0, 2.0 * math.pi)) @ src_up.rotation_difference(normal) @ source_quat
        inst = source.copy()
        inst.name = f"{source.name}_{tag}_{i + 1:04d}"
        _link_object(inst, target)
        inst.parent = target
        inst.matrix_parent_inverse = target_matrix.inverted()
        inst.matrix_world = Matrix.LocRotScale(
            point,
            quat,
            Vector((source_scale.x * factor, source_scale.y * factor, source_scale.z * factor)),
        )
        names.append(inst.name)
    bpy.context.view_layer.update()
    return names


def create_biome_scatter(server, target_name, tree_name, bush_name,
                         count=20, seed=0) -> dict:
    """Scatter linked tree/bush instances over a target surface deterministically."""
    target = _require_object(target_name, "target_name")
    tree = _require_object(tree_name, "tree_name")
    bush = _require_object(bush_name, "bush_name")
    if target.type != "MESH":
        raise ValueError(f"Object '{target.name}' must be a MESH (got {target.type})")
    if tree == target or bush == target:
        raise ValueError("tree_name and bush_name must differ from target_name")
    count = _require_int(count, "count", minimum=0)
    seed = _require_seed(seed)

    if count == 0:
        return {
            "success": True,
            "target": target.name,
            "tree": tree.name,
            "bush": bush.name,
            "count": 0,
            "tree_count": 0,
            "bush_count": 0,
            "tree_instances": [],
            "bush_instances": [],
            "instances": [],
            "seed": seed,
        }

    tree_count = count - count // 2
    bush_count = count // 2
    scatter = getattr(server, "scatter_objects", None)
    if callable(scatter):
        try:
            tree_result = scatter(tree.name, target.name, tree_count, seed)
            bush_result = scatter(bush.name, target.name, bush_count, seed + 1)
            tree_instances = list(tree_result.get("instances", []))
            bush_instances = list(bush_result.get("instances", []))
        except TypeError:
            tree_instances = None
        else:
            bpy.context.view_layer.update()
            return {
                "success": True,
                "target": target.name,
                "tree": tree.name,
                "bush": bush.name,
                "count": len(tree_instances) + len(bush_instances),
                "tree_count": len(tree_instances),
                "bush_count": len(bush_instances),
                "tree_instances": tree_instances,
                "bush_instances": bush_instances,
                "instances": tree_instances + bush_instances,
                "seed": seed,
                "via": "server.scatter_objects",
            }
    else:
        tree_instances = None

    if tree_instances is None:
        rng = random.Random(seed)
        samples = _sample_surface_points(target, count, rng)
        tree_samples = samples[::2][:tree_count] if tree_count else []
        bush_samples = samples[1::2][:bush_count] if bush_count else []
        tree_instances = _place_instances(tree, target, tree_samples, rng, "tree")
        bush_instances = _place_instances(bush, target, bush_samples, rng, "bush")

    bpy.context.view_layer.update()
    return {
        "success": True,
        "target": target.name,
        "tree": tree.name,
        "bush": bush.name,
        "count": len(tree_instances) + len(bush_instances),
        "tree_count": len(tree_instances),
        "bush_count": len(bush_instances),
        "tree_instances": tree_instances,
        "bush_instances": bush_instances,
        "instances": tree_instances + bush_instances,
        "seed": seed,
        "via": "environment",
    }


# ---------------------------------------------------------------------------
# Water shore (annulus + water disc)
# ---------------------------------------------------------------------------

def create_water_shore(server, name="Shore", radius=5.0, seed=0) -> dict:
    """Create an annulus shore terrain ring around a water disc."""
    _ = server
    clean_name = _require_name(name)
    radius = _require_positive(radius, "radius")
    seed = _require_seed(seed)

    seed_masked = seed & _MASK64
    rng = random.Random(seed)
    offset = rng.uniform(-64.0, 64.0)
    segments = 64
    ring_radii = (radius, radius * 1.3, radius * 1.65, radius * 2.0)
    ring_base_z = (-0.35, -0.08, 0.12, 0.30)
    rings = []
    for k, (ring_radius, base_z) in enumerate(zip(ring_radii, ring_base_z)):
        row = []
        for j in range(segments):
            angle = 2.0 * math.pi * j / segments
            wobble = (_fbm2(math.cos(angle) * 1.5 + offset + k * 7.3,
                            math.sin(angle) * 1.5 + offset, 3, seed_masked) - 0.5)
            swell = wobble * 0.3 * (k / max(len(ring_radii) - 1, 1))
            row.append((ring_radius * math.cos(angle),
                        ring_radius * math.sin(angle),
                        base_z + swell))
        rings.append(row)

    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    flat_verts = [co for row in rings for co in row]
    faces = []
    for k in range(len(rings) - 1):
        base = k * segments
        upper = (k + 1) * segments
        for j in range(segments):
            nxt = (j + 1) % segments
            faces.append((base + j, base + nxt, upper + nxt, upper + j))
    mesh.from_pydata(flat_verts, [], faces)
    mesh.update()
    shore = bpy.data.objects.new(clean_name, mesh)
    _link_object(shore)
    _set_smooth(mesh, True)

    material = bpy.data.materials.get(clean_name + "_Shore")
    if material is None:
        material = bpy.data.materials.new(clean_name + "_Shore")
    material.use_nodes = True
    tree = material.node_tree
    _clear_tree(tree)
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0.0, 0.0)
    _set_socket(bsdf, ("Roughness",), 0.85)
    tex_coord = tree.nodes.new(type="ShaderNodeTexCoord")
    tex_coord.location = (-400.0, 0.0)
    noise_node = tree.nodes.new(type="ShaderNodeTexNoise")
    noise_node.location = (-200.0, 0.0)
    _set_socket(noise_node, ("Scale",), 4.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.location = (-100.0, 100.0)
    ramp.color_ramp.elements[0].position = 0.45
    ramp.color_ramp.elements[0].color = _SHORE_SAND
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = _SHORE_ROCK
    tree.links.new(tex_coord.outputs["Object"], noise_node.inputs["Vector"])
    tree.links.new(noise_node.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    if material.name not in shore.data.materials:
        shore.data.materials.append(material)

    # Water disc filling the annulus hole at Z=0.
    disc_radius = radius * 1.06
    disc_verts = [(0.0, 0.0, 0.0)]
    for j in range(segments):
        angle = 2.0 * math.pi * j / segments
        disc_verts.append((disc_radius * math.cos(angle),
                           disc_radius * math.sin(angle), 0.0))
    disc_faces = [(0, 1 + j, 1 + (j + 1) % segments) for j in range(segments)]
    disc_mesh = bpy.data.meshes.new(clean_name + "WaterMesh")
    disc_mesh.from_pydata(disc_verts, [], disc_faces)
    disc_mesh.update()
    water = bpy.data.objects.new(clean_name + "_Water", disc_mesh)
    _link_object(water, shore)
    _set_smooth(disc_mesh, True)
    water_material, _ = _solid_material(clean_name + "_Water", _WATER_TINT, 0.15)
    if water_material.name not in water.data.materials:
        water.data.materials.append(water_material)
    bpy.context.view_layer.update()

    dims, lo, hi = _mesh_bounds(shore)
    return {
        "success": True,
        "name": shore.name,
        "object": shore.name,
        "water": water.name,
        "material": material.name,
        "water_material": water_material.name,
        "radius": radius,
        "outer_radius": round(ring_radii[-1], 6),
        "dimensions": dims,
        "bounds_min": lo,
        "bounds_max": hi,
        "seed": seed,
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
        "water_vertex_count": len(disc_mesh.vertices),
        "water_face_count": len(disc_mesh.polygons),
    }
