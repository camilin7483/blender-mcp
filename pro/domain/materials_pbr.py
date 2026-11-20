"""Physically based procedural materials and face assignment helpers."""

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


def _as_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    return value


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


def _nodes_dict(material):
    return {node.name: node.bl_idname for node in material.node_tree.nodes}


def create_metal_material(server, name="Metal", color=(0.7, 0.7, 0.75, 1.0),
                          roughness=0.25) -> dict:
    """Create a metallic Principled BSDF material."""
    name = _validate_name(name)
    color = _validate_color(color)
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (400.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (100.0, 0.0)
    _set_socket(bsdf, ("Base Color",), color)
    _set_socket(bsdf, ("Metallic",), 1.0)
    _set_socket(bsdf, ("Roughness",), roughness)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "roughness": roughness,
        "metallic": 1.0,
    }


def create_wood_material(server, name="Wood",
                         light_color=(0.45, 0.28, 0.14, 1.0),
                         dark_color=(0.20, 0.10, 0.05, 1.0),
                         scale=4.0) -> dict:
    """Create a wood-grain material from noise texture and color ramp."""
    name = _validate_name(name)
    light_color = _validate_color(light_color, "light_color")
    dark_color = _validate_color(dark_color, "dark_color")
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=0.001, maximum=1000.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (500.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (200.0, 0.0)
    mapping = _add_coordinates(tree, scale)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Wood Noise"
    noise.location = (-300.0, 0.0)
    wave = tree.nodes.new(type="ShaderNodeTexWave")
    wave.name = "Wood Grain"
    wave.location = (-100.0, 100.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.name = "Wood Colors"
    ramp.location = (0.0, 100.0)
    _set_socket(noise, ("Scale",), scale)
    _set_socket(noise, ("Detail",), 2.0)
    _set_socket(wave, ("Scale",), scale)
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = dark_color
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = light_color
    bump = _add_bump(tree, wave.outputs["Fac"], strength=0.15)

    links = tree.links
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], wave.inputs["Vector"])
    links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    base_socket = _find_input(bsdf, ("Base Color",))
    if base_socket is not None:
        links.new(ramp.outputs["Color"], base_socket)
    normal_socket = _find_input(bsdf, ("Normal",))
    if normal_socket is not None:
        links.new(bump.outputs["Normal"], normal_socket)
    _set_socket(bsdf, ("Roughness",), 0.6)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "light_color": list(light_color),
        "dark_color": list(dark_color),
        "scale": scale,
    }


