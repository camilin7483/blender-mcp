"""Weather and atmosphere tools: rain, snow, lightning, wind, haze, sunset, night and composited weather scenes.

Runs on Blender's main thread. Uses only ``bpy``, ``bmesh``, ``mathutils``
and the standard library. All functions validate their inputs, raise
``ValueError`` with a precise message on bad input, and return plain
JSON-serializable dictionaries. Results are deterministic for a given
``seed``. Compatible with Blender 4.5 LTS and 5.2 LTS.
"""

import math
import random

import bpy
from mathutils import Vector

_RAIN_HEIGHT = 6.0
_RAIN_STREAK_LENGTH = 0.3
_SNOW_HEIGHT = 5.0
_SNOW_FLAKE_SIZE = 0.05
_HAZE_SIZE = 50.0
_WEATHERS = ("rain", "snow", "clear")


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


# ---------------------------------------------------------------------------
# Blender helpers
# ---------------------------------------------------------------------------

def _link_object(obj):
    target = bpy.context.scene.collection
    if obj.name not in target.objects:
        target.objects.link(obj)
    return target.name


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


def _principled_material(name, color, roughness=0.5, alpha=None):
    """Get or rebuild a Principled BSDF solid material (4.5/5.2 safe)."""
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
    if alpha is not None:
        if _set_socket(bsdf, ("Alpha",), float(alpha)):
            try:
                material.blend_method = "BLEND"
            except (AttributeError, TypeError):
                pass
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return material


def _emission_material(name, color, strength=20.0):
    """Get or rebuild an Emission material (stable across Blender versions)."""
    material = bpy.data.materials.get(name)
    if material is None:
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


def _volume_material(name, color, density):
    """Get or rebuild a Principled Volume material with a scatter fallback."""
    material = bpy.data.materials.get(name)
    if material is None:
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
        _set_socket(scatter, ("Color",), (color[0], color[1], color[2], 1.0))
        _set_socket(scatter, ("Density",), float(density))
        tree.links.new(scatter.outputs["Volume"], output.inputs["Volume"])
        volume_type = "VOLUME_SCATTER"
    return material, volume_type


def _ensure_world_background(color, strength):
    """Reuse the scene World with a flat Background color (non-destructive)."""
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
    _set_socket(background, ("Color",), (color[0], color[1], color[2], 1.0))
    _set_socket(background, ("Strength",), float(strength))
    if "Background" in background.outputs and "Surface" in output.inputs:
        if not any(link.from_node == background and link.to_node == output
                   for link in tree.links):
            tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    return world


def _create_sun(name, color, energy, elevation_deg, azimuth_deg, distance=30.0):
    """Create a SUN light aimed at the origin from an elevation/azimuth."""
    elevation = math.radians(elevation_deg)
    azimuth = math.radians(azimuth_deg % 360.0)
    direction = Vector((
        math.cos(elevation) * math.cos(azimuth),
        math.cos(elevation) * math.sin(azimuth),
        math.sin(elevation),
    ))
    light_data = bpy.data.lights.new(name=name, type="SUN")
    light_data.energy = float(energy)
    light_data.color = (color[0], color[1], color[2])
    sun_obj = bpy.data.objects.new(name=name, object_data=light_data)
    _link_object(sun_obj)
    sun_obj.location = direction * distance
    sun_obj.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    return sun_obj


def _update_view_layer():
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Rain
# ---------------------------------------------------------------------------

def create_rain_system(server, name="Rain", count=500, area=10.0, seed=0) -> dict:
    """Create one mesh of deterministic falling rain streaks over a square area."""
    _ = server
    clean_name = _require_name(name)
    count = _require_int(count, "count", minimum=1, maximum=20000)
    area = _require_positive(area, "area")
    seed = _require_seed(seed)

    rng = random.Random(seed)
    half = area / 2.0
    verts = []
    edges = []
    for i in range(count):
        x = rng.uniform(-half, half)
        y = rng.uniform(-half, half)
        top_z = rng.uniform(_RAIN_STREAK_LENGTH, _RAIN_HEIGHT)
        slant_x = rng.uniform(-0.05, 0.05)
        slant_y = rng.uniform(-0.02, 0.02)
        verts.append((x, y, top_z))
        verts.append((x + slant_x, y + slant_y, top_z - _RAIN_STREAK_LENGTH))
        edges.append((2 * i, 2 * i + 1))

    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    mesh.from_pydata(verts, edges, [])
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)

    material = _principled_material(
        clean_name + "_Rain", (0.65, 0.75, 0.9), roughness=0.05, alpha=0.5)
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    _update_view_layer()

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "count": count,
        "area": area,
        "height": _RAIN_HEIGHT,
        "streak_length": _RAIN_STREAK_LENGTH,
        "dimensions": [round(area, 6), round(area, 6), round(_RAIN_HEIGHT, 6)],
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Snow
# ---------------------------------------------------------------------------

