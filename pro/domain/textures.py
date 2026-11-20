"""Procedural image textures and image-to-material helpers."""

import math
import os

import bpy


_IMAGE_FORMATS = ("PNG", "JPEG", "OPEN_EXR", "TARGA", "TIFF", "BMP")
_MAPPING_OUTPUTS = ("UV", "Generated", "Object")


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
        raise ValueError(f"{label} must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1].")
    channels = []
    for channel in color:
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            raise ValueError(f"{label} must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1].")
        value = float(channel)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{label} must be an RGB or RGBA sequence of 3 or 4 floats in [0, 1].")
        channels.append(value)
    if len(channels) == 3:
        channels.append(1.0)
    return tuple(channels)


def _validate_dimensions(width, height):
    width = _as_int(width, "width")
    height = _as_int(height, "height")
    _check_range(width, "width", minimum=1, maximum=16384)
    _check_range(height, "height", minimum=1, maximum=16384)
    return width, height


def _get_image(image_name):
    if not isinstance(image_name, str) or not image_name.strip():
        raise ValueError("image_name must be a non-empty string.")
    cleaned = image_name.strip()
    image = bpy.data.images.get(cleaned)
    if image is None:
        raise ValueError(f"Image '{cleaned}' not found.")
    return image


def _new_image(name, width, height):
    existing = bpy.data.images.get(name)
    if existing is not None:
        try:
            bpy.data.images.remove(existing)
        except Exception:
            pass
    return bpy.data.images.new(name, width, height, alpha=True, float_buffer=False)


def _fill_pixels(image, pixels):
    image.pixels = pixels


def _solid_pixels(width, height, color):
    pixel = list(color)
    return pixel * (width * height)


def _checker_pixels(width, height, color_a, color_b, cells_x, cells_y):
    pixels = [0.0] * (width * height * 4)
    for y in range(height):
        row = (y * cells_y) // height
        for x in range(width):
            col = (x * cells_x) // width
            color = color_a if (row + col) % 2 == 0 else color_b
            offset = (y * width + x) * 4
            pixels[offset] = color[0]
            pixels[offset + 1] = color[1]
            pixels[offset + 2] = color[2]
            pixels[offset + 3] = color[3]
    return pixels


def _image_info(image):
    return {
        "width": int(image.size[0]),
        "height": int(image.size[1]),
        "channels": int(image.channels),
        "packed": bool(image.packed_file is not None),
    }


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


def _ensure_material(material_name):
    material = bpy.data.materials.get(material_name)
    if material is None:
        material = bpy.data.materials.new(material_name)
    material.use_nodes = True
    tree = material.node_tree
    if tree is None:
        raise ValueError(f"Material '{material.name}' has no node tree.")
    return material, tree


def _principled_and_output(tree):
    principled = None
    output = None
    for node in tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled" and principled is None:
            principled = node
        elif node.bl_idname == "ShaderNodeOutputMaterial" and output is None:
            output = node
    if principled is None:
        principled = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
        principled.name = "Principled BSDF"
        principled.location = (200.0, 0.0)
    if output is None:
        output = tree.nodes.new(type="ShaderNodeOutputMaterial")
        output.name = "Material Output"
        output.location = (500.0, 0.0)
        try:
            tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
        except Exception:
            pass
    return principled, output


def _available_colorspaces(image):
    try:
        prop = image.colorspace_settings.bl_rna.properties["name"]
        return [item.identifier for item in prop.enum_items]
    except Exception:
        return ["sRGB", "Linear", "Linear ACES", "Non-Color", "XYZ", "sRGB Float"]


def create_image(server, name="Texture", width=256, height=256,
                 color=(0.0, 0.0, 0.0, 1.0), checker=False) -> dict:
    """Create an image filled with a solid color or a checker pattern."""
    del server
    name = _validate_name(name)
    width, height = _validate_dimensions(width, height)
    color = _validate_color(color)
    if not isinstance(checker, bool):
        raise ValueError("checker must be a bool.")

    image = _new_image(name, width, height)
    if checker:
        pixels = _checker_pixels(width, height, (0.0, 0.0, 0.0, 1.0),
                                 (1.0, 1.0, 1.0, 1.0), 8, 8)
    else:
        pixels = _solid_pixels(width, height, color)
    _fill_pixels(image, pixels)
    image.update()
    info = _image_info(image)
    return {
        "success": True,
        "image": image.name,
        "width": info["width"],
        "height": info["height"],
        "channels": info["channels"],
        "packed": info["packed"],
        "checker": checker,
        "color": list(color),
    }


