"""Procedural materials and UV utilities."""

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


def _validate_color(color):
    if not isinstance(color, (list, tuple)) or len(color) not in (3, 4):
        raise ValueError("base_color must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1].")
    channels = []
    for channel in color:
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            raise ValueError("base_color must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1].")
        value = float(channel)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("base_color must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1].")
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


def _get_mesh_object(object_name):
    if not isinstance(object_name, str) or not object_name.strip():
        raise ValueError("object_name must be a non-empty string.")
    cleaned = object_name.strip()
    obj = bpy.data.objects.get(cleaned)
    if obj is None:
        raise ValueError(f"Object '{cleaned}' not found.")
    if obj.type != "MESH" or obj.data is None:
        raise ValueError(f"Object '{obj.name}' is not a mesh object.")
    return obj


def _set_object_mode():
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass


def _activate_for_uv(obj):
    _set_object_mode()
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _active_uv_layer_name(obj):
    layers = obj.data.uv_layers
    if len(layers) == 0:
        return layers.new(name="UVMap").name
    active = layers.active
    if active is None:
        layers.active_index = 0
        active = layers.active
    return active.name


def create_procedural_material(server, name="Procedural",
                               base_color=(0.6, 0.6, 0.6, 1.0), roughness=0.5,
                               metallic=0.0, noise_scale=5.0,
                               bump_strength=0.2, color_variation=0.1) -> dict:
    """Create a Principled BSDF material driven by noise color and bump."""
    name = _validate_name(name)
    base_color = _validate_color(base_color)
    roughness = _check_range(_as_number(roughness, "roughness"), "roughness", 0.0, 1.0)
    metallic = _check_range(_as_number(metallic, "metallic"), "metallic", 0.0, 1.0)
    noise_scale = _as_number(noise_scale, "noise_scale")
    _check_range(noise_scale, "noise_scale", minimum=0.001, maximum=1000.0)
    bump_strength = _as_number(bump_strength, "bump_strength")
    _check_range(bump_strength, "bump_strength", minimum=0.0, maximum=10.0)
    color_variation = _as_number(color_variation, "color_variation")
    _check_range(color_variation, "color_variation", minimum=0.0, maximum=1.0)

    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)

    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (500.0, 0.0)
    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (200.0, 0.0)
    tex_coord = tree.nodes.new(type="ShaderNodeTexCoord")
    tex_coord.name = "Texture Coordinate"
    tex_coord.location = (-700.0, 0.0)
    mapping = tree.nodes.new(type="ShaderNodeMapping")
    mapping.name = "Mapping"
    mapping.location = (-500.0, 0.0)
    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Procedural Noise"
    noise.location = (-300.0, 0.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.name = "Color Variation"
    ramp.location = (-100.0, 100.0)
    bump = tree.nodes.new(type="ShaderNodeBump")
    bump.name = "Procedural Bump"
    bump.location = (-100.0, -150.0)

    _set_socket(bsdf, ("Roughness",), roughness)
    _set_socket(bsdf, ("Metallic",), metallic)
    _set_socket(noise, ("Scale",), noise_scale)
    _set_socket(noise, ("Detail",), 2.0)
    _set_socket(bump, ("Strength",), bump_strength)

    base_rgb = list(base_color[:3])
    dark = [max(0.0, min(1.0, channel - color_variation)) for channel in base_rgb]
    light = [max(0.0, min(1.0, channel + color_variation)) for channel in base_rgb]
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = tuple(dark) + (base_color[3],)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = tuple(light) + (base_color[3],)

    links = tree.links
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    base_socket = _find_input(bsdf, ("Base Color",))
    if base_socket is not None:
        links.new(ramp.outputs["Color"], base_socket)
    normal_socket = _find_input(bsdf, ("Normal",))
    if normal_socket is not None:
        links.new(bump.outputs["Normal"], normal_socket)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    nodes = {node.name: node.bl_idname for node in tree.nodes}
    return {
        "success": True,
        "material": material.name,
        "nodes": nodes,
        "base_color": list(base_color),
        "roughness": roughness,
        "metallic": metallic,
        "noise_scale": noise_scale,
        "bump_strength": bump_strength,
        "color_variation": color_variation,
    }


def smart_uv_unwrap(server, object_name, angle_limit=66.0,
                    island_margin=0.02) -> dict:
    """Smart-UV-project a mesh object, restoring Object Mode afterwards."""
    obj = _get_mesh_object(object_name)
    angle_limit = _as_number(angle_limit, "angle_limit")
    _check_range(angle_limit, "angle_limit", minimum=0.0, maximum=89.0)
    island_margin = _as_number(island_margin, "island_margin")
    _check_range(island_margin, "island_margin", minimum=0.0, maximum=1.0)

    _activate_for_uv(obj)
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(
            angle_limit=float(angle_limit),
            island_margin=float(island_margin),
        )
    except Exception as exc:
        _set_object_mode()
        return {
            "success": False,
            "object": obj.name,
            "error": f"smart_project failed for '{obj.name}': {exc}",
        }
    _set_object_mode()
    uv_name = _active_uv_layer_name(obj)
    return {
        "success": True,
        "object": obj.name,
        "uv_layer": uv_name,
        "angle_limit": angle_limit,
        "island_margin": island_margin,
    }


def pack_uv_islands(server, object_name, margin=0.001) -> dict:
    """Pack the UV islands of a mesh object, restoring Object Mode afterwards."""
    obj = _get_mesh_object(object_name)
    margin = _as_number(margin, "margin")
    _check_range(margin, "margin", minimum=0.0, maximum=1.0)

    _activate_for_uv(obj)
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.pack_islands(margin=float(margin))
    except Exception as exc:
        _set_object_mode()
        return {
            "success": False,
            "object": obj.name,
            "error": f"pack_islands failed for '{obj.name}': {exc}",
        }
    _set_object_mode()
    uv_name = _active_uv_layer_name(obj)
    return {
        "success": True,
        "object": obj.name,
        "uv_layer": uv_name,
        "uv_layer_count": len(obj.data.uv_layers),
        "margin": margin,
    }


def list_materials(server, used_only=False) -> dict:
    """List materials with user counts, node types and usage flags."""
    if not isinstance(used_only, bool):
        raise ValueError("used_only must be a bool.")
    items = []
    for material in bpy.data.materials:
        users = int(material.users)
        is_used = users > 0
        if used_only and not is_used:
            continue
        has_nodes = bool(material.use_nodes and material.node_tree is not None)
        node_types = []
        node_count = 0
        if has_nodes:
            node_count = len(material.node_tree.nodes)
            node_types = sorted({node.bl_idname for node in material.node_tree.nodes})
        items.append({
            "name": material.name,
            "users": users,
            "is_used": is_used,
            "use_nodes": bool(material.use_nodes),
            "node_types": node_types,
            "node_count": node_count,
        })
    items.sort(key=lambda entry: entry["name"])
    return {
        "success": True,
        "count": len(items),
        "materials": items,
        "used_only": used_only,
    }
