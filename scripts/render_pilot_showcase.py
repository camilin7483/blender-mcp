"""Build, pose and render the original NEREID 07 subsea survey pilot in Blender."""

from __future__ import annotations

import json
import math
import sys
from contextlib import contextmanager
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_showcase import GeometryService, Showcase, aim, arguments, outline  # noqa: E402

RIG_NAME = "Nereid | articulated survey suit"
SHELLS = ("Pressure cuirass", "Helmet | ceramic crown", "Forearm plate.L", "Shin shell.R")
FINGERS = ("Index", "Middle", "Ring", "Little")


def section(radius_x, radius_y, offset_y=0):
    return [(x, y + offset_y) for x, y in outline(radius_x, radius_y, 0.63)]


def oval(demo, name, center, scale, material, direction=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=center)
    obj = demo.place(bpy.context.object)
    obj.name = name
    obj.scale = scale
    if direction is not None:
        obj.rotation_euler = Vector(direction).to_track_quat("Z", "Y").to_euler()
    obj.data.materials.append(demo.materials[material])
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def limb(demo, name, start, end, profiles, material, bevel=0.015):
    start, end = Vector(start), Vector(end)
    axis = end - start
    levels = [(t * axis.length, section(w, d, offset)) for t, w, d, offset in profiles]
    obj = demo.loft(name, levels, material, bevel)
    obj.location = start
    obj.rotation_euler = axis.to_track_quat("Z", "Y").to_euler()
    return obj


def badge(demo, name, text, x, y, z, scale=0.05, material="white"):
    return demo.label(name, text, (x, y, z), scale, material, front=True, align="CENTER")


def materials(demo):
    for name, rgb, metal, rough, bump, glow in (
        ("ceramic", (0.59, 0.52, 0.38), 0.24, 0.32, 0.14, 0),
        ("ceramic dark", (0.22, 0.31, 0.32), 0.42, 0.33, 0.13, 0),
        ("teal", (0.029, 0.27, 0.31), 0.49, 0.29, 0.14, 0),
        ("copper", (0.61, 0.245, 0.066), 0.71, 0.28, 0.09, 0),
        ("steel", (0.29, 0.36, 0.37), 0.85, 0.32, 0.13, 0),
        ("black", (0.018, 0.03, 0.041), 0.41, 0.31, 0.17, 0),
        ("fabric", (0.023, 0.035, 0.050), 0.08, 0.61, 0.44, 0),
        ("ribbing", (0.044, 0.063, 0.076), 0.15, 0.44, 0.24, 0),
        ("glass", (0.015, 0.097, 0.138), 0.67, 0.14, 0, 0),
        ("white", (0.86, 0.91, 0.86), 0.19, 0.41, 0, 0),
        ("aqua", (0.049, 0.81, 0.76), 0.29, 0.28, 0, 3.0),
        ("amber", (1.0, 0.36, 0.052), 0.29, 0.28, 0, 2.5),
        ("floor", (0.035, 0.060, 0.081), 0.39, 0.38, 0.14, 0),
    ):
        demo.material(name, rgb, metal, rough, texture=bump, glow=glow)
    glass = demo.materials["glass"].node_tree.nodes["Principled BSDF"]
    glass.inputs["Coat Weight"].default_value = 0.48
    glass.inputs["Coat Roughness"].default_value = 0.19


