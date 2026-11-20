"""High-detail procedural character base domain pack.

Pure ``bpy`` / ``bmesh`` / ``mathutils`` geometry and node graphs, no
external assets. All functions run on Blender's main thread, validate
their inputs, raise ``ValueError`` with a precise message on bad input
and return plain JSON-serializable dictionaries.

Outputs are procedural pro-level bases (anatomical landmarks, layered
eye, skin shader, full dentition, unified body, garment shells), not
AAA or photoreal characters.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

_PRO_LIMITATIONS = (
    "Procedural pro base only: generated anatomy proportions for layout, "
    "shading tests and previz (no sculpt detail, no rig, no AAA certification, "
    "not photoreal)."
)

_VALID_BUILDS = ("slim", "average", "heavy")
_VALID_GARMENTS = ("shirt", "jacket", "pants")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_name(value, label="name"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_float(value, label, minimum=None, maximum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number (got {value!r})")
    if isinstance(value, bool) or not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number (got {value!r})")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {number})")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {number})")
    return number


def _validate_int(value, label, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer (got {value!r})")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum} (got {value})")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum} (got {value})")
    return value


def _validate_color(value, label="color"):
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        raise ValueError(
            f"{label} must be an RGB or RGBA sequence of 3 or 4 floats "
            f"in [0, 1] (got {value!r})"
        )
    channels = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            raise ValueError(
                f"{label} must be an RGB or RGBA sequence of 3 or 4 floats "
                f"in [0, 1] (got {value!r})"
            )
        number = float(channel)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError(
                f"{label} must be an RGB or RGBA sequence of 3 or 4 floats "
                f"in [0, 1] (got {value!r})"
            )
        channels.append(number)
    if len(channels) == 3:
        channels.append(1.0)
    return tuple(channels)


def _validate_build(value):
    if not isinstance(value, str):
        raise ValueError(
            f"build must be one of {list(_VALID_BUILDS)} (got {value!r})"
        )
    key = value.strip().lower()
    if key not in _VALID_BUILDS:
        raise ValueError(
            f"build must be one of {list(_VALID_BUILDS)} (got {value!r})"
        )
    return key


def _validate_garment(value):
    if not isinstance(value, str):
        raise ValueError(
            f"garment_type must be one of {list(_VALID_GARMENTS)} "
            f"(got {value!r})"
        )
    key = value.strip().lower()
    if key not in _VALID_GARMENTS:
        raise ValueError(
            f"garment_type must be one of {list(_VALID_GARMENTS)} "
            f"(got {value!r})"
        )
    return key


# ---------------------------------------------------------------------------
# Geometry helpers (data API + bmesh only: Blender 4.5/5.2 compatible)
# ---------------------------------------------------------------------------

def _link(obj):
    try:
        collection = bpy.context.collection or bpy.context.scene.collection
    except AttributeError:
        collection = bpy.context.scene.collection
    collection.objects.link(obj)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return obj


def _finish(bm, name, materials=()):
    """Build mesh + object from *bm*, link it, return (object, dims, polys)."""
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    for mat in materials:
        mesh.materials.append(mat)
    _link(obj)
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    dims = [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)]
    return obj, dims, len(mesh.polygons)


def _box(bm, size_x, size_y, size_z, location=(0.0, 0.0, 0.0)):
    geo = bmesh.ops.create_cube(bm, size=1.0)
    verts = geo["verts"]
    bmesh.ops.scale(bm, vec=Vector((size_x, size_y, size_z)), verts=verts)
    bmesh.ops.translate(bm, vec=Vector(location), verts=verts)
    return verts


def _ball(bm, radius, location=(0.0, 0.0, 0.0), u_segments=16,
          v_segments=12, scale=None):
    geo = bmesh.ops.create_uvsphere(
        bm, u_segments=u_segments, v_segments=v_segments, radius=radius,
    )
    verts = geo["verts"]
    if scale is not None:
        bmesh.ops.scale(bm, vec=Vector(scale), verts=verts)
    bmesh.ops.translate(bm, vec=Vector(location), verts=verts)
    return verts


def _limb(bm, radius_top, radius_bottom, depth, location=(0.0, 0.0, 0.0),
          segments=12, tilt_x=0.0, tilt_y=0.0):
    geo = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segments,
        radius1=radius_bottom, radius2=radius_top, depth=depth,
    )
    verts = geo["verts"]
    if tilt_x:
        bmesh.ops.rotate(
            bm, cent=Vector((0.0, 0.0, 0.0)),
            matrix=Matrix.Rotation(tilt_x, 3, "X"), verts=verts,
        )
    if tilt_y:
        bmesh.ops.rotate(
            bm, cent=Vector((0.0, 0.0, 0.0)),
            matrix=Matrix.Rotation(tilt_y, 3, "Y"), verts=verts,
        )
    bmesh.ops.translate(bm, vec=Vector(location), verts=verts)
    return verts


def _cleanup(bm):
    """Weld coincident verts, drop loose verts, recalc normals."""
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
    for vert in [v for v in bm.verts if not v.link_faces]:
        bm.verts.remove(vert)
    bm.faces.ensure_lookup_table()
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))


def _dent(bm, center, radius, offset):
    """Push verts near *center* by *offset* with smooth falloff (sockets)."""
    bm.verts.ensure_lookup_table()
    center = Vector(center)
    shift = Vector(offset)
    for vert in bm.verts:
        dist = (vert.co - center).length
        if dist < radius:
            falloff = 0.5 + 0.5 * math.cos(math.pi * dist / radius)
            vert.co += shift * falloff


def _normalize_height_center(bm, target_height):
    """Scale Z so the mesh spans *target_height*, base at Z=0, centered X/Y."""
    bm.verts.ensure_lookup_table()
    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    cx, cy, min_z = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, min(zs)
    span = max(zs) - min_z
    if span <= 0.0:
        raise ValueError("geometry has zero height and cannot be normalized")
    factor = target_height / span
    for vert in bm.verts:
        vert.co.x -= cx
        vert.co.y -= cy
        vert.co.z = (vert.co.z - min_z) * factor


def _add_subsurf(obj, levels):
    sub = obj.modifiers.new(name="Subdivision", type="SUBSURF")
    sub.levels = levels
    sub.render_levels = levels
    return sub


def _simple_principled(name, rgba, roughness=0.6):
    """Get or create a plain Principled material (Blender 4.5/5.2 safe)."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    color = list(rgba) if len(rgba) == 4 else list(rgba) + [1.0]
    if "Base Color" in bsdf.inputs:
        bsdf.inputs["Base Color"].default_value = color
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = float(roughness)
    return mat