def create_fabric_material(server, name="Fabric",
                           color=(0.2, 0.3, 0.5, 1.0),
                           roughness=0.8, sheen=0.3) -> dict:
    """Create a rough fabric material with sheen and subtle noise bump."""
    name = _validate_name(name)
    color = _validate_color(color)
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)
    sheen = _check_range(_as_number(sheen, "sheen"), "sheen", 0.0, 1.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (500.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (200.0, 0.0)
    mapping = _add_coordinates(tree, 20.0)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Fabric Noise"
    noise.location = (-300.0, -100.0)
    _set_socket(noise, ("Scale",), 20.0)
    _set_socket(noise, ("Detail",), 2.0)
    bump = _add_bump(tree, noise.outputs["Fac"], strength=0.05)

    _set_socket(bsdf, ("Base Color",), color)
    _set_socket(bsdf, ("Roughness",), roughness)
    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Sheen Weight", "Sheen"), sheen)
    _set_socket(bsdf, ("Sheen Roughness",), 0.5)

    links = tree.links
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    normal_socket = _find_input(bsdf, ("Normal",))
    if normal_socket is not None:
        links.new(bump.outputs["Normal"], normal_socket)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "roughness": roughness,
        "sheen": sheen,
    }


def create_glass_material(server, name="Glass",
                          color=(0.8, 0.9, 1.0, 1.0), roughness=0.05,
                          ior=1.45) -> dict:
    """Create a transmissive glass material with IOR control."""
    name = _validate_name(name)
    color = _validate_color(color)
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)
    ior = _as_number(ior, "ior")
    _check_range(ior, "ior", minimum=1.0, maximum=3.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (400.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (100.0, 0.0)
    _set_socket(bsdf, ("Base Color",), color)
    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Roughness",), roughness)
    _set_socket(bsdf, ("IOR",), ior)
    _set_socket(bsdf, ("Transmission Weight", "Transmission"), 1.0)
    _set_socket(bsdf, ("Alpha",), color[3])
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "roughness": roughness,
        "ior": ior,
        "transmission": 1.0,
    }


def create_skin_material(server, name="Skin",
                         color=(0.65, 0.45, 0.35, 1.0),
                         subsurface=0.15, roughness=0.45) -> dict:
    """Create a skin material with subsurface scattering."""
    name = _validate_name(name)
    color = _validate_color(color)
    subsurface = _check_range(
        _as_number(subsurface, "subsurface"), "subsurface", 0.0, 1.0)
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (400.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (100.0, 0.0)
    _set_socket(bsdf, ("Base Color",), color)
    _set_socket(bsdf, ("Roughness",), roughness)
    _set_socket(bsdf, ("Metallic",), 0.0)
    _set_socket(bsdf, ("Subsurface Weight", "Subsurface"), subsurface)
    _set_socket(bsdf, ("Subsurface Radius",), (1.0, 0.35, 0.2))
    _set_socket(bsdf, ("Subsurface Color",), color)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "subsurface": subsurface,
        "roughness": roughness,
    }


def create_concrete_material(server, name="Concrete",
                             color=(0.5, 0.5, 0.5, 1.0),
                             roughness=0.8, scale=8.0) -> dict:
    """Create a concrete material with noise color variation and bump."""
    name = _validate_name(name)
    color = _validate_color(color)
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=0.001, maximum=1000.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (500.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (200.0, 0.0)
    mapping = _add_coordinates(tree, scale)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Concrete Noise"
    noise.location = (-300.0, 0.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.name = "Concrete Variation"
    ramp.location = (-100.0, 100.0)
    _set_socket(noise, ("Scale",), scale)
    _set_socket(noise, ("Detail",), 3.0)
    variation = 0.08
    base_rgb = list(color[:3])
    dark = [max(0.0, min(1.0, channel - variation)) for channel in base_rgb]
    light = [max(0.0, min(1.0, channel + variation)) for channel in base_rgb]
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = tuple(dark) + (color[3],)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = tuple(light) + (color[3],)
    bump = _add_bump(tree, noise.outputs["Fac"], strength=0.3)

    _set_socket(bsdf, ("Roughness",), roughness)
    _set_socket(bsdf, ("Metallic",), 0.0)
    links = tree.links
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    base_socket = _find_input(bsdf, ("Base Color",))
    if base_socket is not None:
        links.new(ramp.outputs["Color"], base_socket)
    normal_socket = _find_input(bsdf, ("Normal",))
    if normal_socket is not None:
        links.new(bump.outputs["Normal"], normal_socket)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "roughness": roughness,
        "scale": scale,
    }


def create_emission_material(server, name="Emission",
                             color=(1.0, 0.8, 0.4, 1.0),
                             strength=5.0) -> dict:
    """Create an emissive material with color and strength control."""
    name = _validate_name(name)
    color = _validate_color(color)
    strength = _as_number(strength, "strength")
    _check_range(strength, "strength", minimum=0.0, maximum=1000000.0)

    material = _get_or_create_material(name)
    tree = material.node_tree
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (400.0, 0.0)
    emission = tree.nodes.new(type="ShaderNodeEmission")
    emission.name = "Emission"
    emission.location = (100.0, 0.0)
    emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = strength
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])

    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color": list(color),
        "strength": strength,
    }


def assign_material_to_faces(server, object_name, material_name,
                             face_indices=None) -> dict:
    """Assign a material to selected faces (or the whole mesh)."""
    if not isinstance(object_name, str) or not object_name.strip():
        raise ValueError("object_name must be a non-empty string.")
    if not isinstance(material_name, str) or not material_name.strip():
        raise ValueError("material_name must be a non-empty string.")
    object_name = object_name.strip()
    material_name = material_name.strip()

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found.")
    if obj.type != "MESH" or obj.data is None:
        raise ValueError(f"Object '{obj.name}' is not a mesh object.")
    material = bpy.data.materials.get(material_name)
    if material is None:
        raise ValueError(f"Material '{material_name}' not found.")

    mesh = obj.data
    face_count = len(mesh.polygons)
    if face_indices is None:
        targets = list(range(face_count))
    else:
        if not isinstance(face_indices, (list, tuple)):
            raise ValueError("face_indices must be a list or tuple of integers, or None.")
        if len(face_indices) == 0:
            raise ValueError("face_indices must contain at least one index.")
        seen = set()
        targets = []
        for item in face_indices:
            index = _as_int(item, "face_indices entries")
            if index < 0 or index >= face_count:
                raise ValueError(
                    f"face index {index} out of range [0, {face_count - 1}]."
                )
            if index not in seen:
                seen.add(index)
                targets.append(index)

    slot_index = -1
    for position, slot_material in enumerate(mesh.materials):
        if slot_material is not None and slot_material.name == material.name:
            slot_index = position
            break
    if slot_index < 0:
        mesh.materials.append(material)
        slot_index = len(mesh.materials) - 1

    for index in targets:
        mesh.polygons[index].material_index = slot_index
    try:
        obj.active_material_index = slot_index
    except Exception:
        pass

    return {
        "success": True,
        "object": obj.name,
        "material": material.name,
        "slot_index": slot_index,
        "assigned_count": len(targets),
        "face_count": face_count,
        "nodes": _nodes_dict(material) if material.use_nodes and material.node_tree else {},
    }
