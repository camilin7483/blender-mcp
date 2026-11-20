"""Advanced material tools: texture baking, UDIM tiles, displacement and cleanup."""

import math
import time

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


def _validate_color(color, label):
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


def _validate_image_size(value, label="image_size"):
    size = _as_int(value, label)
    _check_range(size, label, minimum=16, maximum=4096)
    return size


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


def _get_material(material_name):
    if not isinstance(material_name, str) or not material_name.strip():
        raise ValueError("material_name must be a non-empty string.")
    cleaned = material_name.strip()
    material = bpy.data.materials.get(cleaned)
    if material is None:
        raise ValueError(f"Material '{cleaned}' not found.")
    return material


def _ensure_node_tree(material):
    material.use_nodes = True
    tree = material.node_tree
    if tree is None:
        raise ValueError(f"Material '{material.name}' has no node tree.")
    return tree


def _find_output(tree):
    for node in tree.nodes:
        if node.type == "OUTPUT_MATERIAL":
            return node
    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (400.0, 0.0)
    return output


def _find_principled(tree):
    for node in tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def _nodes_dict(material):
    return {node.name: node.bl_idname for node in material.node_tree.nodes}


def _unique_image_name(base):
    name = base
    index = 1
    while name in bpy.data.images:
        existing = bpy.data.images[name]
        if existing.users == 0:
            try:
                bpy.data.images.remove(existing)
            except (AttributeError, RuntimeError):
                pass
            if name not in bpy.data.images:
                break
        index += 1
        name = f"{base}.{index:03d}"
    return name


def _bake_map(obj, material, bake_type, image_size, samples, extra_bake_args):
    image_name = _unique_image_name(f"{obj.name}_{bake_type}_Bake")
    image = bpy.data.images.new(image_name, image_size, image_size, alpha=True)
    try:
        image.file_format = "PNG"
    except (AttributeError, TypeError):
        pass

    tree = _ensure_node_tree(material)
    tex_node = tree.nodes.new(type="ShaderNodeTexImage")
    tex_node.name = f"Bake {bake_type}"
    tex_node.label = f"Bake {bake_type}"
    tex_node.location = (-600.0, 0.0)
    tex_node.image = image
    for node in tree.nodes:
        try:
            node.select = node is tex_node
        except (AttributeError, TypeError):
            pass
    try:
        tree.nodes.active = tex_node
    except (AttributeError, TypeError):
        pass

    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    prev_engine = scene.render.engine
    cycles = getattr(scene, "cycles", None)
    prev_samples = getattr(cycles, "samples", None) if cycles is not None else None
    prev_active = view_layer.objects.active
    prev_selected = [item for item in bpy.context.selected_objects]
    prev_mode = None
    try:
        if prev_active is not None:
            prev_mode = prev_active.mode
    except (AttributeError, ReferenceError):
        prev_mode = None

    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except (RuntimeError, TypeError):
        pass
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except (RuntimeError, TypeError):
        pass
    obj.select_set(True)
    view_layer.objects.active = obj

    try:
        scene.render.engine = "CYCLES"
    except (AttributeError, TypeError, ValueError):
        pass
    if cycles is not None:
        try:
            cycles.samples = samples
        except (AttributeError, TypeError):
            pass

    started = time.perf_counter()
    try:
        bpy.ops.object.bake(type=bake_type, **extra_bake_args)
    except Exception as exc:
        return {
            "success": False,
            "object": obj.name,
            "material": material.name,
            "image": image.name,
            "image_size": [int(image.size[0]), int(image.size[1])],
            "bake_type": bake_type,
            "baked": False,
            "elapsed": round(time.perf_counter() - started, 3),
            "error": f"Bake '{bake_type}' failed for '{obj.name}': {exc}",
        }
    finally:
        try:
            scene.render.engine = prev_engine
        except (AttributeError, TypeError, ValueError):
            pass
        if cycles is not None and prev_samples is not None:
            try:
                cycles.samples = prev_samples
            except (AttributeError, TypeError):
                pass
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except (RuntimeError, TypeError):
            pass
        for item in prev_selected:
            try:
                item.select_set(True)
            except (AttributeError, ReferenceError, RuntimeError):
                continue
        try:
            view_layer.objects.active = prev_active
        except (AttributeError, ReferenceError, RuntimeError):
            pass

    try:
        image.update()
    except (AttributeError, RuntimeError):
        pass
    return {
        "success": True,
        "object": obj.name,
        "material": material.name,
        "image": image.name,
        "image_size": [int(image.size[0]), int(image.size[1])],
        "bake_type": bake_type,
        "samples": samples,
        "baked": True,
        "elapsed": round(time.perf_counter() - started, 3),
    }