def _find_input(node, names):
    for candidate in names:
        socket = node.inputs.get(candidate)
        if socket is not None:
            return socket
    return None


def _set_socket(node, names, value):
    socket = _find_input(node, names)
    if socket is not None:
        try:
            socket.default_value = value
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------



def _add_planar_uv(obj):
    """Add a simple normalized XZ planar UV layer when the mesh has none."""
    mesh = obj.data
    if getattr(mesh, "uv_layers", None) and len(mesh.uv_layers) > 0:
        return False
    if len(mesh.vertices) == 0:
        return False
    xs = [vertex.co.x for vertex in mesh.vertices]
    zs = [vertex.co.z for vertex in mesh.vertices]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    width = max(max_x - min_x, 1e-9)
    height = max(max_z - min_z, 1e-9)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index]
            uv_layer.data[loop_index].uv = (
                (vertex.co.x - min_x) / width,
                (vertex.co.z - min_z) / height,
            )
    return True


def _torus(bm, major_rad, minor_rad, major_seg=20, minor_seg=8):
    """Create a torus in the XY plane without bmesh.ops.create_torus."""
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


def create_anatomical_head(server, name="HeadPro", height=0.23, width=0.15,
                           depth=0.19, subdivisions=2) -> dict:
    """Create a grounded single-mesh anatomical head base with landmarks."""
    _ = server
    name = _validate_name(name)
    height = _validate_float(height, "height", minimum=0.05, maximum=1.0)
    width = _validate_float(width, "width", minimum=0.03, maximum=0.6)
    depth = _validate_float(depth, "depth", minimum=0.03, maximum=0.6)
    subdivisions = _validate_int(subdivisions, "subdivisions",
                                 minimum=0, maximum=4)

    h, w, d = height, width, depth
    bm = bmesh.new()
    # Cranium: large ellipsoid, top lands on full height.
    _ball(bm, 0.5, (0.0, d * 0.03, h * 0.67), u_segments=24, v_segments=18,
          scale=(w, d, h * 0.66))
    # Mid face / tapered jaw mass.
    _ball(bm, 0.5, (0.0, -d * 0.06, h * 0.34), u_segments=20, v_segments=14,
          scale=(w * 0.78, d * 0.82, h * 0.50))
    # Chin.
    _ball(bm, 0.5, (0.0, -d * 0.10, h * 0.08), u_segments=14, v_segments=10,
          scale=(w * 0.34, d * 0.34, h * 0.16))
    # Cheekbones.
    for sign in (-1.0, 1.0):
        _ball(bm, w * 0.14, (sign * w * 0.30, -d * 0.22, h * 0.40),
              u_segments=12, v_segments=10, scale=(1.2, 0.9, 0.7))
    # Brow ridge.
    _box(bm, w * 0.70, d * 0.16, h * 0.075, (0.0, -d * 0.38, h * 0.615))
    # Nose bridge + tip.
    _box(bm, w * 0.11, d * 0.10, h * 0.20, (0.0, -d * 0.44, h * 0.50))
    _ball(bm, w * 0.09, (0.0, -d * 0.50, h * 0.40),
          u_segments=12, v_segments=10, scale=(1.0, 1.1, 0.85))
    # Ears: thin tall shells on the sides.
    for sign in (-1.0, 1.0):
        _ball(bm, h * 0.13, (sign * (w / 2.0 + w * 0.02), d * 0.02, h * 0.45),
              u_segments=14, v_segments=12, scale=(0.35, 0.6, 1.0))
    # Lips (front is -Y); tracked for the lip material slot.
    lip_start = set(bm.faces)
    _box(bm, w * 0.32, d * 0.06, h * 0.035, (0.0, -d * 0.40, h * 0.27))
    _box(bm, w * 0.28, d * 0.065, h * 0.04, (0.0, -d * 0.405, h * 0.235))
    bm.faces.ensure_lookup_table()
    lip_faces = set(bm.faces) - lip_start
    for face in lip_faces:
        face.material_index = 1
    # Carve eye sockets by denting the base mesh inward (+Y).
    for sign in (-1.0, 1.0):
        _dent(bm, (sign * w * 0.21, -d * 0.38, h * 0.55),
              w * 0.24, (0.0, w * 0.06, 0.0))

    _cleanup(bm)
    _normalize_height_center(bm, h)

    skin = _simple_principled(name + "_Skin", (0.65, 0.45, 0.35, 1.0), 0.55)
    lip = _simple_principled(name + "_Lip", (0.55, 0.25, 0.22, 1.0), 0.5)
    obj, dims, polys = _finish(bm, name, [skin, lip])
    _add_planar_uv(obj)
    obj.location = (0.0, 0.0, 0.0)
    if subdivisions:
        _add_subsurf(obj, subdivisions)

    landmarks = {
        "eye_L": [round(w * 0.21, 6), round(-d * 0.44, 6), round(h * 0.55, 6)],
        "eye_R": [round(-w * 0.21, 6), round(-d * 0.44, 6), round(h * 0.55, 6)],
        "nose": [0.0, round(-d * 0.55, 6), round(h * 0.42, 6)],
        "mouth": [0.0, round(-d * 0.44, 6), round(h * 0.25, 6)],
        "chin": [0.0, round(-d * 0.12, 6), 0.005],
        "ear_L": [round(w * 0.55, 6), round(d * 0.02, 6), round(h * 0.45, 6)],
        "ear_R": [round(-w * 0.55, 6), round(d * 0.02, 6), round(h * 0.45, 6)],
    }
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "height": height,
        "width": width,
        "depth": depth,
        "subdivisions": subdivisions,
        "dimensions": [round(v, 6) for v in dims],
        "actual_height": round(dims[2], 6),
        "polygon_count": polys,
        "landmarks": sorted(landmarks.keys()),
        "positions": landmarks,
        "parts": ["cranium", "jaw", "chin", "cheekbone_L", "cheekbone_R",
                  "brow_ridge", "nose_bridge", "nose_tip", "ear_L", "ear_R",
                  "upper_lip", "lower_lip", "eye_socket_L", "eye_socket_R"],
        "materials": [skin.name, lip.name],
        "limitations": _PRO_LIMITATIONS,
    }