def build_torso(demo, group):
    with group("Pelvis", "01 / Pelvis and field kit"):
        demo.loft("Pelvis | pressure undersuit", [
            (1.49, section(0.24, 0.12)), (1.58, section(0.35, 0.20)),
            (1.76, section(0.36, 0.23)), (1.83, section(0.30, 0.18)),
        ], "fabric", 0.078)
        demo.loft("Utility belt | titanium latch band", [
            (1.66, section(0.365, 0.236)), (1.75, section(0.355, 0.233)),
        ], "black", 0.024)
        demo.box("Utility belt | buckle", (0, -0.243, 1.703), (0.17, 0.055, 0.105), "copper", 0.024)
        demo.box("Utility belt | latch", (0, -0.276, 1.702), (0.11, 0.018, 0.026), "black", 0.007)
        for side in (-1, 1):
            x = side * 0.318
            demo.box(f"Belt canister {side}", (x, -0.145, 1.65), (0.145, 0.21, 0.226),
                     "ceramic dark", 0.03, angle=side * 0.48)
            demo.box(f"Canister cap {side}", (x, -0.14, 1.763), (0.14, 0.20, 0.051),
                     "teal", 0.012, angle=side * 0.48)
            for i in range(3):
                demo.box(f"Pouch weave {side} {i}", (x, -0.245, 1.60 + i * 0.034),
                         (0.078, 0.024, 0.012), "black", 0.005, angle=side * 0.48)

    with group("Waist", "02 / Flexible waist seal"):
        demo.loft("Waist | pressure seal", [
            (1.71, section(0.285, 0.179)), (1.85, section(0.268, 0.173)),
            (2.03, section(0.335, 0.208)), (2.12, section(0.38, 0.227)),
        ], "fabric", 0.04)
        for i in range(5):
            z = 1.778 + i * 0.071
            w = 0.273 + 0.014 * i
            depth = 0.188 + i * 0.009
            demo.loft(f"Waist | layered flex bellow {i + 1}", [
                (z - 0.019, section(w - 0.01, depth - 0.01)), (z, section(w, depth)),
                (z + 0.026, section(w, depth)),
            ], "ribbing", 0.013)

    with group("Chest", "03 / Cuirass, display and life support"):
        demo.loft("Chest | structural liner", [
            (1.99, section(0.34, 0.208)), (2.18, section(0.422, 0.258)),
            (2.41, section(0.478, 0.242, 0.017)), (2.52, section(0.33, 0.19, 0.029)),
        ], "black", 0.058)
        demo.loft("Pressure cuirass", [
            (2.025, section(0.328, 0.246, -0.02)), (2.141, section(0.437, 0.284, -0.023)),
            (2.365, section(0.469, 0.280, -0.020)), (2.49, section(0.365, 0.215, 0.008)),
            (2.525, section(0.254, 0.188, 0.01)),
        ], "ceramic", 0.054)
        demo.box("Recessed sternum gauge", (0, -0.296, 2.334), (0.277, 0.069, 0.201), "black", 0.033)
        demo.box("Sternum gauge glass", (0, -0.335, 2.346), (0.223, 0.018, 0.119), "glass", 0.022)
        badge(demo, "Instrument readout", "O2  098", 0, -0.347, 2.35, 0.036, "aqua")
        for i in range(6):
            demo.box(f"Gauge segment {i + 1}", (-0.071 + i * 0.028, -0.347, 2.323), (0.020, 0.006, 0.008),
                     "aqua" if i < 5 else "copper", 0.002)
        badge(demo, "Chest designation", "P E L A G O S", 0, -0.307, 2.173, 0.048, "black")
        badge(demo, "Suit type", "SURVEY DIVISION", 0, -0.301, 2.129, 0.027, "black")
        for side in (-1, 1):
            x = side * 0.331
            demo.box(f"Collarbone plate {side}", (x, -0.241, 2.452), (0.171, 0.081, 0.099),
                     "teal", 0.025, angle=side * 0.33)
            demo.disk(f"Cuirass fastener {side}", (side * 0.259, -0.294, 2.284), 0.026, 0.019,
                      "steel", sides=6, bevel=0.004)
            demo.disk(f"Cuirass screw head {side}", (side * 0.259, -0.305, 2.284), 0.009, 0.007,
                      "black", sides=6)
            demo.box(f"Shoulder guide {side}", (side * 0.263, -0.263, 2.426), (0.08, 0.018, 0.018),
                     "amber", 0.005)
            demo.box(f"Breathing unit {side}", (side * 0.287, 0.272, 2.214), (0.22, 0.28, 0.52),
                     "teal", 0.056)
            demo.disk(f"Gas transfer cap {side}", (side * 0.283, 0.271, 2.475), 0.067, 0.078,
                      "steel", bevel=0.012, axis="Z")
            demo.tube(f"Boost regulator line {side}", [
                (side * 0.28, 0.28, 2.50), (side * 0.34, 0.32, 2.57), (side * 0.43, 0.24, 2.53),
                (side * 0.45, 0.09, 2.37), (side * 0.423, -0.07, 2.25),
            ], 0.024, "ribbing")
        demo.box("Life-support pack", (0, 0.29, 2.253), (0.48, 0.29, 0.59), "ceramic dark", 0.067)
        for i in range(8):
            demo.box(f"Pack cooling fin {i + 1}", (0, 0.45, 2.090 + 0.047 * i),
                     (0.278, 0.036, 0.022), "steel", 0.007)
        demo.disk("Insulated collar base", (0, 0.015, 2.545), 0.217, 0.09, "black", bevel=0.012, axis="Z")
        demo.disk("Collar lock ring", (0, 0.015, 2.593), 0.192, 0.047, "copper", bevel=0.01, axis="Z")


