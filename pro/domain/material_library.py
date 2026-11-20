"""Procedural architectural/elemental material library."""

import math

import bpy


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


def _check_range(value, label, minimum=None, maximum=None):
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum}.")
    return value


def _validate_color(color, label="color"):
    if not isinstance(color, (list, tuple)) or len(color) not in (3, 4):
        raise ValueError(
            f"{label} must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1]."
        )
    channels = []
    for channel in color:
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            raise ValueError(
                f"{label} must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1]."
            )
        value = float(channel)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(
                f"{label} must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1]."
            )
        channels.append(value)
    if len(channels) == 3:
        channels.append(1.0)
    return tuple(channels)


def _find_input(node, names):
    for candidate in names:
        socket = node.inputs.get(candidate)
        if socket is not None:
            return socket
    return None


def _set_socket(node, names, value):
    socket = _find_input(node, names)
    if socket is not None:
        socket.default_value = value


def _get_or_create_material(name):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)
    return material


def _add_coordinates(tree, scale):
    tex_coord = tree.nodes.new(type="ShaderNodeTexCoord")
    tex_coord.name = "Texture Coordinate"
    tex_coord.location = (-700.0, 0.0)
    mapping = tree.nodes.new(type="ShaderNodeMapping")
    mapping.name = "Mapping"
    mapping.location = (-500.0, 0.0)
    scale_socket = mapping.inputs.get("Scale")
    if scale_socket is not None:
        try:
            scale_socket.default_value = (scale, scale, scale)
        except Exception:
            pass
    tree.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    return mapping


def _add_bump(tree, height_output, location=(-100.0, -200.0),
              strength=0.2, distance=0.1):
    bump = tree.nodes.new(type="ShaderNodeBump")
    bump.name = "Procedural Bump"
    bump.location = location
    _set_socket(bump, ("Strength",), strength)
    _set_socket(bump, ("Distance",), distance)
    tree.links.new(height_output, bump.inputs["Height"])
    return bump


def _finish(tree, bsdf, bump=None):
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (500.0, 0.0)
    links = tree.links
    if bump is not None:
        normal_socket = _find_input(bsdf, ("Normal",))
        if normal_socket is not None:
            links.new(bump.outputs["Normal"], normal_socket)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])


def _nodes_dict(material):
    return {node.name: node.bl_idname for node in material.node_tree.nodes}


def _new_bsdf(tree, location=(200.0, 0.0)):
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = location
    return bsdf


def create_marble_material(server, name="Marble",
                           color=(0.85, 0.85, 0.82, 1.0),
                           vein_color=(0.25, 0.25, 0.28, 1.0),
                           scale=3.0) -> dict:
    """Create a polished marble material with noise-distorted wave veins."""
    name = _validate_name(name)
    color = _validate_color(color, "color")
    vein_color = _validate_color(vein_color, "vein_color")
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=0.001, maximum=1000.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    bsdf = _new_bsdf(tree)
    mapping = _add_coordinates(tree, scale)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Marble Distortion"
    noise.location = (-300.0, -100.0)
    wave = tree.nodes.new(type="ShaderNodeTexWave")
    wave.name = "Marble Veins"
    wave.location = (-100.0, 50.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.name = "Marble Colors"
    ramp.location = (0.0, 100.0)
    _set_socket(noise, ("Scale",), scale)
    _set_socket(noise, ("Detail",), 3.0)
    _set_socket(wave, ("Scale",), scale * 2.0)
    _set_socket(wave, ("Distortion",), 2.5)
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = vein_color
    ramp.color_ramp.elements[1].position = 0.55
    ramp.color_ramp.elements[1].color = color
    bump = _add_bump(tree, wave.outputs["Fac"], strength=0.05)

    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Roughness",), 0.15)
    _set_socket(bsdf, ("Specular IOR Level", "Specular"), 0.6)

    links = tree.links
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], wave.inputs["Vector"])
    links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    base_socket = _find_input(bsdf, ("Base Color",))
    if base_socket is not None:
        links.new(ramp.outputs["Color"], base_socket)
    _finish(tree, bsdf, bump)

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "vein_color": list(vein_color),
        "scale": scale,
        "roughness": 0.15,
    }


