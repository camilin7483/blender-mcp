"""Build and render the original PELAGOS 07 inspection ROV in Blender.

Run: blender -b --factory-startup --python-exit-code 1 --python scripts/render_showcase.py -- --output out/showcase
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pro"))

from blender_mcp import BlenderMCPServer, GeometryService  # noqa: E402

TAU = math.tau


def arguments(description=__doc__):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--samples", type=int, default=36)
    parser.add_argument("--check-only", action="store_true", help="Save and verify the scene without rendering.")
    parser.add_argument("--detail", action="store_true", help="Render the close-up camera as well.")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


class Showcase:
    def __init__(self, material_prefix="Pelagos"):
        self.server = BlenderMCPServer(port=0)
        self.material_prefix = material_prefix
        self.materials = {}
        self.group = None
        self.pro_calls = 0

    def collection(self, name):
        group = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(group)
        self.group = group
        return group

    def place(self, obj):
        for group in tuple(obj.users_collection):
            group.objects.unlink(obj)
        self.group.objects.link(obj)
        return obj

    def material(self, key, color, metal, rough, *, glow=0, texture=0):
        name = f"{self.material_prefix} / {key}"
        result = self.server.create_material(name, [*color, 1.0], metallic=metal, roughness=rough)
        self.pro_calls += 1
        material = bpy.data.materials[result["material"]]
        self.materials[key] = material
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        if glow:
            bsdf.inputs["Emission Color"].default_value = (*color, 1)
            bsdf.inputs["Emission Strength"].default_value = glow
        if texture:
            noise = nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = 145
            noise.inputs["Detail"].default_value = 2
            bump = nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = texture
            bump.inputs["Distance"].default_value = 0.012
            links.new(noise.outputs["Fac"], bump.inputs["Height"])
            links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        return material

    def box(self, name, loc, size, material, bevel=0.04, angle=0.0):
        result = self.server.create_parametric_part(
            name, shape="ROUNDED_BOX", dimensions=list(size), location=list(loc),
            rotation_deg=[0, 0, math.degrees(angle)], origin="CENTER",
            bevel_width=bevel, bevel_segments=3, material_name=self.materials[material].name,
        )
        self.pro_calls += 1
        return self.place(bpy.data.objects[result["name"]])

    def mesh(self, name, points, faces, material, bevel=0.0, *, smooth=False, normals=False):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(points, [], faces)
        mesh.update()
        if normals:
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.to_mesh(mesh)
            bm.free()
        obj = bpy.data.objects.new(name, mesh)
        self.group.objects.link(obj)
        obj.data.materials.append(self.materials[material])
        if smooth:
            for face in mesh.polygons:
                face.use_smooth = len(face.vertices) == 4
        if bevel:
            mod = obj.modifiers.new("Machined edge radii", "BEVEL")
            mod.width, mod.segments = bevel, 3
            mod.harden_normals = True
            obj.modifiers.new("Weighted product normals", "WEIGHTED_NORMAL")
        return obj

    def loft(self, name, levels, material, bevel):
        """Create a closed panel shell from equal-length sections."""
        n = len(levels[0][1])
        vertices = [(x, y, z) for z, section in levels for x, y in section]
        faces = [tuple(reversed(range(n)))]
        for r in range(len(levels) - 1):
            for i in range(n):
                a, b = r * n + i, r * n + (i + 1) % n
                faces.append((a, b, b + n, a + n))
        faces.append(tuple(range(len(vertices) - n, len(vertices))))
        return self.mesh(name, vertices, faces, material, bevel)

    def disk(self, name, center, radius, depth, material, *, sides=64, bevel=0.0, axis="Y"):
        bpy.ops.mesh.primitive_cylinder_add(vertices=sides, radius=radius, depth=depth, location=center)
        obj = self.place(bpy.context.object)
        obj.name = name
        if axis == "Y":
            obj.rotation_euler.x = math.pi / 2
        elif axis == "X":
            obj.rotation_euler.y = math.pi / 2
        obj.data.materials.append(self.materials[material])
        for p in obj.data.polygons:
            p.use_smooth = len(p.vertices) == 4
        if bevel:
            mod = obj.modifiers.new("Edge radius", "BEVEL")
            mod.width, mod.segments = bevel, 3
            mod.harden_normals = True
            obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
        return obj

    def lathe(self, name, center, profile, material, *, segments=96, axis="Y"):
        """Revolve a closed annular section around the local Z axis."""
        coordinates = [
            (radius * math.cos(TAU * i / segments), radius * math.sin(TAU * i / segments), depth)
            for radius, depth in profile for i in range(segments)
        ]
        faces = []
        for j in range(len(profile)):
            next_j = (j + 1) % len(profile)
            for i in range(segments):
                k = (i + 1) % segments
                faces.append((j * segments + i, j * segments + k, next_j * segments + k, next_j * segments + i))
        obj = self.mesh(name, coordinates, faces, material, smooth=True, normals=True)
        obj.location = center
        if axis == "Y":
            obj.rotation_euler.x = -math.pi / 2
        return obj

    def tube(self, name, points, radius, material, *, smooth=True):
        curve = bpy.data.curves.new(name, "CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 16
        curve.bevel_depth = radius
        curve.bevel_resolution = 4
        curve.use_fill_caps = True
        spline = curve.splines.new("BEZIER" if smooth else "POLY")
        if smooth:
            spline.bezier_points.add(len(points) - 1)
            for p, coord in zip(spline.bezier_points, points, strict=True):
                p.co = coord
                p.handle_left_type = p.handle_right_type = "AUTO"
        else:
            spline.points.add(len(points) - 1)
            for p, coord in zip(spline.points, points, strict=True):
                p.co = (*coord, 1.0)
        obj = bpy.data.objects.new(name, curve)
        self.group.objects.link(obj)
        curve.materials.append(self.materials[material])
        return obj

    def label(self, name, body, loc, size, material, *, front=False, align="LEFT"):
        curve = bpy.data.curves.new(name, "FONT")
        curve.body = body
        curve.size = size
        curve.space_character = 1.15
        curve.align_x = align
        obj = bpy.data.objects.new(name, curve)
        self.group.objects.link(obj)
        obj.location = loc
        if front:
            obj.rotation_euler.x = math.pi / 2
        curve.materials.append(self.materials[material])
        return obj


def outline(w, length, shoulder):
    return [
        (-w * 0.69, -length), (w * 0.69, -length), (w, -length * shoulder),
        (w, length * 0.59), (w * 0.72, length), (-w * 0.72, length),
        (-w, length * 0.59), (-w, -length * shoulder),
    ]


def build_hull(demo):
    demo.collection("01 / Pressure hull and armour")
    demo.loft("Hull | graphite pressure housing", [
        (1.18, outline(0.83, 1.07, 0.65)), (1.34, outline(1.04, 1.19, 0.69)),
        (1.92, outline(1.04, 1.19, 0.69)), (2.08, outline(0.78, 1.05, 0.60)),
    ], "graphite", 0.072)
    demo.loft("Hull | ceramic monocoque", [
        (1.63, outline(0.99, 1.26, 0.62)), (1.84, outline(1.10, 1.35, 0.64)),
        (2.19, outline(1.00, 1.18, 0.57)), (2.33, outline(0.79, 0.98, 0.54)),
    ], "ceramic", 0.085)
    demo.loft("Dorsal service hatch", [
        (2.333, outline(0.57, 0.73, 0.55)), (2.372, outline(0.55, 0.70, 0.55)),
    ], "graphite", 0.027)
    demo.loft("Dorsal thermal cover", [
        (2.375, outline(0.515, 0.66, 0.55)), (2.415, outline(0.49, 0.63, 0.55)),
    ], "teal", 0.029)
    demo.label("Vehicle marking", "P E L A G O S", (-0.365, -0.39, 2.416), 0.123, "white")
    demo.label("Vehicle class", "07  /  ABYSSAL SURVEY", (-0.358, -0.52, 2.416), 0.044, "white")
    for i in range(8):
        demo.box(f"Dorsal grille {i + 1:02}", (0, 0.03 + i * 0.061, 2.422), (0.63, 0.024, 0.025), "steel", 0.006)
    for side in (-1, 1):
        for y in (-0.43, 0.30, 0.81):
            demo.box(f"Shoulder seam {side} {y}", (side * 0.733, y, 2.31),
                     (0.11, 0.33, 0.045), "graphite", 0.01)
        for i in range(4):
            demo.box(f"Service caution marking {side} {i}", (side * (0.66 + i * 0.062), 0.57, 2.334),
                     (0.028, 0.102, 0.012), "yellow", 0.002, angle=-0.44)
        demo.label(f"Pressure shell marking {side}", "O7 / ROV", (side * 0.75 - 0.11, -0.45, 2.34),
                   0.042, "ink")
        for i in range(7):
            demo.box(f"Side cooling fins {side} {i:02}", (
                side * 1.027, 0.11 + i * 0.112, 1.555,
            ), (0.12, 0.061, 0.24), "steel", 0.015)
        for y in (-0.66, 0.63):
            demo.disk(f"Hatch fastener {side} {y}", (side * 0.635, y, 2.323), 0.048, 0.023,
                      "steel", sides=6, bevel=0.005, axis="Z")
            demo.disk(f"Hatch socket {side} {y}", (side * 0.635, y, 2.336), 0.016, 0.007,
                      "graphite", sides=6, axis="Z")
        demo.box(f"Side sensor rail {side}", (side * 0.90, -0.49, 1.91), (0.23, 0.60, 0.07), "teal", 0.018)


def build_frame(demo):
    demo.collection("02 / Skids, braces and service lines")
    for side in (-1, 1):
        x = side * 0.91
        demo.tube(f"Skid | main {side}", [
            (x, -1.37, 1.25), (x, -1.52, 0.98), (x, -1.40, 0.84),
            (x, -0.99, 0.73), (x, 0.88, 0.73), (x, 1.32, 0.86), (x, 1.45, 1.17),
        ], 0.052, "steel")
        for y in (-0.84, 0.73):
            demo.tube(f"Skid | diagonal brace {side} {y}", [
                (x, y, 0.76), (x, y * 0.75, 1.09), (side * 0.79, y * 0.63, 1.36),
            ], 0.045, "graphite")
            demo.box(f"Skid | rubber foot {side} {y}", (x, y, 0.712), (0.24, 0.31, 0.11), "rubber", 0.039)
        for shift, cable in ((0, "yellow"), (0.09, "teal")):
            demo.tube(f"Harness {side} {cable}", [
                (side * 0.62, 0.76, 2.13 + shift),
                (side * 1.08, 1.12, 2.11 + shift),
                (side * 1.47, 1.06, 1.97 + shift),
                (side * 1.61, 0.84, 1.65 + shift),
            ], 0.028, cable)
        demo.tube(f"Carry handle {side}", [
            (side * 0.88, -0.65, 2.18), (side * 0.92, -0.45, 2.48), (side * 0.92, 0.14, 2.48),
            (side * 0.84, 0.32, 2.30),
        ], 0.036, "yellow")
        demo.box(f"Thruster carrier {side}", (side * 1.28, 0.25, 1.64), (0.89, 0.49, 0.23), "graphite", 0.08)
        demo.box(f"Carrier cap {side}", (side * 1.24, 0.25, 1.79), (0.75, 0.30, 0.10), "teal", 0.036)


def build_thrusters(demo):
    demo.collection("03 / Counter-rotating propulsion pods")
    for side in (-1, 1):
        x, y, z = side * 1.72, 0.21, 1.67
        prefix = f"Thruster {'R' if side > 0 else 'L'}"
        demo.lathe(f"{prefix} | ceramic duct", (x, y, z), [
            (0.46, -0.47), (0.52, -0.49), (0.62, -0.44), (0.68, -0.32),
            (0.69, 0.13), (0.65, 0.32), (0.59, 0.47), (0.49, 0.49),
            (0.42, 0.37), (0.44, 0.11), (0.465, -0.24),
        ], "ceramic")
        demo.lathe(f"{prefix} | machined rim", (x, y, z), [
            (0.46, -0.492), (0.49, -0.517), (0.565, -0.506), (0.596, -0.466),
            (0.588, -0.449), (0.51, -0.468), (0.47, -0.458),
        ], "titanium")
        demo.lathe(f"{prefix} | seal", (x, y, z), [
            (0.454, -0.436), (0.48, -0.476), (0.492, -0.468), (0.486, -0.423),
        ], "teal")
        demo.lathe(f"{prefix} | stator liner", (x, y, z), [
            (0.411, -0.33), (0.454, -0.36), (0.455, 0.32), (0.41, 0.34),
        ], "graphite")
        demo.disk(f"{prefix} | rear bearing", (x, y + 0.16, z), 0.145, 0.40, "graphite", bevel=0.020)
        demo.disk(f"{prefix} | impeller hub", (x, y - 0.21, z), 0.133, 0.105, "titanium", bevel=0.024)
        demo.disk(f"{prefix} | axle cap", (x, y - 0.27, z), 0.058, 0.04, "yellow", sides=8, bevel=0.008)
        for i in range(7):
            angle = i * TAU / 7
            section = [(0.105, -0.12), (0.237, -0.24), (0.414, -0.33),
                       (0.405, 0.09), (0.303, 0.34), (0.123, 0.32)]
            points = [
                (x + r * math.cos(angle + side * sweep), y - 0.18 + d + (r - 0.12) * 0.34,
                 z + r * math.sin(angle + side * sweep))
                for d in (-0.024, 0.024) for r, sweep in section
            ]
            demo.mesh(f"{prefix} | swept impeller blade {i + 1}", points, [
                (5, 4, 3, 2, 1, 0), (6, 7, 8, 9, 10, 11),
                *((i, (i + 1) % 6, (i + 1) % 6 + 6, i + 6) for i in range(6)),
            ], "teal", 0.013, normals=True)
        for i in range(10):
            angle = (i + 0.5) * TAU / 10
            demo.disk(f"{prefix} | rim socket {i + 1}", (
                x + 0.546 * math.cos(angle), y - 0.518, z + 0.546 * math.sin(angle),
            ), 0.020, 0.015, "rubber", sides=6, bevel=0.003)
        demo.box(f"{prefix} | top instrumentation", (x, y + 0.025, z + 0.687),
                 (0.37, 0.47, 0.083), "graphite", 0.038)
        for i in range(5):
            demo.box(f"{prefix} | five status lamps {i}", (x - 0.107 + 0.054 * i, y + 0.004, z + 0.734),
                     (0.021, 0.112, 0.009), "sea light" if i != 4 else "amber light", 0.003)


def build_optics(demo):
    demo.collection("04 / Sonar and imaging")
    for side in (-1, 1):
        x = side * 0.59
        demo.box(f"Floodlight mount {side}", (x, -1.195, 1.67), (0.37, 0.35, 0.41), "graphite", 0.062)
        demo.disk(f"Floodlight flange {side}", (x, -1.392, 1.676), 0.144, 0.143,
                  "titanium", sides=12, bevel=0.016)
        demo.disk(f"Floodlight glass {side}", (x, -1.469, 1.676), 0.103, 0.029, "sea light", bevel=0.016)
        for i in range(3):
            demo.box(f"Identification stripe {side} {i}", (
                side * (0.54 + i * 0.102), -0.96, 2.211 - i * 0.017,
            ), (0.063, 0.157, 0.014), "yellow", 0.003, angle=-side * 0.35)
    center = (0, -1.40, 1.59)
    demo.disk("Optic | gimbal housing", center, 0.369, 0.38, "graphite", sides=12, bevel=0.039)
    for title, radius, y, depth, mat in (
        ("shoulder", 0.327, -1.595, 0.099, "titanium"),
        ("lens bezel", 0.295, -1.657, 0.10, "graphite"),
        ("copper tolerance ring", 0.264, -1.717, 0.028, "copper"),
        ("optical gasket", 0.246, -1.735, 0.025, "rubber"),
        ("optical glass", 0.218, -1.751, 0.028, "optical glass"),
    ):
        demo.disk("Optic | " + title, (0, y, center[2]), radius, depth, mat, bevel=0.009)
    for radius, mat in ((0.190, "teal"), (0.157, "sea light"), (0.088, "teal")):
        demo.lathe(f"Optic | circular coating {radius}", (0, -1.767, center[2]), [
            (radius - 0.004, 0), (radius + 0.004, 0), (radius + 0.003, 0.006), (radius - 0.003, 0.006),
        ], mat)
    demo.disk("Optic | pupil", (0.018, -1.776, 1.603), 0.072, 0.013, "optical glass", bevel=0.005)
    for i in range(18):
        a = i * TAU / 18
        demo.disk(f"Optic | grip stud {i + 1}", (0.306 * math.cos(a), -1.689, 1.59 + 0.306 * math.sin(a)),
                  0.012, 0.026, "steel", sides=8, bevel=0.003)
    demo.box("Sonar bar | ceramic rail", (0, -1.067, 2.165), (1.10, 0.13, 0.151), "graphite", 0.037)
    for i in range(13):
        mat = "sea light" if i in (0, 1, 2, 3, 9, 10, 11, 12) else "steel"
        demo.box(f"Sonar bar | pixel {i + 1}", ((i - 6) * 0.071, -1.139, 2.165), (0.034, 0.014, 0.028),
                 mat, 0.004)


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def build_stage(demo):
    demo.collection("05 / Studio plinth and graphics")
    demo.box("Stage | slate plinth", (0, -0.02, 0.49), (5.59, 3.62, 0.16), "plinth", 0.135)
    demo.box("Stage | base", (0, -0.02, 0.345), (5.42, 3.46, 0.14), "graphite", 0.13)
    for side in (-1, 1):
        demo.box(f"Stage | raised dock rail {side}", (side * 0.91, -0.05, 0.602),
                 (0.31, 2.33, 0.125), "steel", 0.025)
        for i in range(3):
            demo.box(f"Stage | alignment marker {side} {i}", (side * (2.07 + i * 0.10), -1.34, 0.573),
                     (0.06, 0.32, 0.012), "yellow", 0.003, angle=-0.42)
    demo.box("Stage | engraved plate", (0.07, -1.48, 0.578), (2.80, 0.47, 0.037), "graphite", 0.025)
    demo.label("Stage title", "P E L A G O S   /   0 7", (-1.14, -1.48, 0.598), 0.188, "white")
    demo.label("Stage label", "DEEP SURVEY ROV    //    ENGINEERING  PROTOTYPE", (-1.13, -1.62, 0.598), 0.068, "yellow")
    demo.box("Stage | front light guide", (0, -1.808, 0.44), (4.63, 0.015, 0.018), "teal", 0.004)
    demo.box("Studio | floor", (0, 0, 0.12), (200, 200, 0.30), "floor", 0)
    for i in range(-6, 7):
        demo.box(f"Studio | scale line {i:+}", (i * 0.68, -2.25, 0.272), (0.013, 0.36, 0.004), "ink", 0)
    demo.box("Studio | scale baseline", (0, -2.25, 0.271), (8.5, 0.012, 0.004), "ink", 0)

    demo.collection("06 / Cameras and studio lighting")
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("Pelagos")
    scene.world = world
    if world.node_tree is None:
        world.use_nodes = True
    world.node_tree.nodes.get("Background").inputs["Color"].default_value = (0.105, 0.15, 0.19, 1)
    world.node_tree.nodes.get("Background").inputs["Strength"].default_value = 0.30

    def light(name, location, target, power, color, size, size_y=None):
        data = bpy.data.lights.new(name, "AREA")
        lamp = bpy.data.objects.new(name, data)
        demo.group.objects.link(lamp)
        lamp.location = location
        data.energy, data.color, data.size = power, color, size
        if size_y is not None:
            data.shape, data.size_y = "RECTANGLE", size_y
        aim(lamp, target)

    light("Key | overhead softbox", (-3.5, -4.3, 7.1), (0, 0, 1.1), 1400, (0.84, 0.92, 1.0), 4.0, 3.0)
    light("Edge | ice-blue strip", (1.9, 3.4, 5.2), (0, 0.2, 1.4), 1700, (0.31, 0.71, 1.0), 4.1, 1.2)
    light("Edge | warm strip", (5.5, -0.6, 3.6), (0, 0, 1.2), 1000, (1.0, 0.72, 0.46), 2.6, 0.85)
    light("Fill | lens reflection", (-0.2, -5.7, 2.5), (0, 0.1, 1.6), 160, (0.52, 0.76, 1.0), 2.0, 0.5)
    light("Backdrop pool", (-4, 5, 6), (-1, 4, 0), 750, (0.20, 0.58, 0.79), 4)

    def camera(name, eye, target, lens):
        data = bpy.data.cameras.new(name)
        obj = bpy.data.objects.new(name, data)
        demo.group.objects.link(obj)
        obj.location = eye
        aim(obj, target)
        data.lens = lens
        return obj

    hero = camera("Hero / three-quarter", (5.15, -9.90, 5.62), (0.0, 0, 1.40), 53)
    detail = camera("Detail / optics and impeller", (3.81, -6.74, 3.49), (0.52, -0.31, 1.78), 69)
    scene.camera = hero
    scene.render.engine = "CYCLES"
    scene.cycles.use_denoising = True
    scene.cycles.adaptive_threshold = 0.025
    scene.cycles.max_bounces = 6
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    return hero, detail


def main():
    args = arguments()
    if args.width < 128 or args.samples < 1:
        raise ValueError("Width must be at least 128 pixels and samples must be positive.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    demo = Showcase()
    demo.server.clear_scene(confirm=True)
    for name, color, metal, rough, texture, glow in (
        ("ceramic", (0.34, 0.43, 0.39), 0.24, 0.32, 0.17, 0),
        ("graphite", (0.026, 0.043, 0.052), 0.52, 0.28, 0.19, 0),
        ("teal", (0.018, 0.255, 0.253), 0.64, 0.26, 0.16, 0),
        ("titanium", (0.29, 0.34, 0.38), 0.89, 0.30, 0.13, 0),
        ("steel", (0.125, 0.174, 0.195), 0.79, 0.30, 0.14, 0),
        ("rubber", (0.013, 0.019, 0.024), 0.05, 0.52, 0.09, 0),
        ("yellow", (0.94, 0.38, 0.025), 0.28, 0.30, 0.12, 0),
        ("copper", (0.63, 0.25, 0.063), 0.87, 0.28, 0.12, 0),
        ("sea light", (0.037, 0.80, 0.76), 0.23, 0.20, 0.0, 2.4),
        ("amber light", (0.96, 0.32, 0.03), 0.08, 0.29, 0.0, 2.0),
        ("optical glass", (0.007, 0.096, 0.145), 0.69, 0.13, 0, 0),
        ("floor", (0.043, 0.063, 0.078), 0.36, 0.33, 0.12, 0),
        ("ink", (0.09, 0.15, 0.18), 0.34, 0.48, 0, 0),
        ("plinth", (0.071, 0.097, 0.116), 0.52, 0.30, 0.17, 0),
        ("white", (0.77, 0.91, 0.87), 0.23, 0.33, 0, 0),
    ):
        demo.material(name, color, metal, rough, texture=texture, glow=glow)

    build_hull(demo)
    build_frame(demo)
    build_thrusters(demo)
    build_optics(demo)
    hero, detail = build_stage(demo)
    scene = bpy.context.scene
    scene.render.resolution_x = args.width
    scene.render.resolution_y = round(args.width * 0.625)
    scene.render.resolution_percentage = 100
    scene.cycles.samples = args.samples
    scene.cycles.seed = 7

    bpy.context.view_layer.update()
    checks = {}
    for name in ("Hull | ceramic monocoque", "Thruster R | ceramic duct", "Thruster L | ceramic duct"):
        metrics = GeometryService.topology_metrics(bpy.data.objects[name])
        keys = ("vertex_count", "face_count", "non_manifold_edges", "disconnected_components")
        checks[name] = {key: metrics[key] for key in keys}
        if metrics["non_manifold_edges"] or metrics["disconnected_components"] != 1:
            raise RuntimeError(f"Invalid showcase mesh: {name}: {checks[name]}")
    scene.render.filepath = "//pelagos-07.png"
    blend = output / "pelagos-07.blend"
    if "FINISHED" not in bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=True):
        raise RuntimeError(f"Could not save {blend}")

    renders = []
    if not args.check_only:
        cameras = [(hero, "pelagos-07.png")]
        if args.detail:
            cameras.append((detail, "pelagos-07-detail.png"))
        for camera, filename in cameras:
            scene.camera = camera
            path = output / filename
            path.unlink(missing_ok=True)
            scene.render.filepath = str(path)
            if "FINISHED" not in bpy.ops.render.render(write_still=True) or not path.is_file():
                raise RuntimeError(f"Could not render {path}")
            renders.append(filename)

    report = {
        "model": "PELAGOS 07",
        "blender": bpy.app.version_string,
        "objects": len(scene.objects),
        "meshes": sum(obj.type == "MESH" for obj in scene.objects),
        "pro_modeling_and_material_calls": demo.pro_calls,
        "evaluated_topology": checks,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "samples": scene.cycles.samples,
        "scene": blend.name,
        "renders": renders,
    }
    (output / "showcase.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("PELAGOS_SHOWCASE_OK")


if __name__ == "__main__":
    main()