def build_helmet(demo, group):
    with group("Head", "04 / Helmet, glazing and sensors"):
        oval(demo, "Helmet | pressure seal", (0.025, -0.018, 2.788), (0.283, 0.245, 0.261), "black")
        oval(demo, SHELLS[1], (0.025, 0.021, 2.850), (0.282, 0.244, 0.264), "ceramic")
        # Local coordinates give the visor and helmet the same slight turn.
        def visor_point(x, y, z):
            return (x + 0.029 + y * 0.09, y - x * 0.09, z)

        border = [(-0.215, 2.876), (-0.187, 2.957), (-0.118, 2.992), (0.133, 2.992),
                  (0.198, 2.945), (0.215, 2.867), (0.166, 2.77), (0.094, 2.749),
                  (-0.108, 2.749), (-0.177, 2.785)]
        for scale, shift, name, material in (
            (1.15, 0.015, "Helmet | titanium visor frame", "black"),
            (1.00, 0.0, "Helmet | curved visored glazing", "glass"),
        ):
            ring = [(x * scale, 2.873 + (z - 2.873) * scale) for x, z in border]
            points = [(0.0, -0.306 + shift, 2.879)]
            points.extend((x * 0.62, -0.300 + shift + abs(x) * 0.034, 2.869 + (z - 2.869) * 0.62)
                          for x, z in ring)
            points.extend((x, -0.274 + shift + abs(x) * 0.29, z) for x, z in ring)
            points.extend((x, -0.225 + shift + abs(x) * 0.29, z) for x, z in ring)
            n = len(ring)
            faces = [(0, 1 + i, 1 + (i + 1) % n) for i in range(n)]
            for start in (1, 1 + n):
                faces.extend((start + i, start + n + i, start + n + (i + 1) % n, start + (i + 1) % n)
                             for i in range(n))
            faces.append(tuple(reversed(range(1 + n * 2, 1 + n * 3))))
            visor = demo.mesh(name, [visor_point(*p) for p in points], faces, material, normals=True)
            subdiv = visor.modifiers.new("Curved optical surface", "SUBSURF")
            subdiv.levels = subdiv.render_levels = 2
            for poly in visor.data.polygons:
                poly.use_smooth = True

        demo.loft("Helmet | regulator jaw", [
            (2.623, [(x + 0.02, y) for x, y in section(0.137, 0.091, -0.12)]),
            (2.657, [(x + 0.02, y) for x, y in section(0.216, 0.133, -0.101)]),
            (2.731, [(x + 0.02, y) for x, y in section(0.218, 0.143, -0.102)]),
            (2.762, [(x + 0.02, y) for x, y in section(0.131, 0.127, -0.11)]),
        ], "teal", 0.021)
        demo.box("Helmet | regulator intake", (0.012, -0.247, 2.692), (0.169, 0.040, 0.067), "black", 0.015)
        for i in range(6):
            demo.box(f"Helmet | regulator slot {i + 1}", (-0.046 + i * 0.023, -0.271, 2.690),
                     (0.007, 0.01, 0.037), "steel", 0.003)
        demo.tube("Helmet | cyan optical signature", [visor_point(*p) for p in [
            (-0.177, -0.270, 2.872), (-0.125, -0.302, 2.853), (-0.037, -0.309, 2.849),
            (0.019, -0.307, 2.836), (0.076, -0.304, 2.850), (0.141, -0.280, 2.861),
            (0.176, -0.263, 2.881),
        ]], 0.009, "aqua", smooth=False)
        demo.tube("Helmet | central painted spine", [
            (0.023, -0.133, 3.058), (0.024, -0.043, 3.107), (0.026, 0.053, 3.118),
            (0.03, 0.163, 3.079), (0.039, 0.231, 2.997),
        ], 0.017, "copper")
        for side in (-1, 1):
            x = 0.027 + side * 0.245
            demo.disk(f"Helmet | comms base {side}", (x, 0.02, 2.835), 0.113, 0.081, "black", bevel=0.013,
                      axis="X")
            demo.disk(f"Helmet | comms ring {side}", (x + side * 0.044, 0.02, 2.835), 0.086, 0.036,
                      "copper", bevel=0.005, axis="X")
            demo.disk(f"Helmet | comms cap {side}", (x + side * 0.073, 0.02, 2.835), 0.063, 0.034,
                      "teal", sides=32, bevel=0.006, axis="X")
            for j in (-1, 0, 1):
                demo.box(f"Helmet | ear vent {side} {j}", (x + side * 0.091, 0.02, 2.832 + j * 0.023),
                         (0.007, 0.053, 0.010), "black", 0.003)
            demo.disk(f"Helmet | forward camera rim {side}", (0.016 + side * 0.181, -0.179, 2.97),
                      0.033, 0.053, "black", bevel=0.008)
            demo.disk(f"Helmet | forward camera lens {side}", (0.016 + side * 0.181, -0.209, 2.97),
                      0.020, 0.011, "aqua" if side == -1 else "glass", bevel=0.004)