def create_eye_assembly(server, name="EyePro", radius=0.012,
                        iris_color=(0.2, 0.4, 0.7, 1.0)) -> dict:
    """Create a layered eyeball (sclera, cornea, iris, pupil, highlight)."""
    _ = server
    name = _validate_name(name)
    radius = _validate_float(radius, "radius", minimum=0.002, maximum=0.1)
    iris_color = _validate_color(iris_color, label="iris_color")
    r = radius

    sclera = _simple_principled(name + "_Sclera", (0.92, 0.92, 0.90, 1.0), 0.3)
    cornea = _simple_principled(name + "_Cornea",
                                (0.95, 0.97, 1.0, 1.0), 0.05)
    _set_socket(cornea.node_tree.nodes.get("Principled BSDF"),
                ("Transmission Weight", "Transmission"), 0.9)
    iris_mat = _simple_principled(name + "_Iris", iris_color, 0.4)
    pupil_mat = _simple_principled(name + "_Pupil",
                                   (0.01, 0.01, 0.01, 1.0), 0.25)
    highlight_mat = bpy.data.materials.get(name + "_Highlight")
    if highlight_mat is None:
        highlight_mat = bpy.data.materials.new(name=name + "_Highlight")
    highlight_mat.use_nodes = True
    nodes = highlight_mat.node_tree.nodes
    emission = nodes.get("Emission")
    if emission is None:
        emission = nodes.new(type="ShaderNodeEmission")
    _set_socket(emission, ("Color",), [1.0, 1.0, 1.0, 1.0])
    _set_socket(emission, ("Strength",), 3.0)
    output = nodes.get("Material Output")
    if output is not None and "Surface" in output.inputs:
        try:
            highlight_mat.node_tree.links.new(
                emission.outputs["Emission"], output.inputs["Surface"])
        except Exception:
            pass
    materials = [sclera, cornea, iris_mat, pupil_mat, highlight_mat]

    bm = bmesh.new()
    # Sclera facing -Y.
    start = set(bm.faces)
    _ball(bm, r, (0.0, 0.0, 0.0), u_segments=24, v_segments=16)
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - start:
        face.material_index = 0
    # Cornea bulge.
    start = set(bm.faces)
    _ball(bm, r * 0.55, (0.0, -r * 0.80, 0.0), u_segments=18, v_segments=12,
          scale=(1.0, 0.45, 1.0))
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - start:
        face.material_index = 1
    # Iris disc.
    start = set(bm.faces)
    _ball(bm, r * 0.42, (0.0, -r * 0.86, 0.0), u_segments=18, v_segments=12,
          scale=(1.0, 0.28, 1.0))
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - start:
        face.material_index = 2
    # Pupil.
    start = set(bm.faces)
    _ball(bm, r * 0.20, (0.0, -r * 0.94, 0.0), u_segments=12, v_segments=8,
          scale=(1.0, 0.28, 1.0))
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - start:
        face.material_index = 3
    # Specular highlight catchlight.
    start = set(bm.faces)
    _ball(bm, r * 0.07, (r * 0.25, -r * 1.02, r * 0.30),
          u_segments=8, v_segments=6)
    bm.faces.ensure_lookup_table()
    for face in set(bm.faces) - start:
        face.material_index = 4

    obj, dims, polys = _finish(bm, name, materials)
    obj.location = (0.0, 0.0, 0.0)

    parts = ["sclera", "cornea", "iris", "pupil", "highlight"]
    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "radius": radius,
        "iris_color": [round(c, 6) for c in iris_color],
        "parts": parts,
        "part_materials": {part: mat.name
                           for part, mat in zip(parts, materials)},
        "materials": [mat.name for mat in materials],
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "limitations": _PRO_LIMITATIONS,
    }