def create_snow_system(server, name="Snow", count=500, area=10.0, seed=0) -> dict:
    """Create one mesh of deterministic snow-flake quads over a square area."""
    _ = server
    clean_name = _require_name(name)
    count = _require_int(count, "count", minimum=1, maximum=20000)
    area = _require_positive(area, "area")
    seed = _require_seed(seed)

    rng = random.Random(seed)
    half = area / 2.0
    half_flake = _SNOW_FLAKE_SIZE / 2.0
    verts = []
    faces = []
    for i in range(count):
        x = rng.uniform(-half, half)
        y = rng.uniform(-half, half)
        z = rng.uniform(0.05, _SNOW_HEIGHT)
        base = 4 * i
        verts.extend([
            (x - half_flake, y - half_flake, z),
            (x + half_flake, y - half_flake, z),
            (x + half_flake, y + half_flake, z),
            (x - half_flake, y + half_flake, z),
        ])
        faces.append((base, base + 1, base + 2, base + 3))

    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(clean_name, mesh)
    _link_object(obj)

    material = _principled_material(
        clean_name + "_Snow", (0.95, 0.96, 1.0), roughness=0.5)
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    _update_view_layer()

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "count": count,
        "area": area,
        "height": _SNOW_HEIGHT,
        "flake_size": _SNOW_FLAKE_SIZE,
        "dimensions": [round(area, 6), round(area, 6), round(_SNOW_HEIGHT, 6)],
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Lightning
# ---------------------------------------------------------------------------

def create_lightning_rig(server, name="Lightning", location=(0.0, 0.0, 5.0), energy=1000.0) -> dict:
    """Create a flash light plus an emissive zigzag bolt mesh striking the ground."""
    _ = server
    clean_name = _require_name(name)
    loc = _require_vector3(location, "location")
    energy = _require_non_negative(energy, "energy")

    seed = int(abs(loc[0] * 13.7 + loc[1] * 71.3 + loc[2] * 17.1 + energy * 0.001) * 1000) % 2147483647
    rng = random.Random(seed)
    segments = 10
    top = Vector(loc)
    base = Vector((loc[0] + rng.uniform(-0.5, 0.5),
                   loc[1] + rng.uniform(-0.5, 0.5), 0.0))
    path = []
    for i in range(segments + 1):
        t = i / segments
        point = top.lerp(base, t)
        envelope = 4.0 * t * (1.0 - t)
        if 0 < i < segments:
            point = point + Vector((rng.uniform(-0.35, 0.35) * envelope,
                                    rng.uniform(-0.35, 0.35) * envelope, 0.0))
        path.append(point)

    half_width = 0.05
    verts = []
    for point in path:
        verts.append((point.x - half_width, point.y, point.z))
        verts.append((point.x + half_width, point.y, point.z))
    faces = []
    for i in range(segments):
        a = 2 * i
        faces.append((a, a + 1, a + 3, a + 2))
    mesh = bpy.data.meshes.new(clean_name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    bolt = bpy.data.objects.new(clean_name + "_Bolt", mesh)
    _link_object(bolt)

    emission_strength = max(1.0, float(energy) / 50.0)
    material = _emission_material(
        clean_name + "_Bolt", (0.8, 0.85, 1.0), strength=emission_strength)
    if material.name not in bolt.data.materials:
        bolt.data.materials.append(material)

    light_data = bpy.data.lights.new(name=clean_name + "_Flash", type="POINT")
    light_data.energy = float(energy)
    light_data.color = (0.8, 0.85, 1.0)
    flash = bpy.data.objects.new(clean_name + "_Flash", light_data)
    _link_object(flash)
    flash.location = Vector(loc)
    _update_view_layer()

    return {
        "success": True,
        "name": clean_name,
        "light": flash.name,
        "bolt": bolt.name,
        "material": material.name,
        "location": [round(c, 6) for c in loc],
        "energy": energy,
        "emission_strength": round(emission_strength, 6),
        "bolt_segments": segments,
        "bolt_vertex_count": len(mesh.vertices),
        "bolt_face_count": len(mesh.polygons),
        "dimensions": [round(1.0, 6), round(1.0, 6), round(max(loc[2], 0.0), 6)],
    }


# ---------------------------------------------------------------------------
# Wind
# ---------------------------------------------------------------------------

def create_wind_field(server, name="Wind", strength=1.0, direction=(1.0, 0.0, 0.0)) -> dict:
    """Create a WIND force-field empty oriented along `direction`."""
    _ = server
    clean_name = _require_name(name)
    strength = _require_number(strength, "strength")
    raw_direction = _require_vector3(direction, "direction")

    flow = Vector(raw_direction)
    if flow.length < 1e-9:
        raise ValueError(f"direction must be a non-zero vector (got {direction!r})")
    flow.normalize()

    try:
        bpy.ops.object.effector_add(type="WIND", location=(0.0, 0.0, 0.0))
    except (RuntimeError, TypeError) as exc:
        raise ValueError(f"Could not create WIND field: {exc}") from None
    obj = bpy.context.object
    if obj is None:
        raise ValueError("Could not create WIND field")
    obj.name = clean_name
    field = getattr(obj, "field", None)
    if field is None:
        raise ValueError(f"Object '{clean_name}' does not support force fields")
    field.strength = float(strength)
    # Wind flows along the object's local +Z; align +Z with the direction.
    obj.rotation_euler = flow.to_track_quat("Z", "Y").to_euler()
    for attr, value in (("empty_display_type", "SINGLE_ARROW"),
                        ("empty_display_size", 1.0)):
        try:
            setattr(obj, attr, value)
        except (AttributeError, TypeError):
            pass
    _update_view_layer()

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "field_type": field.type,
        "strength": float(strength),
        "direction": [round(c, 6) for c in flow],
        "flow_axis": "+Z",
        "rotation": [round(math.degrees(a), 6) for a in obj.rotation_euler],
    }