def arms(demo, group, add_bone):
    for suffix, shoulder, elbow, wrist, palm in (
        ("L", (0.43, 0.008, 2.423), (0.647, 0.078, 1.950), (0.734, -0.083, 1.577), (0.755, -0.139, 1.420)),
        ("R", (-0.43, 0.030, 2.416), (-0.675, 0.123, 1.976), (-0.735, -0.115, 1.654), (-0.756, -0.204, 1.513)),
    ):
        side = 1 if suffix == "L" else -1
        upper, lower, hand = (f"{part}.{suffix}" for part in ("Upper arm", "Forearm", "Hand"))
        add_bone(upper, shoulder, elbow, "Chest")
        add_bone(lower, elbow, wrist, upper)
        add_bone(hand, wrist, palm, lower)
        with group(upper, f"05 / Upper arm {suffix}"):
            direction = Vector(elbow) - Vector(shoulder)
            oval(demo, f"Shoulder gasket.{suffix}", shoulder, (0.187, 0.167, 0.181), "ribbing", direction)
            limb(demo, f"Pauldrons | ceramic shell.{suffix}", shoulder, elbow, [
                (-0.25, 0.081, 0.095, 0), (-0.12, 0.179, 0.158, -0.012),
                (0.23, 0.185, 0.186, -0.009), (0.51, 0.133, 0.122, 0),
            ], "ceramic", 0.055)
            limb(demo, f"Upper sleeve.{suffix}", shoulder, elbow, [
                (0.39, 0.148, 0.129, 0), (0.67, 0.123, 0.119, 0), (1.026, 0.105, 0.107, 0),
            ], "fabric", 0.032)
            cap = (shoulder[0] + side * 0.126, -0.13, shoulder[2] - 0.065)
            demo.disk(f"Arm ID mount.{suffix}", cap, 0.086, 0.032, "black", sides=12, bevel=0.008)
            demo.disk(f"Arm ID badge.{suffix}", (cap[0], cap[1] - 0.022, cap[2]), 0.063, 0.017,
                      "teal", sides=12, bevel=0.006)
            badge(demo, f"Arm stencil.{suffix}", "07", cap[0], cap[1] - 0.032, cap[2] - 0.024, 0.066)
            for i in range(3):
                x = shoulder[0] + side * 0.085
                demo.box(f"Shoulder lip {suffix} {i}", (x + side * 0.025 * i, -0.13, 2.47),
                         (0.015, 0.028, 0.031), "copper", 0.004, angle=0.45 * side)

        with group(lower, f"06 / Forearm {suffix}"):
            direction = Vector(wrist) - Vector(elbow)
            oval(demo, f"Elbow seal.{suffix}", elbow, (0.117, 0.11, 0.116), "ribbing", direction)
            demo.disk(f"Elbow pivot.{suffix}", (elbow[0] + side * 0.10, elbow[1], elbow[2]),
                      0.083, 0.054, "steel", sides=12, bevel=0.007, axis="X")
            demo.disk(f"Elbow hub.{suffix}", (elbow[0] + side * 0.13, elbow[1], elbow[2]),
                      0.053, 0.018, "teal", bevel=0.005, axis="X")
            limb(demo, f"Forearm plate.{suffix}", elbow, wrist, [
                (0.085, 0.108, 0.123, -0.006), (0.32, 0.137, 0.153, -0.01),
                (0.74, 0.101, 0.117, -0.01), (0.94, 0.088, 0.098, 0),
            ], "teal", 0.032)
            limb(demo, f"Wrist service ring.{suffix}", elbow, wrist, [
                (0.84, 0.095, 0.106, 0), (0.91, 0.095, 0.103, 0),
                (1.025, 0.082, 0.082, 0),
            ], "black", 0.012)
            patch = Vector(elbow).lerp(Vector(wrist), 0.51)
            patch.y -= 0.137
            demo.box(f"Forearm telemetry mount.{suffix}", patch, (0.121, 0.035, 0.134), "black", 0.018)
            for i in range(3):
                demo.box(f"Forearm status {suffix} {i}", (patch.x, patch.y - 0.023, patch.z + (i - 1) * 0.029),
                         (0.071, 0.012, 0.009), "aqua" if i < 2 else "copper", 0.003)

        with group(hand, f"07 / Glove {suffix}"):
            limb(demo, f"Dorsal glove.{suffix}", wrist, palm, [
                (-0.035, 0.070, 0.071, 0), (0.23, 0.087, 0.058, 0),
                (0.74, 0.087, 0.051, 0), (1.11, 0.077, 0.043, 0),
            ], "fabric", 0.019)
            limb(demo, f"Dorsal glove armour.{suffix}", wrist, palm, [
                (0.16, 0.060, 0.015, -0.062), (0.45, 0.079, 0.019, -0.067),
                (0.98, 0.071, 0.017, -0.059),
            ], "ceramic dark", 0.013)
        palm = Vector(palm)
        for i, name in enumerate(FINGERS):
            start = palm + Vector((side * (0.037 - i * 0.040), -0.018 + i * 0.006, -0.012 + 0.007 * i))
            length = (0.129, 0.145, 0.133, 0.113)[i]
            middle = start + Vector((side * (0.021 - 0.009 * i), -0.016, -length * 0.54))
            end = middle + Vector((-side * 0.007, -0.028, -length * 0.46))
            proximal, tip = (f"{name} {joint}.{suffix}" for joint in ("01", "02"))
            add_bone(proximal, start, middle, hand)
            add_bone(tip, middle, end, proximal)
            for bone, a, b, radius, material in (
                (proximal, start, middle, 0.0255, "steel"), (tip, middle, end, 0.0215, "ribbing"),
            ):
                with group(bone):
                    oval(demo, f"{bone} | pressure glove", (a + b) / 2,
                         (radius, radius * 0.94, (a - b).length * 0.5 + 0.013), material, b - a)
        thumb_base = palm + Vector((-side * 0.079, -0.010, 0.070))
        thumb_tip = thumb_base + Vector((-side * 0.047, -0.048, -0.092))
        thumb = f"Thumb.{suffix}"
        add_bone(thumb, thumb_base, thumb_tip, hand)
        with group(thumb):
            oval(demo, f"Opposable thumb.{suffix}", (thumb_base + thumb_tip) / 2,
                 (0.031, 0.028, 0.071), "ribbing", thumb_tip - thumb_base)