def create_checker_texture(server, name="Checker", width=256, height=256,
                           color_a=(0.1, 0.1, 0.1, 1.0),
                           color_b=(0.9, 0.9, 0.9, 1.0),
                           cells=8) -> dict:
    """Create a deterministic checker image from two colors and a cell count."""
    del server
    name = _validate_name(name)
    width, height = _validate_dimensions(width, height)
    color_a = _validate_color(color_a, label="color_a")
    color_b = _validate_color(color_b, label="color_b")
    cells = _as_int(cells, "cells")
    _check_range(cells, "cells", minimum=1, maximum=1024)

    image = _new_image(name, width, height)
    pixels = _checker_pixels(width, height, color_a, color_b, cells, cells)
    _fill_pixels(image, pixels)
    image.update()
    info = _image_info(image)
    return {
        "success": True,
        "image": image.name,
        "width": info["width"],
        "height": info["height"],
        "channels": info["channels"],
        "packed": info["packed"],
        "cells": cells,
        "color_a": list(color_a),
        "color_b": list(color_b),
    }


def add_image_texture_node(server, material_name, image_name,
                           mapping="UV", scale=1.0) -> dict:
    """Add an Image Texture node to a material and link it to Base Color."""
    del server
    material_name = _validate_name(material_name, label="material_name")
    image = _get_image(image_name)
    if not isinstance(mapping, str) or not mapping.strip():
        raise ValueError("mapping must be a non-empty string.")
    mapping_clean = mapping.strip()
    matched = None
    for candidate in _MAPPING_OUTPUTS:
        if candidate.lower() == mapping_clean.lower():
            matched = candidate
            break
    if matched is None:
        raise ValueError(f"mapping must be one of {list(_MAPPING_OUTPUTS)}.")
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=1e-6, maximum=1e6)

    material, tree = _ensure_material(material_name)
    principled, _output = _principled_and_output(tree)

    tex_node = tree.nodes.new(type="ShaderNodeTexImage")
    base_name = "Image Texture"
    used_names = {node.name for node in tree.nodes if node is not tex_node}
    index = 0
    candidate = base_name
    while candidate in used_names:
        index += 1
        candidate = f"{base_name}.{index:03d}"
    tex_node.name = candidate
    tex_node.location = (-200.0, 200.0)
    tex_node.image = image

    coord_node = None
    for node in tree.nodes:
        if node.bl_idname == "ShaderNodeTexCoord":
            coord_node = node
            break
    if coord_node is None:
        coord_node = tree.nodes.new(type="ShaderNodeTexCoord")
        coord_node.name = "Texture Coordinate"
        coord_node.location = (-800.0, 0.0)

    mapping_node = tree.nodes.new(type="ShaderNodeMapping")
    map_base = "Image Mapping"
    used_names = {node.name for node in tree.nodes if node is not mapping_node}
    index = 0
    candidate = map_base
    while candidate in used_names:
        index += 1
        candidate = f"{map_base}.{index:03d}"
    mapping_node.name = candidate
    mapping_node.location = (-500.0, 0.0)
    try:
        mapping_node.inputs["Scale"].default_value = (scale, scale, scale)
    except Exception:
        pass

    links = tree.links
    try:
        links.new(coord_node.outputs[matched], mapping_node.inputs["Vector"])
    except Exception as exc:
        raise ValueError(f"mapping output '{matched}' is not available: {exc}")
    try:
        links.new(mapping_node.outputs["Vector"], tex_node.inputs["Vector"])
    except Exception:
        pass
    base_socket = _find_input(principled, ("Base Color",))
    if base_socket is not None:
        try:
            links.new(tex_node.outputs["Color"], base_socket)
        except Exception:
            pass

    return {
        "success": True,
        "material": material.name,
        "image": image.name,
        "nodes": {
            "image_texture": tex_node.name,
            "mapping": mapping_node.name,
            "texture_coordinate": coord_node.name,
            "principled": principled.name,
        },
        "mapping": matched,
        "scale": scale,
    }