def create_brick_material(server, name="Brick",
                          color=(0.45, 0.16, 0.10, 1.0),
                          mortar_color=(0.75, 0.75, 0.72, 1.0),
                          scale=8.0) -> dict:
    """Create a brick material with mortar joints and bump relief."""
    name = _validate_name(name)
    color = _validate_color(color, "color")
    mortar_color = _validate_color(mortar_color, "mortar_color")
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=0.001, maximum=1000.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    bsdf = _new_bsdf(tree)
    mapping = _add_coordinates(tree, scale)
    brick = tree.nodes.new(type="ShaderNodeTexBrick")
    brick.name = "Brick Pattern"
    brick.location = (-200.0, 50.0)
    _set_socket(brick, ("Color1",), color)
    _set_socket(brick, ("Color2",), color)
    _set_socket(brick, ("Mortar",), mortar_color)
    _set_socket(brick, ("Scale",), scale)
    _set_socket(brick, ("Mortar Size",), 0.02)
    _set_socket(brick, ("Mortar Smooth",), 0.1)
    mortar_socket = brick.outputs.get("Fac")
    if mortar_socket is None:
        mortar_socket = brick.outputs["Color"]
    bump = _add_bump(tree, mortar_socket, strength=0.5)

    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Roughness",), 0.8)
    links = tree.links
    links.new(mapping.outputs["Vector"], brick.inputs["Vector"])
    base_socket = _find_input(bsdf, ("Base Color",))
    if base_socket is not None:
        links.new(brick.outputs["Color"], base_socket)
    _finish(tree, bsdf, bump)

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "mortar_color": list(mortar_color),
        "scale": scale,
        "roughness": 0.8,
    }


def create_asphalt_material(server, name="Asphalt",
                            color=(0.08, 0.08, 0.09, 1.0),
                            roughness=0.9) -> dict:
    """Create a dark rough asphalt material with noise bump grain."""
    name = _validate_name(name)
    color = _validate_color(color, "color")
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    bsdf = _new_bsdf(tree)
    mapping = _add_coordinates(tree, 15.0)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Asphalt Grain"
    noise.location = (-300.0, 0.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.name = "Asphalt Variation"
    ramp.location = (-100.0, 100.0)
    _set_socket(noise, ("Scale",), 15.0)
    _set_socket(noise, ("Detail",), 4.0)
    _set_socket(noise, ("Roughness",), 0.7)
    variation = 0.03
    base_rgb = list(color[:3])
    dark = [max(0.0, min(1.0, c - variation)) for c in base_rgb]
    light = [max(0.0, min(1.0, c + variation * 2.0)) for c in base_rgb]
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = tuple(dark) + (color[3],)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = tuple(light) + (color[3],)
    bump = _add_bump(tree, noise.outputs["Fac"], strength=0.4)

    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Roughness",), roughness)
    links = tree.links
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    base_socket = _find_input(bsdf, ("Base Color",))
    if base_socket is not None:
        links.new(ramp.outputs["Color"], base_socket)
    _finish(tree, bsdf, bump)

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "roughness": roughness,
    }


def create_grass_material(server, name="Grass",
                          color=(0.12, 0.35, 0.08, 1.0),
                          scale=12.0) -> dict:
    """Create a green grass material with noise blade variation and bump."""
    name = _validate_name(name)
    color = _validate_color(color, "color")
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=0.001, maximum=1000.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    bsdf = _new_bsdf(tree)
    mapping = _add_coordinates(tree, scale)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Grass Variation"
    noise.location = (-300.0, 0.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.name = "Grass Colors"
    ramp.location = (-100.0, 100.0)
    _set_socket(noise, ("Scale",), scale)
    _set_socket(noise, ("Detail",), 3.0)
    variation = 0.12
    base_rgb = list(color[:3])
    dark = [max(0.0, min(1.0, c - variation)) for c in base_rgb]
    light = [max(0.0, min(1.0, c + variation)) for c in base_rgb]
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = tuple(dark) + (color[3],)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = tuple(light) + (color[3],)
    bump = _add_bump(tree, noise.outputs["Fac"], strength=0.25)

    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Roughness",), 0.85)
    _set_socket(bsdf, ("Sheen Weight", "Sheen"), 0.2)
    links = tree.links
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    base_socket = _find_input(bsdf, ("Base Color",))
    if base_socket is not None:
        links.new(ramp.outputs["Color"], base_socket)
    _finish(tree, bsdf, bump)

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "scale": scale,
        "roughness": 0.85,
    }