def _require_bake_target(object_name):
    obj = _get_mesh_object(object_name)
    if len(obj.data.uv_layers) == 0:
        raise ValueError(f"Object '{obj.name}' has no UV layer; unwrap it first.")
    material = None
    for slot in obj.data.materials:
        if slot is not None:
            material = slot
            break
    if material is None:
        raise ValueError(f"Object '{obj.name}' has no material to bake.")
    _ensure_node_tree(material)
    return obj, material


def bake_ambient_occlusion(server, object_name, image_size=512,
                           samples=16) -> dict:
    """Bake ambient occlusion of a mesh to a new image via Cycles."""
    obj, material = _require_bake_target(object_name)
    image_size = _validate_image_size(image_size)
    samples = _as_int(samples, "samples")
    _check_range(samples, "samples", minimum=1, maximum=1024)
    return _bake_map(obj, material, "AO", image_size, samples, {})


def bake_normal_map(server, object_name, image_size=512) -> dict:
    """Bake the normal map of a mesh to a new image via Cycles."""
    obj, material = _require_bake_target(object_name)
    image_size = _validate_image_size(image_size)
    return _bake_map(obj, material, "NORMAL", image_size, 16, {})


def bake_diffuse(server, object_name, image_size=512) -> dict:
    """Bake the diffuse color of a mesh to a new image via Cycles."""
    obj, material = _require_bake_target(object_name)
    image_size = _validate_image_size(image_size)
    return _bake_map(obj, material, "DIFFUSE", image_size, 16, {})


def create_udim_tiles(server, name="UDIM", tiles=(1001, 1002),
                      size=1024) -> dict:
    """Create a tiled UDIM image with one tile per given UDIM number."""
    name = _validate_name(name)
    try:
        tile_list = list(tiles)
    except TypeError:
        raise ValueError("tiles must be a sequence of UDIM tile numbers.")
    if not tile_list:
        raise ValueError("tiles must contain at least one tile number.")
    seen = set()
    cleaned = []
    for tile in tile_list:
        number = _as_int(tile, "tiles entries")
        _check_range(number, "tiles entries", minimum=1001, maximum=1999)
        if number not in seen:
            seen.add(number)
            cleaned.append(number)
    cleaned.sort()
    size = _as_int(size, "size")
    _check_range(size, "size", minimum=16, maximum=8192)

    image_name = _unique_image_name(name)
    image = bpy.data.images.new(image_name, size, size, alpha=True)
    try:
        image.source = "TILED"
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Image '{image.name}' does not support UDIM tiles: {exc}")
    existing = set()
    try:
        existing = {tile.tile_number for tile in image.tiles}
    except (AttributeError, TypeError):
        existing = set()
    added = []
    for number in cleaned:
        if number in existing:
            continue
        try:
            image.tiles.new(tile_number=number)
        except TypeError:
            image.tiles.new(number)
        except (AttributeError, RuntimeError) as exc:
            raise ValueError(f"Could not add UDIM tile {number}: {exc}")
        added.append(number)
    try:
        tile_numbers = sorted({tile.tile_number for tile in image.tiles})
    except (AttributeError, TypeError):
        tile_numbers = cleaned
    return {
        "success": True,
        "image": image.name,
        "tiles": tile_numbers,
        "added": added,
        "tile_count": len(tile_numbers),
        "size": size,
    }