# ---------------------------------------------------------------------------
# Atmospheric haze
# ---------------------------------------------------------------------------

def create_atmospheric_haze(server, density=0.01, color=(0.8, 0.85, 0.9)) -> dict:
    """Create a large volume cube with an atmospheric haze material."""
    _ = server
    density = _require_non_negative(density, "density")
    rgb = _require_color3(color)

    half = _HAZE_SIZE / 2.0
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
    mesh = bpy.data.meshes.new("AtmosphericHazeMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("AtmosphericHaze", mesh)
    _link_object(obj)

    material, volume_type = _volume_material(
        "AtmosphericHazeMat", rgb, density)
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    _update_view_layer()

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "material": material.name,
        "volume_type": volume_type,
        "size": _HAZE_SIZE,
        "dimensions": [round(_HAZE_SIZE, 6), round(_HAZE_SIZE, 6), round(_HAZE_SIZE, 6)],
        "density": density,
        "color": [round(c, 6) for c in rgb],
    }


# ---------------------------------------------------------------------------
# Sunset / night lighting
# ---------------------------------------------------------------------------

def create_sunset_lighting(server) -> dict:
    """Create a warm sunset world background plus a low warm sun light."""
    _ = server
    sky_color = [1.0, 0.42, 0.18]
    world = _ensure_world_background(sky_color, 1.0)
    sun = _create_sun("SunsetSun", (1.0, 0.55, 0.3), 3.0, 12.0, 250.0)
    _update_view_layer()

    return {
        "success": True,
        "world": world.name,
        "sun": sun.name,
        "sky_color": [round(c, 6) for c in sky_color],
        "sky_strength": 1.0,
        "sun_color": [1.0, 0.55, 0.3],
        "sun_energy": 3.0,
        "sun_elevation": 12.0,
        "sun_azimuth": 250.0,
        "sun_location": [round(c, 6) for c in sun.location],
    }