def create_sand_material(server, name="Sand",
                         color=(0.76, 0.65, 0.45, 1.0),
                         scale=10.0) -> dict:
    """Create a sand material with fine noise color variation and bump."""
    name = _validate_name(name)
    color = _validate_color(color, "color")
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=0.001, maximum=1000.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    bsdf = _new_bsdf(tree)
    mapping = _add_coordinates(tree, scale)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Sand Grain"
    noise.location = (-300.0, 0.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.name = "Sand Variation"
    ramp.location = (-100.0, 100.0)
    _set_socket(noise, ("Scale",), scale * 4.0)
    _set_socket(noise, ("Detail",), 4.0)
    variation = 0.07
    base_rgb = list(color[:3])
    dark = [max(0.0, min(1.0, c - variation)) for c in base_rgb]
    light = [max(0.0, min(1.0, c + variation)) for c in base_rgb]
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = tuple(dark) + (color[3],)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = tuple(light) + (color[3],)
    bump = _add_bump(tree, noise.outputs["Fac"], strength=0.1)

    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Roughness",), 0.9)
    links = tree.links
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    base_socket = _find_input(bsdf, ("Base Color",))
    if base_socket is not None:
        links.new(ramp.outputs["Color"], base_socket)
    _finish(tree, bsdf, bump)

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "scale": scale,
        "roughness": 0.9,
    }


def create_rust_material(server, name="Rust",
                         color=(0.35, 0.12, 0.05, 1.0),
                         scale=6.0) -> dict:
    """Create a corroded rust material with musgrave patch variation."""
    name = _validate_name(name)
    color = _validate_color(color, "color")
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=0.001, maximum=1000.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    bsdf = _new_bsdf(tree)
    mapping = _add_coordinates(tree, scale)
    musgrave = tree.nodes.new(type="ShaderNodeTexNoise")
    musgrave.name = "Rust Patches"
    musgrave.location = (-300.0, 0.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.name = "Rust Colors"
    ramp.location = (-100.0, 100.0)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Rust Grain"
    noise.location = (-300.0, -250.0)
    _set_socket(musgrave, ("Scale",), scale)
    _set_socket(musgrave, ("Detail",), 3.0)
    _set_socket(musgrave, ("Roughness",), 0.6)
    _set_socket(noise, ("Scale",), scale * 5.0)
    _set_socket(noise, ("Detail",), 2.0)
    base_rgb = list(color[:3])
    dark = [max(0.0, min(1.0, c * 0.5)) for c in base_rgb]
    light = [max(0.0, min(1.0, c + 0.25)) for c in base_rgb]
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = tuple(dark) + (color[3],)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = tuple(light) + (color[3],)
    bump = _add_bump(tree, noise.outputs["Fac"], strength=0.5)

    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Roughness",), 0.95)
    links = tree.links
    links.new(mapping.outputs["Vector"], musgrave.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(musgrave.outputs["Fac"], ramp.inputs["Fac"])
    base_socket = _find_input(bsdf, ("Base Color",))
    if base_socket is not None:
        links.new(ramp.outputs["Color"], base_socket)
    _finish(tree, bsdf, bump)

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "scale": scale,
        "metallic": 0.0,
        "roughness": 0.95,
    }


def create_chrome_material(server, name="Chrome",
                           roughness=0.05) -> dict:
    """Create a polished chrome material with full metal and low roughness."""
    name = _validate_name(name)
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    bsdf = _new_bsdf(tree, location=(100.0, 0.0))
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (400.0, 0.0)

    _set_socket(bsdf, ("Base Color",), (1.0, 1.0, 1.0, 1.0))
    _set_socket(bsdf, ("Metallic",), 1.0)
    _set_socket(bsdf, ("Roughness",), roughness)
    _set_socket(bsdf, ("IOR",), 1.45)
    _set_socket(bsdf, ("Specular IOR Level", "Specular"), 1.0)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "roughness": roughness,
        "metallic": 1.0,
    }


def create_ceramic_material(server, name="Ceramic",
                            color=(0.9, 0.9, 0.88, 1.0),
                            roughness=0.15) -> dict:
    """Create a glossy glazed ceramic material with clearcoat when available."""
    name = _validate_name(name)
    color = _validate_color(color, "color")
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    bsdf = _new_bsdf(tree, location=(100.0, 0.0))
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (400.0, 0.0)

    _set_socket(bsdf, ("Base Color",), color)
    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Roughness",), roughness)
    _set_socket(bsdf, ("IOR",), 1.45)
    _set_socket(bsdf, ("Specular IOR Level", "Specular"), 0.6)
    _set_socket(bsdf, ("Coat Weight", "Clearcoat"), 1.0)
    _set_socket(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.05)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "roughness": roughness,
    }