def legs(demo, group, add_bone):
    for suffix, hip, knee, ankle, toe in (
        ("L", (0.203, 0.011, 1.663), (0.309, -0.152, 1.055), (0.372, 0.002, 0.43), (0.401, -0.256, 0.34)),
        ("R", (-0.204, 0.012, 1.661), (-0.314, 0.095, 1.050), (-0.416, 0.205, 0.43), (-0.506, -0.062, 0.34)),
    ):
        side = 1 if suffix == "L" else -1
        thigh, calf, foot = (f"{part}.{suffix}" for part in ("Thigh", "Calf", "Foot"))
        add_bone(thigh, hip, knee, "Pelvis")
        add_bone(calf, knee, ankle, thigh)
        add_bone(foot, ankle, toe, calf)
        with group(thigh, f"08 / Thigh {suffix}"):
            limb(demo, f"Thigh | flexible underlayer.{suffix}", hip, knee, [
                (-0.10, 0.155, 0.153, 0), (0.25, 0.169, 0.163, 0),
                (0.60, 0.151, 0.139, 0), (1.00, 0.114, 0.112, 0),
            ], "fabric", 0.045)
            limb(demo, f"Thigh | pressure plate.{suffix}", hip, knee, [
                (0.11, 0.134, 0.056, -0.127), (0.28, 0.148, 0.066, -0.136),
                (0.58, 0.115, 0.068, -0.124), (0.79, 0.080, 0.043, -0.111),
            ], "ceramic dark" if side == 1 else "ceramic", 0.035)
            for i in range(4):
                p = Vector(hip).lerp(Vector(knee), 0.32 + i * 0.075)
                p.x += side * 0.126
                p.y -= 0.079
                demo.box(f"Thigh guide {suffix} {i}", p, (0.061, 0.099, 0.031), "black", 0.009,
                         angle=side * 0.41)
        with group(calf, f"09 / Calf {suffix}"):
            oval(demo, f"Knee {suffix} seal", knee, (0.123, 0.123, 0.128), "ribbing")
            demo.disk(f"Knee {suffix} carrier", (knee[0], knee[1] - 0.08, knee[2]), 0.129, 0.103,
                      "black", sides=12, bevel=0.024)
            demo.disk(f"Knee {suffix} strike plate", (knee[0], knee[1] - 0.140, knee[2] + 0.011), 0.106,
                      0.066, "ceramic" if side == 1 else "teal", sides=8, bevel=0.018)
            demo.disk(f"Knee {suffix} lock", (knee[0], knee[1] - 0.177, knee[2] + 0.018), 0.039, 0.014,
                      "copper", sides=6, bevel=0.005)
            limb(demo, f"Calf | gaiter.{suffix}", knee, ankle, [
                (0.051, 0.121, 0.122, 0), (0.303, 0.154, 0.156, 0.02),
                (0.674, 0.119, 0.127, 0.012), (1.026, 0.091, 0.105, 0.015),
            ], "fabric", 0.033)
            limb(demo, f"Shin shell.{suffix}", knee, ankle, [
                (0.135, 0.097, 0.051, -0.106), (0.26, 0.132, 0.077, -0.126),
                (0.68, 0.110, 0.080, -0.110), (0.91, 0.082, 0.051, -0.084),
            ], "ceramic" if side == 1 else "teal", 0.037)
            strip = Vector(knee).lerp(Vector(ankle), 0.50)
            demo.box(f"Shin serial plate.{suffix}", (strip.x, strip.y - 0.221, strip.z),
                     (0.112, 0.059, 0.092), "black", 0.011)
            badge(demo, f"Shin serial.{suffix}", "07", strip.x, strip.y - 0.253, strip.z - 0.019, 0.054)
        with group(foot, f"10 / Boot {suffix}"):
            boot(demo, suffix, ankle, toe)