def add_displacement(server, material_name, scale=0.1,
                     midlevel=0.5) -> dict:
    """Add noise-driven true displacement to a material."""
    material = _get_material(material_name)
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=0.0, maximum=10.0)
    midlevel = _as_number(midlevel, "midlevel")
    _check_range(midlevel, "midlevel", minimum=0.0, maximum=1.0)
    tree = _ensure_node_tree(material)
    output = _find_output(tree)

    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Displacement Noise"
    noise.location = (-400.0, -200.0)
    displacement = tree.nodes.new(type="ShaderNodeDisplacement")
    displacement.name = "Displacement"
    displacement.location = (100.0, -200.0)
    for socket_name, value in (("Scale", scale), ("Midlevel", midlevel)):
        target = displacement.inputs.get(socket_name)
        if target is not None:
            try:
                target.default_value = value
            except (AttributeError, TypeError):
                pass
    try:
        tree.links.new(noise.outputs["Fac"], displacement.inputs["Height"])
    except (AttributeError, KeyError, RuntimeError, TypeError) as exc:
        raise ValueError(
            f"Could not link displacement nodes in '{material.name}': {exc}"
        )
    try:
        tree.links.new(
            displacement.outputs["Displacement"], output.inputs["Displacement"]
        )
    except (AttributeError, KeyError, RuntimeError, TypeError) as exc:
        raise ValueError(
            f"Material Output of '{material.name}' has no Displacement input: {exc}"
        )
    if hasattr(material, "displacement_method"):
        try:
            material.displacement_method = "BOTH"
        except (AttributeError, TypeError, ValueError):
            pass
    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "displacement_node": displacement.name,
        "noise_node": noise.name,
        "scale": scale,
        "midlevel": midlevel,
    }


def create_layer_weight_mix(server, name="LayerMix",
                            color_a=(0.1, 0.2, 0.4, 1.0),
                            color_b=(0.8, 0.6, 0.3, 1.0)) -> dict:
    """Create a Fresnel-blended mix of two Principled shaders."""
    name = _validate_name(name)
    color_a = _validate_color(color_a, "color_a")
    color_b = _validate_color(color_b, "color_b")

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
    mix = tree.nodes.new(type="ShaderNodeMixShader")
    mix.name = "Layer Mix"
    mix.location = (300.0, 0.0)
    bsdf_a = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf_a.name = "Layer A"
    bsdf_a.location = (0.0, 150.0)
    bsdf_b = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf_b.name = "Layer B"
    bsdf_b.location = (0.0, -150.0)
    layer_weight = tree.nodes.new(type="ShaderNodeLayerWeight")
    layer_weight.name = "Layer Weight"
    layer_weight.location = (-300.0, 0.0)
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.name = "Fresnel Ramp"
    ramp.location = (-100.0, 0.0)

    for node, color in ((bsdf_a, color_a), (bsdf_b, color_b)):
        target = node.inputs.get("Base Color")
        if target is not None:
            try:
                target.default_value = color
            except (AttributeError, TypeError):
                pass
    try:
        tree.links.new(layer_weight.outputs["Facing"], ramp.inputs["Fac"])
        tree.links.new(ramp.outputs["Color"], mix.inputs["Fac"])
        tree.links.new(bsdf_a.outputs["BSDF"], mix.inputs[1])
        tree.links.new(bsdf_b.outputs["BSDF"], mix.inputs[2])
        tree.links.new(mix.outputs["Shader"], output.inputs["Surface"])
    except (AttributeError, KeyError, IndexError, RuntimeError, TypeError) as exc:
        raise ValueError(
            f"Could not link layer weight mix nodes in '{material.name}': {exc}"
        )
    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "color_a": list(color_a),
        "color_b": list(color_b),
    }