def create_skin_material_pro(server, name="SkinPro",
                             base_color=(0.65, 0.45, 0.35, 1.0),
                             subsurface=0.15, roughness=0.45,
                             pore_scale=80.0) -> dict:
    """Create a Principled skin shader with SSS, pores and microdetail."""
    _ = server
    name = _validate_name(name)
    base_color = _validate_color(base_color, label="base_color")
    subsurface = _validate_float(subsurface, "subsurface",
                                 minimum=0.0, maximum=1.0)
    roughness = _validate_float(roughness, "roughness",
                                minimum=0.0, maximum=1.0)
    pore_scale = _validate_float(pore_scale, "pore_scale",
                                 minimum=1.0, maximum=1000.0)

    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    tree = mat.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)

    tex_coord = tree.nodes.new(type="ShaderNodeTexCoord")
    tex_coord.name = "Skin Coordinates"
    tex_coord.location = (-800.0, 0.0)
    mapping = tree.nodes.new(type="ShaderNodeMapping")
    mapping.name = "Skin Mapping"
    mapping.location = (-620.0, 0.0)
    tree.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])

    voronoi = tree.nodes.new(type="ShaderNodeTexVoronoi")
    voronoi.name = "Pore Voronoi"
    voronoi.location = (-420.0, 120.0)
    _set_socket(voronoi, ("Scale",), float(pore_scale))
    try:
        voronoi.feature = "SMOOTH_F1"
    except Exception:
        pass

    noise = tree.nodes.new(type="ShaderNodeTexNoise")
    noise.name = "Microdetail Noise"
    noise.location = (-420.0, -140.0)
    _set_socket(noise, ("Scale",), float(pore_scale) * 0.15)
    _set_socket(noise, ("Detail",), 4.0)
    _set_socket(noise, ("Roughness",), 0.6)

    mix = tree.nodes.new(type="ShaderNodeMix")
    mix.name = "Pore Micro Mix"
    mix.location = (-200.0, 0.0)
    try:
        mix.data_type = "RGBA"
    except Exception:
        pass
    _set_socket(mix, ("Factor", "Fac"), 0.5)
    try:
        if voronoi.outputs.get("Distance") is not None:
            tree.links.new(voronoi.outputs["Distance"], mix.inputs["A"])
        if noise.outputs.get("Fac") is not None:
            tree.links.new(noise.outputs["Fac"], mix.inputs["B"])
    except Exception:
        pass

    bump = tree.nodes.new(type="ShaderNodeBump")
    bump.name = "Pore Bump"
    bump.location = (0.0, -160.0)
    _set_socket(bump, ("Strength",), 0.6)
    _set_socket(bump, ("Distance",), 0.02)
    try:
        tree.links.new(mix.outputs["Result"], bump.inputs["Height"])
    except Exception:
        pass

    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.name = "Skin BSDF"
    bsdf.location = (220.0, 0.0)
    _set_socket(bsdf, ("Base Color",), list(base_color))
    _set_socket(bsdf, ("Roughness",), float(roughness))
    _set_socket(bsdf, ("Subsurface Weight", "Subsurface"), float(subsurface))
    _set_socket(bsdf, ("Subsurface Radius",),
                (0.9, 0.35, 0.2))
    _set_socket(bsdf, ("Subsurface Color",),
                [base_color[0] * 0.55, base_color[1] * 0.28,
                 base_color[2] * 0.22, 1.0])
    try:
        normal_socket = _find_input(bsdf, ("Normal",))
        if normal_socket is not None:
            tree.links.new(bump.outputs["Normal"], normal_socket)
    except Exception:
        pass

    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.name = "Material Output"
    output.location = (460.0, 0.0)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return {
        "success": True,
        "name": mat.name,
        "material": mat.name,
        "base_color": [round(c, 6) for c in base_color],
        "subsurface": subsurface,
        "roughness": roughness,
        "pore_scale": pore_scale,
        "nodes": {node.name: node.bl_idname for node in tree.nodes},
        "limitations": _PRO_LIMITATIONS,
    }