def boot(demo, suffix, ankle, toe):
    angle = math.atan2(toe[0] - ankle[0], ankle[1] - toe[1])
    sin, cos = math.sin(angle), math.cos(angle)

    def boot_pos(x, y, z):
        return (ankle[0] + x * cos - y * sin, ankle[1] + x * sin + y * cos, z)

    demo.box(f"Boot | traction sole.{suffix}", boot_pos(0, -0.084, 0.269), (0.346, 0.520, 0.085),
             "black", 0.047, angle)
    demo.box(f"Boot | armored upper.{suffix}", boot_pos(0, -0.107, 0.355), (0.310, 0.473, 0.143),
             "ceramic dark", 0.053, angle)
    demo.box(f"Boot | toe shield.{suffix}", boot_pos(0, -0.253, 0.366), (0.281, 0.189, 0.122),
             "teal", 0.032, angle)
    demo.box(f"Boot | ankle collar.{suffix}", boot_pos(0, -0.01, 0.407), (0.260, 0.277, 0.182),
             "ribbing", 0.052, angle)
    for i in range(5):
        for x in (-0.152, 0.152):
            demo.box(f"Sole lug {suffix} {x} {i}", boot_pos(x, -0.249 + i * 0.081, 0.267),
                     (0.061, 0.052, 0.060), "steel" if i == 0 else "ribbing", 0.01, angle)