def create_night_lighting(server, moon_energy=0.5) -> dict:
    """Create a dark night world plus a cool moon (SUN) light and ambient."""
    _ = server
    moon_energy = _require_non_negative(moon_energy, "moon_energy")

    sky_color = [0.008, 0.012, 0.03]
    world = _ensure_world_background(sky_color, 0.4)
    moon = _create_sun("MoonLight", (0.65, 0.75, 1.0), moon_energy, 55.0, 60.0)
    _update_view_layer()

    return {
        "success": True,
        "world": world.name,
        "moon": moon.name,
        "sky_color": [round(c, 6) for c in sky_color],
        "sky_strength": 0.4,
        "moon_color": [0.65, 0.75, 1.0],
        "moon_energy": moon_energy,
        "moon_location": [round(c, 6) for c in moon.location],
    }


# ---------------------------------------------------------------------------
# Weather scene composition
# ---------------------------------------------------------------------------

_WEATHER_PRESETS = {
    "rain": {
        "world_color": (0.45, 0.5, 0.55),
        "world_strength": 0.9,
        "sun_color": (0.7, 0.75, 0.85),
        "sun_energy": 1.5,
        "elevation": 60.0,
        "azimuth": 135.0,
    },
    "snow": {
        "world_color": (0.7, 0.78, 0.88),
        "world_strength": 1.0,
        "sun_color": (0.9, 0.93, 1.0),
        "sun_energy": 2.0,
        "elevation": 45.0,
        "azimuth": 135.0,
    },
    "clear": {
        "world_color": (0.35, 0.55, 0.9),
        "world_strength": 1.0,
        "sun_color": (1.0, 0.8, 0.6),
        "sun_energy": 4.0,
        "elevation": 35.0,
        "azimuth": 135.0,
    },
}


def _fallback_ground(name, size):
    """Minimal grass quad at Z=0 used when server.create_ground is missing."""
    half = size / 2.0
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(
        [(-half, -half, 0.0), (half, -half, 0.0),
         (half, half, 0.0), (-half, half, 0.0)],
        [], [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    _link_object(obj)
    material = _principled_material(
        name + "_Ground", (0.16, 0.36, 0.10), roughness=0.9)
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    return obj


def create_weather_scene(server, weather="rain", size=10.0, seed=0) -> dict:
    """Compose ground, sky, precipitation and lighting for one weather type."""
    if not isinstance(weather, str):
        raise ValueError(f"weather must be a string (got {weather!r})")
    key = weather.strip().lower()
    if key not in _WEATHER_PRESETS:
        raise ValueError(
            f"Unknown weather '{weather}'. Expected one of {sorted(_WEATHER_PRESETS)}"
        )
    size = _require_positive(size, "size")
    seed = _require_seed(seed)
    preset = _WEATHER_PRESETS[key]

    make_ground = getattr(server, "create_ground", None) if server is not None else None
    ground_name = None
    if callable(make_ground):
        try:
            result = make_ground(name="WeatherGround", size=size,
                                 subdivisions=16, style="grass", seed=seed)
            if isinstance(result, dict):
                ground_name = result.get("object") or result.get("name")
        except Exception:
            ground_name = None
    if ground_name is None or bpy.data.objects.get(ground_name) is None:
        ground_name = _fallback_ground("WeatherGround", size).name

    world = _ensure_world_background(
        list(preset["world_color"]), preset["world_strength"])
    sun = _create_sun("WeatherSun", list(preset["sun_color"]),
                      preset["sun_energy"], preset["elevation"], preset["azimuth"])

    precipitation = None
    precip_count = 0
    if key == "rain":
        precip_count = max(100, min(5000, int(size * size * 5)))
        result = create_rain_system(server, name="WeatherRain",
                                    count=precip_count, area=size, seed=seed)
        precipitation = result["object"]
    elif key == "snow":
        precip_count = max(100, min(5000, int(size * size * 5)))
        result = create_snow_system(server, name="WeatherSnow",
                                    count=precip_count, area=size, seed=seed)
        precipitation = result["object"]

    _update_view_layer()
    components = [ground_name, sun.name]
    if precipitation is not None:
        components.append(precipitation)

    return {
        "success": True,
        "name": "WeatherScene",
        "weather": key,
        "size": size,
        "seed": seed,
        "ground": ground_name,
        "precipitation": precipitation,
        "precip_count": precip_count,
        "sun": sun.name,
        "world": world.name,
        "components": components,
        "dimensions": [round(size, 6), round(size, 6), round(_RAIN_HEIGHT, 6)],
    }