def create_dental_arch(server, name="DentalArchPro", width=0.05,
                       depth=0.04, tooth_count=16) -> dict:
    """Create upper/lower tooth arches with typed teeth in one mesh."""
    _ = server
    name = _validate_name(name)
    width = _validate_float(width, "width", minimum=0.01, maximum=0.3)
    depth = _validate_float(depth, "depth", minimum=0.01, maximum=0.3)
    tooth_count = _validate_int(tooth_count, "tooth_count",
                                minimum=2, maximum=32)

    upper_count = (tooth_count + 1) // 2
    lower_count = tooth_count // 2

    def tooth_type(frac):
        if frac > 0.72:
            return "molar"
        if frac > 0.48:
            return "premolar"
        if frac > 0.28:
            return "canine"
        return "incisor"

    crown_scale = {
        "incisor": (1.0, 0.7, 1.3),
        "canine": (0.85, 0.7, 1.5),
        "premolar": (0.95, 0.85, 1.1),
        "molar": (1.15, 1.0, 0.9),
    }
    crown_height = {
        "incisor": 0.009, "canine": 0.010, "premolar": 0.008, "molar": 0.007,
    }

    bm = bmesh.new()
    type_counts = {"incisor": 0, "canine": 0, "premolar": 0, "molar": 0}
    placements = []
    gap = 0.0015
    for arch, count, sign in (("upper", upper_count, 1.0),
                              ("lower", lower_count, -1.0)):
        if count == 0:
            continue
        slot = width / count
        tooth_w = slot * 0.72
        for i in range(count):
            t = (i / (count - 1.0)) * 2.0 - 1.0 if count > 1 else 0.0
            kind = tooth_type(abs(t))
            type_counts[kind] += 1
            x = t * width / 2.0
            y = (t * t) * depth * 0.5 - depth * 0.30
            ch = crown_height[kind]
            zc = sign * (gap + ch / 2.0)
            # Crown (enamel, slot 0).
            start = set(bm.faces)
            _ball(bm, tooth_w * 0.5, (x, y, zc), u_segments=12, v_segments=10,
                  scale=crown_scale[kind])
            bm.faces.ensure_lookup_table()
            for face in set(bm.faces) - start:
                face.material_index = 0
            if kind == "molar":
                start = set(bm.faces)
                _ball(bm, tooth_w * 0.28, (x + tooth_w * 0.22, y, zc),
                      u_segments=8, v_segments=6)
                bm.faces.ensure_lookup_table()
                for face in set(bm.faces) - start:
                    face.material_index = 0
            # Root (dentin, slot 1), pointing away from the bite plane.
            start = set(bm.faces)
            geo = bmesh.ops.create_cone(
                bm, cap_ends=True, segments=8,
                radius1=tooth_w * 0.30, radius2=tooth_w * 0.12,
                depth=ch * 0.9,
            )
            root_verts = geo["verts"]
            if sign < 0.0:
                bmesh.ops.rotate(
                    bm, cent=Vector((0.0, 0.0, 0.0)),
                    matrix=Matrix.Rotation(math.pi, 3, "X"),
                    verts=root_verts,
                )
            bmesh.ops.translate(
                bm, vec=Vector((x, y, zc + sign * (ch * 0.5 + ch * 0.4))),
                verts=root_verts,
            )
            bm.faces.ensure_lookup_table()
            for face in set(bm.faces) - start:
                face.material_index = 1
            placements.append({"arch": arch, "type": kind,
                               "position": [round(x, 6), round(y, 6),
                                            round(zc, 6)]})

    enamel = _simple_principled(name + "_Enamel", (0.93, 0.90, 0.82, 1.0), 0.3)
    dentin = _simple_principled(name + "_Dentin", (0.85, 0.72, 0.55, 1.0), 0.6)
    obj, dims, polys = _finish(bm, name, [enamel, dentin])
    _add_planar_uv(obj)
    obj.location = (0.0, 0.0, 0.0)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "width": width,
        "depth": depth,
        "tooth_count": upper_count + lower_count,
        "arches": {"upper": upper_count, "lower": lower_count},
        "types": type_counts,
        "placements": placements,
        "materials": [enamel.name, dentin.name],
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "limitations": _PRO_LIMITATIONS,
    }