def studio(demo):
    demo.collection("11 / Survey station")
    demo.disk("Station | graphite base", (0, -0.08, 0.094), 1.207, 0.164, "black", sides=120,
              bevel=0.044, axis="Z")
    demo.disk("Station | tide plate", (0, -0.08, 0.192), 1.176, 0.071, "floor", sides=120,
              bevel=0.025, axis="Z")
    demo.lathe("Station | concentric copper inlay", (0, -0.08, 0.223),
               ((1.070, 0), (1.091, 0), (1.091, 0.004), (1.070, 0.004)), "copper", axis="Z")
    for i in range(13):
        angle = (i - 6) * 0.102
        demo.box(f"Station | scale tick {i + 1}", (math.sin(angle) * 1.125, -0.08 - math.cos(angle) * 1.125, 0.228),
                 (0.010, 0.038, 0.006), "white" if i % 3 == 0 else "steel", 0.001, angle)
    demo.box("Station | designation plate", (0, -1.236, 0.129), (0.82, 0.145, 0.123), "black", 0.021)
    badge(demo, "Station designation", "N E R E I D   /   0 7", 0, -1.312, 0.112, 0.064, "white")
    for x in (-0.362, 0.362):
        demo.disk(f"Station | plate screw {x}", (x, -1.313, 0.129), 0.014, 0.011, "copper", sides=6)

    sweep = [(-26, 0)]
    for i in range(21):
        angle = i * math.pi / 40
        sweep.append((3.4 + 5 * math.sin(angle), 5 * (1 - math.cos(angle))))
    sweep.append((8.4, 20))
    points = [(x, y, z) for y, z in sweep for x in (-28, 28)]
    faces = [(2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2) for i in range(len(sweep) - 1)]
    demo.mesh("Studio | seamless cyclorama", points, faces, "floor", smooth=True)

    demo.collection("12 / Photography")
    scene = bpy.context.scene
    if scene.world.node_tree is None:
        scene.world.use_nodes = True
    world = scene.world.node_tree.nodes.get("Background")
    world.inputs["Color"].default_value = (0.09, 0.144, 0.19, 1)
    world.inputs["Strength"].default_value = 0.35
    for name, position, target, watts, color, width, height in (
        ("Portrait | soft key", (-3.4, -4.7, 5.1), (0, 0, 1.92), 1050, (0.89, 0.94, 1), 3.5, 4.7),
        ("Portrait | warm edge", (4.9, -1.33, 3.85), (0, 0, 1.75), 880, (1, 0.62, 0.36), 2.0, 3.1),
        ("Portrait | cold edge", (1.8, 3.9, 4.32), (0, 0, 1.90), 1250, (0.23, 0.71, 1), 1.9, 3.5),
        ("Portrait | eye catchlight", (0.05, -4.1, 3.4), (0, 0, 2.34), 80, (0.72, 0.89, 1), 0.8, 0.30),
        ("Portrait | backdrop", (-0.6, 4.1, 4.7), (-0.6, 4.9, 0), 900, (0.16, 0.39, 0.65), 4.1, 2.3),
    ):
        light = bpy.data.lights.new(name, "AREA")
        light.energy, light.color, light.shape, light.size, light.size_y = watts, color, "RECTANGLE", width, height
        obj = bpy.data.objects.new(name, light)
        demo.group.objects.link(obj)
        obj.location = position
        aim(obj, target)

    def camera(name, position, target, lens):
        data = bpy.data.cameras.new(name)
        data.lens = lens
        obj = bpy.data.objects.new(name, data)
        demo.group.objects.link(obj)
        obj.location = position
        aim(obj, target)
        return obj

    hero = camera("Hero | full suit", (2.72, -8.0, 3.30), (0.0, -0.03, 1.56), 65)
    detail = camera("Detail | life support and glazing", (1.95, -4.90, 3.12), (0.08, -0.03, 2.39), 102)
    scene.camera = hero
    scene.render.engine = "CYCLES"
    scene.cycles.use_denoising = True
    scene.cycles.adaptive_threshold = 0.024
    scene.cycles.max_bounces = 6
    scene.cycles.seed = 7
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    return hero, detail


def build_pilot(demo):
    bindings = {}
    bones = []

    def add_bone(name, head, tail, parent=None):
        bones.append({"name": name, "head": head, "tail": tail, "parent": parent})

    @contextmanager
    def group(bone, collection=None):
        if collection:
            demo.collection(collection)
        before = set(demo.group.objects)
        yield
        bindings.setdefault(bone, []).extend(obj for obj in demo.group.objects if obj not in before)

    add_bone("Root", (0, 0, 0.22), (0, 0, 0.62))
    add_bone("Pelvis", (0, 0, 1.59), (0, 0, 1.77), "Root")
    add_bone("Waist", (0, 0, 1.77), (0, 0, 2.045), "Pelvis")
    add_bone("Chest", (0, 0, 2.045), (0, 0, 2.53), "Waist")
    add_bone("Head", (0, 0.013, 2.565), (0.025, 0.013, 3.098), "Chest")
    build_torso(demo, group)
    build_helmet(demo, group)
    arms(demo, group, add_bone)
    legs(demo, group, add_bone)

    demo.collection("00 / Pose rig")
    info = demo.server.create_armature(RIG_NAME, bones)
    demo.pro_calls += 1
    rig = demo.place(bpy.data.objects[info["armature"]])
    rig.show_in_front = True
    bpy.context.view_layer.update()

    expected = {}
    for bone_name, objects in bindings.items():
        pose = rig.pose.bones[bone_name]
        parent_matrix = rig.matrix_world @ pose.matrix @ Matrix.Translation((0, pose.bone.length, 0))
        inverse = parent_matrix.inverted()
        for obj in objects:
            expected[obj] = obj.matrix_world.copy()
            obj.parent = rig
            obj.parent_type = "BONE"
            obj.parent_bone = bone_name
            obj.matrix_parent_inverse = inverse
    bpy.context.view_layer.update()
    for obj, world in expected.items():
        if any(abs(a - b) > 2e-5 for r, s in zip(obj.matrix_world, world, strict=True)
               for a, b in zip(r, s, strict=True)):
            raise RuntimeError(f"Parenting changed the design pose: {obj.name}")
    return rig, len(expected)