def create_parallax_bump(server, material_name, scale=0.05) -> dict:
    """Add noise-driven bump mapping to a material's Principled Normal."""
    material = _get_material(material_name)
    scale = _as_number(scale, "scale")
    _check_range(scale, "scale", minimum=0.0, maximum=10.0)
    tree = _ensure_node_tree(material)
    bsdf = _find_principled(tree)
    if bsdf is None:
        output = _find_output(tree)
        bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
        bsdf.name = "Principled BSDF"
        bsdf.location = (100.0, 0.0)
        try:
            tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
        except (AttributeError, KeyError, RuntimeError, TypeError):
            pass

    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Parallax Noise"
    noise.location = (-400.0, -200.0)
    bump = tree.nodes.new(type="ShaderNodeBump")
    bump.name = "Parallax Bump"
    bump.location = (-100.0, -200.0)
    strength = min(max(scale, 0.0), 1.0)
    for socket_name, value in (("Strength", strength), ("Distance", scale)):
        target = bump.inputs.get(socket_name)
        if target is not None:
            try:
                target.default_value = value
            except (AttributeError, TypeError):
                pass
    try:
        tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    except (AttributeError, KeyError, RuntimeError, TypeError) as exc:
        raise ValueError(
            f"Could not link parallax bump nodes in '{material.name}': {exc}"
        )
    normal_socket = bsdf.inputs.get("Normal")
    if normal_socket is None:
        raise ValueError(
            f"Material '{material.name}' Principled BSDF has no Normal input."
        )
    try:
        tree.links.new(bump.outputs["Normal"], normal_socket)
    except (AttributeError, KeyError, RuntimeError, TypeError) as exc:
        raise ValueError(
            f"Could not link bump Normal in '{material.name}': {exc}"
        )
    return {
        "success": True,
        "material": material.name,
        "nodes": _nodes_dict(material),
        "bump_node": bump.name,
        "noise_node": noise.name,
        "scale": scale,
        "strength": strength,
        "distance": scale,
    }


def optimize_material(server, material_name) -> dict:
    """Remove dead nodes and merge duplicate image texture nodes."""
    material = _get_material(material_name)
    tree = _ensure_node_tree(material)
    removed = []

    by_image = {}
    for node in list(tree.nodes):
        if node.type != "TEX_IMAGE":
            continue
        key = node.image.name if getattr(node, "image", None) is not None else None
        if key is None:
            continue
        by_image.setdefault(key, []).append(node)
    for key in sorted(by_image):
        group = sorted(by_image[key], key=lambda item: item.name)
        kept = group[0]
        for duplicate in group[1:]:
            for link in list(tree.links):
                if link.from_node is not duplicate:
                    continue
                replacement = None
                try:
                    replacement = kept.outputs[link.from_socket.name]
                except (AttributeError, KeyError, IndexError):
                    try:
                        replacement = kept.outputs[link.from_socket.identifier]
                    except (AttributeError, KeyError, IndexError):
                        replacement = None
                if replacement is None:
                    continue
                try:
                    tree.links.new(replacement, link.to_socket)
                except (AttributeError, RuntimeError, TypeError):
                    continue
            removed.append(duplicate.name)
            try:
                tree.nodes.remove(duplicate)
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    for node in list(tree.nodes):
        if node.type in ("OUTPUT_MATERIAL", "GROUP_OUTPUT", "OUTPUT"):
            continue
        outputs = getattr(node, "outputs", [])
        if len(outputs) == 0:
            continue
        try:
            used = any(len(list(socket.links)) > 0 for socket in outputs)
        except (AttributeError, TypeError):
            continue
        if not used:
            removed.append(node.name)
            try:
                tree.nodes.remove(node)
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    removed = sorted(set(removed))
    return {
        "success": True,
        "material": material.name,
        "removed": removed,
        "removed_count": len(removed),
        "node_count": len(tree.nodes),
        "nodes": _nodes_dict(material),
    }