def resize_image(server, image_name, width, height) -> dict:
    """Scale an image to a new width and height."""
    del server
    image = _get_image(image_name)
    width, height = _validate_dimensions(width, height)
    image.scale(width, height)
    image.update()
    return {
        "success": True,
        "image": image.name,
        "width": int(image.size[0]),
        "height": int(image.size[1]),
        "channels": int(image.channels),
    }


def set_image_colorspace(server, image_name,
                         colorspace="sRGB") -> dict:
    """Set the colorspace of an image, validating against available names."""
    del server
    image = _get_image(image_name)
    if not isinstance(colorspace, str) or not colorspace.strip():
        raise ValueError("colorspace must be a non-empty string.")
    cleaned = colorspace.strip()
    available = _available_colorspaces(image)
    match = None
    for candidate in available:
        if candidate.lower() == cleaned.lower():
            match = candidate
            break
    if match is None:
        raise ValueError(f"colorspace must be one of {available}.")
    image.colorspace_settings.name = match
    return {
        "success": True,
        "image": image.name,
        "colorspace": image.colorspace_settings.name,
        "available": available,
    }


def pack_image(server, image_name) -> dict:
    """Pack an image into the blend file."""
    del server
    image = _get_image(image_name)
    image.pack()
    return {
        "success": True,
        "image": image.name,
        "packed": bool(image.packed_file is not None),
    }


def save_image(server, image_name, filepath, format="PNG") -> dict:
    """Save an image to a resolved filepath, creating parent directories."""
    del server
    image = _get_image(image_name)
    if not isinstance(filepath, str) or not filepath.strip():
        raise ValueError("filepath must be a non-empty string.")
    if not isinstance(format, str) or not format.strip():
        raise ValueError("format must be a non-empty string.")
    format_clean = format.strip().upper()
    if format_clean in ("JPG", "JPEG"):
        format_clean = "JPEG"
    if format_clean not in _IMAGE_FORMATS:
        raise ValueError(f"format must be one of {list(_IMAGE_FORMATS)}.")

    resolved = os.path.abspath(os.path.expanduser(filepath.strip()))
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)
    image.file_format = format_clean
    image.filepath_raw = resolved
    image.save()
    size_bytes = 0
    try:
        size_bytes = int(os.path.getsize(resolved))
    except OSError:
        size_bytes = 0
    return {
        "success": True,
        "image": image.name,
        "filepath": resolved,
        "format": format_clean,
        "width": int(image.size[0]),
        "height": int(image.size[1]),
        "bytes": size_bytes,
    }


def image_to_material(server, image_name, material_name,
                      roughness=0.5) -> dict:
    """Build a material showing an image through Base Color and roughness."""
    del server
    image = _get_image(image_name)
    material_name = _validate_name(material_name, label="material_name")
    roughness = _as_number(roughness, "roughness")
    _check_range(roughness, "roughness", minimum=0.0, maximum=1.0)

    material, tree = _ensure_material(material_name)
    for node in list(tree.nodes):
        tree.nodes.remove(node)

    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (500.0, 0.0)
    principled = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    principled.name = "Principled BSDF"
    principled.location = (200.0, 0.0)
    tex_node = tree.nodes.new(type="ShaderNodeTexImage")
    tex_node.name = "Image Texture"
    tex_node.location = (-200.0, 200.0)
    tex_node.image = image

    _set_socket(principled, ("Roughness",), roughness)
    links = tree.links
    base_socket = _find_input(principled, ("Base Color",))
    if base_socket is not None:
        links.new(tex_node.outputs["Color"], base_socket)
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    nodes = {node.name: node.bl_idname for node in tree.nodes}
    return {
        "success": True,
        "material": material.name,
        "image": image.name,
        "nodes": nodes,
        "roughness": roughness,
    }