def verify_rig(rig):
    forearm = bpy.data.objects["Forearm plate.L"]
    finger = bpy.data.objects["Index 02.L | pressure glove"]
    chest = bpy.data.objects["Pressure cuirass"]

    def vertices_world(obj):
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        return [evaluated.matrix_world @ vertex.co for vertex in evaluated.data.vertices]

    def maximum_movement(obj, original):
        return max((after - before).length for before, after in zip(original, vertices_world(obj), strict=True))

    tracked = (forearm, finger, chest)
    before = [vertices_world(obj) for obj in tracked]
    pose = rig.pose.bones["Forearm.L"]
    pose.rotation_mode = "XYZ"
    pose.rotation_euler.x = math.radians(28)
    bpy.context.view_layer.update()
    movement = [maximum_movement(obj, start) for obj, start in zip(tracked, before, strict=True)]
    pose.rotation_euler.x = 0
    bpy.context.view_layer.update()
    if movement[0] < 0.04 or movement[1] < 0.10 or movement[2] > 1e-6:
        raise RuntimeError(f"Unexpected articulated movement: {movement}")
    if any(maximum_movement(obj, start) > 1e-6 for obj, start in zip(tracked, before, strict=True)):
        raise RuntimeError("Could not restore the saved design pose")
    return {"bone": pose.name, "rotation_degrees": 28, "forearm_displacement": round(movement[0], 6),
            "finger_displacement": round(movement[1], 6), "chest_displacement": round(movement[2], 6)}


def main():
    args = arguments(__doc__)
    if args.width < 128 or args.samples < 1:
        raise ValueError("Width must be at least 128 pixels and samples must be positive.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    demo = Showcase("Nereid")
    demo.server.clear_scene(confirm=True)
    materials(demo)
    rig, attached = build_pilot(demo)
    hero, detail = studio(demo)
    scene = bpy.context.scene
    scene.render.resolution_x = args.width
    scene.render.resolution_y = round(args.width * 1.125)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = "//nereid-07.png"
    scene.cycles.samples = args.samples
    bpy.context.view_layer.update()
    pose_check = verify_rig(rig)
    topology = {}
    for name in SHELLS:
        metrics = GeometryService.topology_metrics(bpy.data.objects[name])
        fields = ("vertex_count", "face_count", "non_manifold_edges", "disconnected_components")
        topology[name] = {key: metrics[key] for key in fields}
        if metrics["non_manifold_edges"] or metrics["disconnected_components"] != 1:
            raise RuntimeError(f"Invalid showcase mesh: {name}: {topology[name]}")

    # Open the saved file with the rig active and the hero camera framed in the viewport.
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"

    blend = output / "nereid-07.blend"
    if "FINISHED" not in bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=True):
        raise RuntimeError(f"Could not save {blend}")
    renders = []
    if not args.check_only:
        cameras = [(hero, "nereid-07.png")]
        if args.detail:
            cameras.append((detail, "nereid-07-detail.png"))
        for camera, filename in cameras:
            path = output / filename
            path.unlink(missing_ok=True)
            scene.camera = camera
            scene.render.filepath = str(path)
            if "FINISHED" not in bpy.ops.render.render(write_still=True) or not path.is_file():
                raise RuntimeError(f"Could not render {path}")
            renders.append({"filename": filename, "pixels": [scene.render.resolution_x, scene.render.resolution_y]})

    report = {
        "model": "NEREID 07",
        "blender": bpy.app.version_string,
        "objects": len(scene.objects),
        "meshes": sum(obj.type == "MESH" for obj in scene.objects),
        "pro_modeling_material_and_rig_calls": demo.pro_calls,
        "bones": len(rig.data.bones),
        "bone_parented_parts": attached,
        "pose_check": pose_check,
        "evaluated_topology": topology,
        "samples": scene.cycles.samples,
        "scene": blend.name,
        "renders": renders,
    }
    (output / "showcase.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("NEREID_SHOWCASE_OK")


if __name__ == "__main__":
    main()