def create_character_body_pro(server, name="BodyPro", height=1.75,
                              build="average", subdivisions=1) -> dict:
    """Create a grounded unified organic body base ~height tall."""
    _ = server
    name = _validate_name(name)
    height = _validate_float(height, "height", minimum=0.3, maximum=3.0)
    build = _validate_build(build)
    subdivisions = _validate_int(subdivisions, "subdivisions",
                                 minimum=0, maximum=4)

    wf = {"slim": 0.85, "average": 1.0, "heavy": 1.22}[build]
    df = {"slim": 0.92, "average": 1.0, "heavy": 1.18}[build]
    h = height

    head_r = h / 15.0
    head_z = h - head_r * 1.05
    hip_z = 0.52 * h
    hip_x = 0.055 * h * wf
    shoulder_z = 0.815 * h
    shoulder_x = 0.095 * h * wf + 0.03 * h
    foot_h = 0.045 * h

    bm = bmesh.new()
    # Feet (toes toward -Y) and legs.
    foot_len, foot_w = 0.145 * h, 0.055 * h * wf
    leg_depth = hip_z - foot_h
    for sign in (-1.0, 1.0):
        _box(bm, foot_w, foot_len, foot_h,
             (sign * hip_x, -0.03 * h, foot_h / 2.0))
        _limb(bm, 0.075 * h * wf, 0.048 * h * wf, leg_depth,
              (sign * hip_x, 0.0, foot_h + leg_depth / 2.0), segments=14)
    # Pelvis, abdomen, chest: overlapping ellipsoids read as one torso.
    _ball(bm, 0.5, (0.0, 0.0, 0.585 * h), u_segments=20, v_segments=14,
          scale=(0.165 * h * wf, 0.105 * h * df, 0.13 * h))
    _ball(bm, 0.5, (0.0, -0.005 * h, 0.66 * h), u_segments=20, v_segments=14,
          scale=(0.175 * h * wf, 0.110 * h * df, 0.14 * h))
    _ball(bm, 0.5, (0.0, -0.005 * h, 0.745 * h), u_segments=20, v_segments=14,
          scale=(0.200 * h * wf, 0.120 * h * df, 0.13 * h))
    # Arms with slight outward tilt + hands.
    arm_len = shoulder_z - 0.56 * h
    for sign in (-1.0, 1.0):
        _limb(bm, 0.040 * h * wf, 0.030 * h * wf, arm_len,
              (sign * shoulder_x, 0.0, shoulder_z - arm_len / 2.0),
              segments=12, tilt_y=sign * -0.09)
        _box(bm, 0.045 * h * wf, 0.05 * h, 0.10 * h,
             (sign * (shoulder_x + 0.035 * h), 0.0, 0.51 * h))
    # Neck and head (head top lands exactly on height).
    _limb(bm, 0.032 * h, 0.037 * h, 0.07 * h, (0.0, 0.0, 0.845 * h),
          segments=12)
    _ball(bm, head_r, (0.0, 0.008 * h, head_z), u_segments=22, v_segments=16,
          scale=(0.88, 0.95, 1.05))

    # Organic pass: relax faceted primitives into one smooth base.
    bm.verts.ensure_lookup_table()
    for _ in range(2):
        bmesh.ops.smooth_vert(bm, verts=list(bm.verts), factor=0.5)
    _cleanup(bm)
    _normalize_height_center(bm, h)

    skin = _simple_principled(name + "_Skin", (0.65, 0.45, 0.35, 1.0), 0.55)
    obj, dims, polys = _finish(bm, name, [skin])
    _add_planar_uv(obj)
    obj.location = (0.0, 0.0, 0.0)
    if subdivisions:
        _add_subsurf(obj, subdivisions)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "height": height,
        "build": build,
        "subdivisions": subdivisions,
        "dimensions": [round(v, 6) for v in dims],
        "actual_height": round(dims[2], 6),
        "polygon_count": polys,
        "parts": ["feet", "legs", "pelvis", "abdomen", "chest", "arms",
                  "hands", "neck", "head"],
        "materials": [skin.name],
        "limitations": _PRO_LIMITATIONS,
    }


def create_garment_shell_pro(server, name="GarmentPro", body_width=0.40,
                             body_depth=0.22, torso_height=0.55,
                             garment_type="shirt") -> dict:
    """Create a grounded garment shell (shirt/jacket/pants) with trim."""
    _ = server
    name = _validate_name(name)
    body_width = _validate_float(body_width, "body_width",
                                 minimum=0.1, maximum=2.0)
    body_depth = _validate_float(body_depth, "body_depth",
                                 minimum=0.05, maximum=2.0)
    torso_height = _validate_float(torso_height, "torso_height",
                                   minimum=0.1, maximum=2.5)
    garment_type = _validate_garment(garment_type)

    subdivisions = 2
    top_w, top_d = body_width * 1.06, body_depth * 1.12

    fabric = _simple_principled(name + "_Fabric", (0.25, 0.32, 0.50, 1.0), 0.85)
    trim = _simple_principled(name + "_Trim", (0.08, 0.08, 0.10, 1.0), 0.6)
    materials = [fabric, trim]
    parts = []

    def mark_trim():
        bm.faces.ensure_lookup_table()
        for face in set(bm.faces) - mark_trim.seen:
            face.material_index = 1
        mark_trim.seen = set(bm.faces)
    mark_trim.seen = set()

    bm = bmesh.new()
    if garment_type in ("shirt", "jacket"):
        flare = {"shirt": 1.0, "jacket": 1.08}[garment_type]
        sleeve_len = {"shirt": 0.22, "jacket": 0.52}[garment_type]
        bot_w, bot_d = body_width * flare, body_depth * flare
        mid_w, mid_d = (top_w + bot_w) / 2.0, (top_d + bot_d) / 2.0
        mark_trim.seen = set(bm.faces)
        _box(bm, top_w, top_d, torso_height * 0.30,
             (0.0, 0.0, torso_height * 0.85))
        _box(bm, mid_w, mid_d, torso_height * 0.35,
             (0.0, 0.0, torso_height * 0.525))
        _box(bm, bot_w, bot_d, torso_height * 0.35,
             (0.0, 0.0, torso_height * 0.175))
        parts += ["torso_shoulders", "torso_waist", "torso_hem"]
        # Sleeves angled down/out from the shoulders.
        shoulder_z = torso_height * 0.88
        for sign in (-1.0, 1.0):
            geo = bmesh.ops.create_cone(
                bm, cap_ends=True, segments=12,
                radius1=0.055, radius2=0.075, depth=sleeve_len,
            )
            verts = geo["verts"]
            bmesh.ops.rotate(
                bm, cent=Vector((0.0, 0.0, 0.0)),
                matrix=Matrix.Rotation(math.pi / 2.0 + sign * -0.35, 3, "Y"),
                verts=verts,
            )
            bmesh.ops.translate(
                bm, vec=Vector((sign * (top_w / 2.0 + sleeve_len / 2.0 * 0.9),
                                0.0, shoulder_z - 0.06)),
                verts=verts,
            )
        parts += ["sleeve_L", "sleeve_R"]
        # Collar ring + hem band in trim.
        mark_trim.seen = set(bm.faces)
        collar_verts = _torus(bm, top_w * 0.22, 0.018, 20, 8)
        bmesh.ops.translate(
            bm, vec=Vector((0.0, 0.0, torso_height * 1.0)),
            verts=collar_verts,
        )
        parts.append("collar")
        mark_trim()
        if garment_type == "jacket":
            mark_trim.seen = set(bm.faces)
            _box(bm, 0.03, 0.012, torso_height * 0.9,
                 (0.0, -top_d / 2.0 - 0.004, torso_height * 0.5))
            parts.append("zipper_strip")
            mark_trim()
    else:  # pants
        leg_len = torso_height * 1.15
        total_h = torso_height * 0.45 + leg_len
        waist_w, waist_d = body_width * 1.04, body_depth * 1.10
        # Waist block + two tapered legs.
        mark_trim.seen = set(bm.faces)
        _box(bm, waist_w, waist_d, torso_height * 0.45,
             (0.0, 0.0, leg_len + torso_height * 0.225))
        parts.append("waist")
        for sign in (-1.0, 1.0):
            _limb(bm, 0.09 * body_width, 0.065 * body_width, leg_len,
                  (sign * waist_w * 0.26, 0.0, leg_len / 2.0), segments=12)
        parts += ["leg_L", "leg_R"]
        # Waistband in trim.
        mark_trim.seen = set(bm.faces)
        geo = bmesh.ops.create_torus(
            bm, major_rad=waist_w * 0.32, minor_rad=0.015,
            major_seg=20, minor_seg=8,
        )
        bmesh.ops.scale(bm, vec=Vector((1.0, waist_d / max(waist_w, 1e-6), 1.0)),
                        verts=geo["verts"])
        bmesh.ops.translate(
            bm, vec=Vector((0.0, 0.0, total_h)), verts=geo["verts"])
        parts.append("waistband")
        mark_trim()
        torso_height = total_h

    _cleanup(bm)
    # Ground the shell: base at Z=0, centered on the origin.
    bm.verts.ensure_lookup_table()
    min_z = min(v.co.z for v in bm.verts)
    for vert in bm.verts:
        vert.co.z -= min_z

    obj, dims, polys = _finish(bm, name, materials)
    obj.location = (0.0, 0.0, 0.0)
    _add_subsurf(obj, subdivisions)

    return {
        "success": True,
        "name": obj.name,
        "object": obj.name,
        "garment_type": garment_type,
        "body_width": body_width,
        "body_depth": body_depth,
        "torso_height": round(torso_height, 6),
        "subdivisions": subdivisions,
        "dimensions": [round(v, 6) for v in dims],
        "polygon_count": polys,
        "parts": parts,
        "materials": [mat.name for mat in materials],
        "limitations": _PRO_LIMITATIONS,
    }
