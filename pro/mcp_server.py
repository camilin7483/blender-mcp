#!/usr/bin/env python3
"""
Blender MCP Pro Server v3.0 (FastMCP Bridge with Universal 3D Engine & Full Spatial Toolset)
Connects Claude / Cursor / OpenCode / Windsurf to the Blender MCP Engine on localhost:9876.
"""

import os
import sys
import json
import socket
import base64
import logging
import uuid
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP, Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_mcp_server")

BLENDER_HOST = os.getenv("BLENDER_HOST", "localhost")
BLENDER_PORT = int(os.getenv("BLENDER_PORT", "9876"))
AUTH_TOKEN_ENV_VAR = "BLENDER_AUTH_TOKEN"
TOKEN_FILE_ENV_VAR = "BLENDER_MCP_TOKEN_FILE"
ALLOW_NO_AUTH_ENV_VAR = "BLENDER_MCP_ALLOW_NO_AUTH"
TOKEN_FILE_NAME = "token"


def default_token_path() -> str:
    """Shared token path. Keep in sync with pro/blender_mcp.py."""
    override = os.getenv(TOKEN_FILE_ENV_VAR, "")
    if override:
        return os.path.expanduser(override)
    if os.name == "nt":
        base = os.getenv("APPDATA", os.path.expanduser("~"))
    else:
        base = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "blender-mcp", TOKEN_FILE_NAME)


def _load_auth_token() -> str:
    env_token = os.getenv(AUTH_TOKEN_ENV_VAR, "")
    if env_token:
        return env_token
    try:
        with open(default_token_path(), "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


BLENDER_AUTH_TOKEN = _load_auth_token()


def _current_auth_token() -> str:
    """Re-read the token file if the bridge started before Blender."""
    return BLENDER_AUTH_TOKEN or _load_auth_token()


# A single response larger than this is rejected instead of growing an
# unbounded buffer. Base64 inspection images are the largest normal payload.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

SYSTEM_INSTRUCTIONS = """
You are a Precision 3D Modeler controlling Blender via the Blender MCP Pro Universal Engine.
Because LLMs can make spatial mistakes when guessing raw 3D coordinates, you MUST follow this mandatory 5-step protocol for EVERY 3D modeling task:

================================================================================
UNIVERSAL MODELING TOOL SELECTION TABLE:
================================================================================
1. Furniture, Mechanical Assemblies & Props:
   - Use `create_parametric_part()` + `attach_and_align()` + `spawn_corner_supports()`.
2. Curved Surfaces, Bottles, Pipes, Organic Silhouettes:
   - Symmetrical Lathe (vases, cups, columns, rims): `create_lathe_part()`.
   - Tubular Sweeps (cables, handrails, horns, branches): `create_curve_sweep()`.
   - Complex Lofts (car bodies, hulls, fuselage, ergonomic seats): `create_loft_surface()`.
   - Controlled Bending/Twisting: `deform_object()`.
3. Humanoids, Characters & Creatures:
   - Unified Organic Skinning: `create_skeleton_skin_mesh()` OR `fuse_organic_parts()`.
   - Automated Skeletal Rigging: `auto_rig_humanoid()`.
4. Parametric Architecture & Buildings:
   - Walls from 2D Floorplan: `create_floorplan_walls()`.
   - Doors & Windows Cutouts: `cut_wall_opening()`.
   - Pitched & Flat Roofs: `create_parametric_roof()`.
   - Precise Architectural Stairs: `create_staircase()`.
   - Multi-floor Buildings & Towers: `create_building_shell()`.
   - Facade Modules (balconies, panels): `array_grid_on_surface()`.

================================================================================
MANDATORY 5-STEP PROTOCOL:
================================================================================
1. PLAN & BLUEPRINT FIRST:
   - Call `get_modeling_blueprint(category=...)` to check metric proportions and conventions.
   - Ground is Z=0.0 (lowest point MUST touch 0.0), Front is -Y, Bilateral symmetry across X=0.

2. PARAMETRIC ASSEMBLY (Never Guess Coordinates):
   - Never guess coordinates to connect two parts! Use `snap_to_semantic_anchor` (words like TOP_CENTER, CORNER_FL) or `attach_and_align` or `spawn_corner_supports`.
   - To point/aim anything (camera, light, wheel, cannon), use `orient_and_face_towards` — never hand-compute rotation_deg.
   - Finishing & integration: `place_on_surface_raycast` (seat on any surface), `smart_bevel_and_polish` (bevel + autosmooth), `apply_smart_procedural_material` (5 presets), `generate_game_ready_asset` (decimate + hulls + audit, then `export_scene`), `build_3d_network_datacenter_from_pt` (Packet Tracer JSON to 3D room).
   - If `audit_3d_model` fails, execute its `llm_fix_commands` verbatim before anything else.

3. VERIFY TOPOLOGY & SURFACE CONTACT:
   - Check `audit_3d_model()` or `auto_fix_model()`. The model must pass (`passed: True`, quality >= 80).

4. MANDATORY MULTI-VIEW 4-ANGLE VISUAL CRITIC:
   - You MUST call `render_multiview_inspection()` before concluding. Inspect all 4 quadrants:
     * Top-Left (FRONT -Y): Check symmetry and proportions.
     * Top-Right (RIGHT +X): Check front-to-back depth, tilt, and air-gaps.
     * Bottom-Left (TOP +Z): Check footprint.
     * Bottom-Right (ISOMETRIC 3/4): Check overall 3D silhouette and materials.

5. SELF-CORRECTION LOOP:
   - Use `create_checkpoint(name)` before risky edits and `rollback_checkpoint(name)` if needed.
"""

mcp = FastMCP("BlenderMCP-Pro", instructions=SYSTEM_INSTRUCTIONS)

HEAVY_TIMEOUT_COMMANDS = {
    "execute_code",
    "render_multiview_inspection",
    "render_scene",
    "download_polyhaven_asset",
    "download_sketchfab_model",
    "boolean_operation",
    "auto_fix_model",
    "fuse_organic_parts",
    "create_building_shell",
    "create_skeleton_skin_mesh",
    "generate_game_ready_asset",
    "build_3d_network_datacenter_from_pt",
}


def send_blender_command(
    cmd_type: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Sends a JSON command to the Blender MCP Socket Server on localhost:9876."""
    request_id = uuid.uuid4().hex
    token = _current_auth_token()
    if not token and os.getenv(ALLOW_NO_AUTH_ENV_VAR) != "1":
        raise RuntimeError(
            f"No Blender auth token. Start Blender once to create {default_token_path()}, "
            f"or set {AUTH_TOKEN_ENV_VAR}. Set {ALLOW_NO_AUTH_ENV_VAR}=1 only for trusted local use."
        )
    payload: Dict[str, Any] = {"type": cmd_type, "params": params or {}, "request_id": request_id}
    if token:
        payload["auth_token"] = token

    eff_timeout = timeout or (180.0 if cmd_type in HEAVY_TIMEOUT_COMMANDS else 60.0)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(eff_timeout)
        sock.connect((BLENDER_HOST, BLENDER_PORT))
        sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")

        decoder = json.JSONDecoder()
        buffer = b""
        while True:
            data = sock.recv(65536)
            if not data:
                break
            buffer += data
            if len(buffer) > MAX_RESPONSE_BYTES:
                raise RuntimeError(
                    f"Response from Blender exceeds maximum size ({MAX_RESPONSE_BYTES} bytes)"
                )
            try:
                text = buffer.decode("utf-8").lstrip()
                resp, _ = decoder.raw_decode(text)
                if resp.get("request_id") not in (None, request_id):
                    raise RuntimeError(
                        f"Response request_id mismatch for '{cmd_type}': "
                        f"expected {request_id}, got {resp.get('request_id')}"
                    )
                if resp.get("status") == "error":
                    raise RuntimeError(resp.get("message", "Unknown Blender error"))
                return resp.get("result", resp)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

    raise RuntimeError(f"Disconnected from Blender MCP during '{cmd_type}' without complete response")


# ==============================================================================
# 1. SCENE & BLUEPRINT INSPECTION TOOLS
# ==============================================================================
@mcp.tool()
def get_scene_info(max_objects: int = 100) -> str:
    """Get comprehensive geometric and spatial info about the current Blender scene."""
    return json.dumps(send_blender_command("get_scene_info", {"max_objects": max_objects}), indent=2)


@mcp.tool()
def get_object_info(name: str) -> str:
    """Get detailed world bounding box, metric dimensions, polygon count, and hierarchy for an object."""
    return json.dumps(send_blender_command("get_object_info", {"name": name}), indent=2)


@mcp.tool()
def list_objects(type_filter: Optional[str] = None) -> str:
    """List all objects in the scene, optionally filtered by type ('MESH', 'LIGHT', 'CAMERA')."""
    return json.dumps(send_blender_command("list_objects", {"type_filter": type_filter}), indent=2)


@mcp.tool()
def list_modeling_blueprints() -> str:
    """List available structural 3D blueprints and proportion standards."""
    return json.dumps(send_blender_command("list_modeling_blueprints"), indent=2)


@mcp.tool()
def get_modeling_blueprint(category: str, target_height: Optional[float] = None) -> str:
    """Returns exact real-world dimensions, part breakdown, and workflow recommendations."""
    return json.dumps(send_blender_command("get_modeling_blueprint", {"category": category, "target_height": target_height}), indent=2)


# ==============================================================================
# 2. PARAMETRIC & RELATIONAL MODELING TOOLS
# ==============================================================================
@mcp.tool()
def create_parametric_part(
    name: str,
    shape: str = "ROUNDED_BOX",
    dimensions: List[float] = [0.5, 0.5, 0.5],
    location: List[float] = [0.0, 0.0, 0.0],
    rotation_deg: List[float] = [0.0, 0.0, 0.0],
    origin: str = "BOTTOM",
    bevel_width: float = 0.005,
    bevel_segments: int = 3,
    subsurf_levels: int = 0,
    taper_ratio: float = 0.7,
    thickness: float = 0.05,
    color: Optional[List[float]] = None,
    material_name: Optional[str] = None,
    parent_name: Optional[str] = None,
    segments: int = 32,
) -> str:
    """Create or update a clean manifold parametric mesh part with exact metric dimensions [width_x, depth_y, height_z]."""
    params = {
        "name": name, "shape": shape, "dimensions": dimensions, "location": location,
        "rotation_deg": rotation_deg, "origin": origin, "bevel_width": bevel_width,
        "bevel_segments": bevel_segments, "subsurf_levels": subsurf_levels,
        "taper_ratio": taper_ratio, "thickness": thickness, "color": color,
        "material_name": material_name, "parent_name": parent_name, "segments": segments,
    }
    return json.dumps(send_blender_command("create_parametric_part", params), indent=2)


@mcp.tool()
def attach_and_align(
    part_name: str,
    target_name: str,
    relation: str = "ON_TOP",
    align_x: str = "CENTER",
    align_y: str = "CENTER",
    align_z: str = "CENTER",
    inset_x: float = 0.0,
    inset_y: float = 0.0,
    inset_z: float = 0.0,
    penetration: float = 0.004,
    parent_to_target: bool = True,
) -> str:
    """Snap and align part_name onto target_name using exact evaluated World Bounding Boxes and BVHTree proximity."""
    params = {
        "part_name": part_name, "target_name": target_name, "relation": relation,
        "align_x": align_x, "align_y": align_y, "align_z": align_z,
        "inset_x": inset_x, "inset_y": inset_y, "inset_z": inset_z,
        "penetration": penetration, "parent_to_target": parent_to_target,
    }
    return json.dumps(send_blender_command("attach_and_align", params), indent=2)


@mcp.tool()
def snap_to_semantic_anchor(
    part_name: str,
    target_name: str,
    anchor: str = "TOP_CENTER",
    offset: Optional[List[float]] = None,
    match_dimensions_axes: Optional[List[str]] = None,
    penetration: float = 0.004,
    parent_to_target: bool = True,
) -> str:
    """Place part_name on target_name with words, not coordinates: TOP/BOTTOM/FRONT/BACK/LEFT/RIGHT centers, TOP_FRONT_EDGE, TOP_BACK_EDGE, CORNER_FL/FR/BL/BR, INSIDE_CENTER."""
    return json.dumps(send_blender_command("snap_to_semantic_anchor", {
        "part_name": part_name, "target_name": target_name, "anchor": anchor,
        "offset": offset, "match_dimensions_axes": match_dimensions_axes,
        "penetration": penetration, "parent_to_target": parent_to_target,
    }), indent=2)


@mcp.tool()
def list_semantic_anchors(object_name: str) -> str:
    """List anchors with world position, normal, tangent, local frame, source and confidence: CENTER, TOP/BOTTOM/LEFT/RIGHT/FRONT/BACK_CENTER, FACE_*, SURFACE_*, EDGE_*, CORNER_*, SOCKET_*, BONE_*, CUSTOM_*."""
    return json.dumps(send_blender_command("list_semantic_anchors", {
        "object_name": object_name,
    }), indent=2)


@mcp.tool()
def anchor_operation(
    operation: str,
    part_name: Optional[str] = None,
    target_name: Optional[str] = None,
    part_anchor: str = "CENTER",
    target_anchor: str = "TOP_CENTER",
    offset: Optional[List[float]] = None,
    gap: float = 0.0,
    normal: Optional[List[float]] = None,
    object_names: Optional[List[str]] = None,
    axis: str = "X",
    plane: float = 0.0,
    spacing: Optional[float] = None,
    duplicate: bool = True,
    parent_to_target: bool = False,
) -> str:
    """Operate on anchors. align/mate need part_name, target_name and anchors; offset/orient_normal need part_name; distribute/mirror need object_names. mate orients the part normal against the target normal and adds gap along the target normal. mirror duplicates by default."""
    return json.dumps(send_blender_command("anchor_operation", {
        "operation": operation, "part_name": part_name, "target_name": target_name,
        "part_anchor": part_anchor, "target_anchor": target_anchor,
        "offset": offset, "gap": gap, "normal": normal,
        "object_names": object_names, "axis": axis, "plane": plane,
        "spacing": spacing, "duplicate": duplicate,
        "parent_to_target": parent_to_target,
    }), indent=2)


@mcp.tool()
def orient_and_face_towards(
    object_name: str,
    look_at_target: Any,
    up_axis: str = "Z",
    front_axis: str = "-Y",
) -> str:
    """Aim object_name at another object name or [x, y, z] with quaternions (cameras, lights, wheels, spotlights)."""
    return json.dumps(send_blender_command("orient_and_face_towards", {
        "object_name": object_name, "look_at_target": look_at_target,
        "up_axis": up_axis, "front_axis": front_axis,
    }), indent=2)


@mcp.tool()
def place_on_surface_raycast(
    object_name: str,
    target_surface: str,
    uv_ratio: Optional[List[float]] = None,
    align_to_normal: bool = True,
    embed_depth: float = 0.003,
) -> str:
    """Seat object_name on target_surface via AABB-seeded BVHTree raycast at (u,v), aligning local Z to the hit normal."""
    return json.dumps(send_blender_command("place_on_surface_raycast", {
        "object_name": object_name, "target_surface": target_surface, "uv_ratio": uv_ratio,
        "align_to_normal": align_to_normal, "embed_depth": embed_depth,
    }), indent=2)


@mcp.tool()
def smart_bevel_and_polish(
    object_names: Optional[List[str]] = None,
    profile: str = "HARD_SURFACE",
) -> str:
    """Repair, bevel (harden normals + clamp overlap) and autosmooth meshes: 'HARD_SURFACE', 'ORGANIC', 'ARCHITECTURAL'."""
    return json.dumps(send_blender_command("smart_bevel_and_polish", {
        "object_names": object_names, "profile": profile,
    }), indent=2)


@mcp.tool()
def apply_smart_procedural_material(
    object_name: str,
    preset: str,
    primary_color: Optional[List[float]] = None,
    wear_amount: float = 0.2,
    scale: float = 5.0,
) -> str:
    """Build and assign a procedural edge-wear material: 'BRUSHED_METAL', 'CAR_PAINT_METALLIC', 'WEATHERED_WOOD', 'MATTE_PLASTIC_EDGE_WEAR', 'ARCHITECTURAL_GLASS'."""
    return json.dumps(send_blender_command("apply_smart_procedural_material", {
        "object_name": object_name, "preset": preset, "primary_color": primary_color,
        "wear_amount": wear_amount, "scale": scale,
    }), indent=2)


@mcp.tool()
def generate_game_ready_asset(
    object_names: Optional[List[str]] = None,
    target_engine: str = "GODOT",
    generate_collision_hull: bool = True,
    max_tris: int = 10000,
) -> str:
    """Normalize, ground, decimate over budget, add convex _colonly hulls and re-audit. Returns export-ready report (no file written)."""
    return json.dumps(send_blender_command("generate_game_ready_asset", {
        "object_names": object_names, "target_engine": target_engine,
        "generate_collision_hull": generate_collision_hull, "max_tris": max_tris,
    }), indent=2)


@mcp.tool()
def build_3d_network_datacenter_from_pt(pt_topology_json: str) -> str:
    """Build a cutaway datacenter room (racks, desks+PCs, colored cables) from a Packet Tracer TopologyPlan JSON string."""
    return json.dumps(send_blender_command("build_3d_network_datacenter_from_pt", {
        "pt_topology_json": pt_topology_json,
    }), indent=2)


@mcp.tool()
def spawn_corner_supports(
    target_name: str,
    prefix: str = "Leg",
    shape: str = "TAPERED_CYLINDER",
    thickness: float = 0.04,
    height: Optional[float] = None,
    inset_x: float = 0.04,
    inset_y: float = 0.04,
    taper_ratio: float = 0.7,
    flare_angle_deg: float = 0.0,
    reach_ground: bool = True,
    color: Optional[List[float]] = None,
    material_name: Optional[str] = None,
) -> str:
    """Create 4 symmetrical corner supports (FL, FR, BL, BR) under target_name reaching Z=0.0."""
    params = {
        "target_name": target_name, "prefix": prefix, "shape": shape, "thickness": thickness,
        "height": height, "inset_x": inset_x, "inset_y": inset_y, "taper_ratio": taper_ratio,
        "flare_angle_deg": flare_angle_deg, "reach_ground": reach_ground,
        "color": color, "material_name": material_name,
    }
    return json.dumps(send_blender_command("spawn_corner_supports", params), indent=2)


@mcp.tool()
def symmetry_mirror(
    object_name: str,
    target_reference: Optional[str] = None,
    axis: str = "X",
    mode: str = "DUPLICATE",
    new_name: Optional[str] = None,
) -> str:
    """Mirror an object across axis ('X', 'Y', 'Z') around target_reference or world origin."""
    return json.dumps(send_blender_command("symmetry_mirror", {
        "object_name": object_name, "target_reference": target_reference,
        "axis": axis, "mode": mode, "new_name": new_name,
    }), indent=2)


@mcp.tool()
def radial_array(
    object_name: str,
    count: int = 4,
    center: Optional[List[float]] = None,
    axis: str = "Z",
) -> str:
    """Create count radially symmetric instances of object_name around center and axis."""
    return json.dumps(send_blender_command("radial_array", {
        "object_name": object_name, "count": count, "center": center, "axis": axis,
    }), indent=2)


@mcp.tool()
def boolean_operation(
    target_name: str,
    cutter_name: str,
    operation: str = "DIFFERENCE",
    apply_modifier: bool = True,
    delete_cutter: bool = True,
) -> str:
    """Perform exact Boolean operation ('DIFFERENCE', 'UNION', 'INTERSECT') and repair normals."""
    return json.dumps(send_blender_command("boolean_operation", {
        "target_name": target_name, "cutter_name": cutter_name,
        "operation": operation, "apply_modifier": apply_modifier, "delete_cutter": delete_cutter,
    }), indent=2)


@mcp.tool()
def create_articulation_joint(
    parent_name: str,
    child_name: str,
    joint_location: Optional[List[float]] = None,
    rotation_limits_deg: Optional[Dict[str, List[float]]] = None,
) -> str:
    """Create a functional pivot/hinge joint between parent and child with angle limits."""
    return json.dumps(send_blender_command("create_articulation_joint", {
        "parent_name": parent_name, "child_name": child_name,
        "joint_location": joint_location, "rotation_limits_deg": rotation_limits_deg,
    }), indent=2)


# ==============================================================================
# 3. CURVATURE, LATHE, SWEEP, LOFT & DEFORMERS
# ==========================================================================
@mcp.tool()
def create_lathe_part(
    name: str,
    profile_points_2d: List[List[float]],
    location: List[float] = [0.0, 0.0, 0.0],
    segments: int = 32,
    angle_deg: float = 360.0,
    bevel_width: float = 0.002,
    color: Optional[List[float]] = None,
    material_name: Optional[str] = None,
    parent_name: Optional[str] = None,
) -> str:
    """Spin a 2D profile [[radius_x, height_z], ...] around local Z axis (vases, cups, columns, wheels, rims)."""
    return json.dumps(send_blender_command("create_lathe_part", {
        "name": name, "profile_points_2d": profile_points_2d, "location": location,
        "segments": segments, "angle_deg": angle_deg, "bevel_width": bevel_width,
        "color": color, "material_name": material_name, "parent_name": parent_name,
    }), indent=2)


@mcp.tool()
def create_curve_sweep(
    name: str,
    path_points_3d: List[List[float]],
    radius: float = 0.03,
    taper_end_ratio: float = 1.0,
    resolution_u: int = 12,
    bevel_resolution: int = 8,
    closed: bool = False,
    color: Optional[List[float]] = None,
    material_name: Optional[str] = None,
    parent_name: Optional[str] = None,
) -> str:
    """Create a tubular 3D curve sweep with tapering and auto-UVs (pipes, cables, handrails, horns, branches)."""
    return json.dumps(send_blender_command("create_curve_sweep", {
        "name": name, "path_points_3d": path_points_3d, "radius": radius,
        "taper_end_ratio": taper_end_ratio, "resolution_u": resolution_u,
        "bevel_resolution": bevel_resolution, "closed": closed, "color": color,
        "material_name": material_name, "parent_name": parent_name,
    }), indent=2)


@mcp.tool()
def create_loft_surface(
    name: str,
    cross_sections: List[List[List[float]]],
    closed_caps: bool = True,
    subsurf_levels: int = 1,
    smooth_shading: bool = True,
    color: Optional[List[float]] = None,
    material_name: Optional[str] = None,
    parent_name: Optional[str] = None,
) -> str:
    """Bridge multiple 3D cross-sections into smooth manifold loft surfaces (car bodies, boat hulls, cushions)."""
    return json.dumps(send_blender_command("create_loft_surface", {
        "name": name, "cross_sections": cross_sections, "closed_caps": closed_caps,
        "subsurf_levels": subsurf_levels, "smooth_shading": smooth_shading,
        "color": color, "material_name": material_name, "parent_name": parent_name,
    }), indent=2)


@mcp.tool()
def deform_object(
    name: str,
    deform_type: str = "BEND",
    axis: str = "Z",
    angle_deg: float = 30.0,
    factor: float = 0.5,
    apply_modifier: bool = True,
) -> str:
    """Apply controlled deformation (BEND, TAPER, TWIST, STRETCH) using a centered deformation gizmo."""
    return json.dumps(send_blender_command("deform_object", {
        "name": name, "deform_type": deform_type, "axis": axis,
        "angle_deg": angle_deg, "factor": factor, "apply_modifier": apply_modifier,
    }), indent=2)


# ==============================================================================
# 4. ORGANIC MODELING, SKINNING & RIGGING
# ==============================================================================
@mcp.tool()
def fuse_organic_parts(
    object_names: List[str],
    merged_name: str = "Organic_Body",
    voxel_size: float = 0.015,
    smooth_iterations: int = 5,
    smooth_factor: float = 0.5,
    keep_originals: bool = False,
) -> str:
    """Seamlessly fuse multiple body parts or primitives into a continuous organic skin via Voxel Remeshing."""
    return json.dumps(send_blender_command("fuse_organic_parts", {
        "object_names": object_names, "merged_name": merged_name, "voxel_size": voxel_size,
        "smooth_iterations": smooth_iterations, "smooth_factor": smooth_factor, "keep_originals": keep_originals,
    }), indent=2)


@mcp.tool()
def create_skeleton_skin_mesh(
    name: str,
    nodes_dict: Dict[str, List[float]],
    edges_list: List[List[str]],
    radii_dict: Dict[str, Any],
    subsurf_levels: int = 2,
    voxel_remesh_size: float = 0.0,
    color: Optional[List[float]] = None,
) -> str:
    """Construct organic bodies or branching creatures from a node graph with per-vertex skin radii in 1 call."""
    return json.dumps(send_blender_command("create_skeleton_skin_mesh", {
        "name": name, "nodes_dict": nodes_dict, "edges_list": edges_list,
        "radii_dict": radii_dict, "subsurf_levels": subsurf_levels,
        "voxel_remesh_size": voxel_remesh_size, "color": color,
    }), indent=2)


@mcp.tool()
def auto_rig_humanoid(
    mesh_name: str,
    armature_name: str = "Humanoid_Rig",
    bind_automatic_weights: bool = True,
) -> str:
    """Generate a proportional humanoid deformation armature with connected bones and auto-weight skinning."""
    return json.dumps(send_blender_command("auto_rig_humanoid", {
        "mesh_name": mesh_name, "armature_name": armature_name,
        "bind_automatic_weights": bind_automatic_weights,
    }), indent=2)


# ==============================================================================
# 5. PARAMETRIC ARCHITECTURE & BUILDINGS
# ==============================================================================
@mcp.tool()
def create_floorplan_walls(
    name: str = "House_Walls",
    wall_segments: Optional[List[List[float]]] = None,
    height: float = 2.7,
    thickness: float = 0.15,
    color: Optional[List[float]] = None,
    material_name: Optional[str] = None,
) -> str:
    """Build clean extruded walls from 2D segments [[x1, y1, x2, y2], ...] grounded at Z=0.0."""
    return json.dumps(send_blender_command("create_floorplan_walls", {
        "name": name, "wall_segments": wall_segments, "height": height,
        "thickness": thickness, "color": color, "material_name": material_name,
    }), indent=2)


@mcp.tool()
def cut_wall_opening(
    wall_name: str,
    offset_along_wall: float = 1.0,
    sill_height: float = 0.0,
    width: float = 0.9,
    height: float = 2.1,
    opening_type: str = "DOOR",
    add_frame: bool = True,
    add_glass_or_panel: bool = True,
    frame_color: Optional[List[float]] = None,
) -> str:
    """Cut an exact boolean opening into a wall and automatically spawn fitted frames and glass panes/panels."""
    return json.dumps(send_blender_command("cut_wall_opening", {
        "wall_name": wall_name, "offset_along_wall": offset_along_wall, "sill_height": sill_height,
        "width": width, "height": height, "opening_type": opening_type, "add_frame": add_frame,
        "add_glass_or_panel": add_glass_or_panel, "frame_color": frame_color,
    }), indent=2)


@mcp.tool()
def create_parametric_roof(
    target_name: str,
    name: str = "Roof",
    style: str = "GABLE",
    pitch_deg: float = 30.0,
    overhang: float = 0.25,
    thickness: float = 0.12,
    color: Optional[List[float]] = None,
) -> str:
    """Generate a parametric roof ('GABLE', 'HIP', 'SHED', 'FLAT') perfectly welded to target walls with overhang."""
    return json.dumps(send_blender_command("create_parametric_roof", {
        "target_name": target_name, "name": name, "style": style, "pitch_deg": pitch_deg,
        "overhang": overhang, "thickness": thickness, "color": color,
    }), indent=2)


@mcp.tool()
def create_staircase(
    name: str = "Staircase",
    start_location: List[float] = [0.0, 0.0, 0.0],
    width: float = 1.0,
    total_height: float = 2.7,
    total_run: float = 3.0,
    step_count: int = 15,
    style: str = "CLOSED",
    direction_deg: float = 0.0,
    handrails: bool = True,
    color: Optional[List[float]] = None,
) -> str:
    """Generate precise architectural stairs ('CLOSED' or 'OPEN') with optional bilateral handrails."""
    return json.dumps(send_blender_command("create_staircase", {
        "name": name, "start_location": start_location, "width": width,
        "total_height": total_height, "total_run": total_run, "step_count": step_count,
        "style": style, "direction_deg": direction_deg, "handrails": handrails, "color": color,
    }), indent=2)


@mcp.tool()
def create_building_shell(
    name: str = "Building",
    width: float = 12.0,
    depth: float = 12.0,
    floors: int = 6,
    floor_height: float = 3.2,
    window_cols_x: int = 4,
    window_cols_y: int = 4,
    window_width: float = 1.5,
    window_height: float = 1.8,
    facade_color: Optional[List[float]] = None,
    glass_color: Optional[List[float]] = None,
) -> str:
    """Build a complete multi-floor building with structural slabs, glass facades, and rooftop parapet."""
    return json.dumps(send_blender_command("create_building_shell", {
        "name": name, "width": width, "depth": depth, "floors": floors,
        "floor_height": floor_height, "window_cols_x": window_cols_x, "window_cols_y": window_cols_y,
        "window_width": window_width, "window_height": window_height,
        "facade_color": facade_color, "glass_color": glass_color,
    }), indent=2)


@mcp.tool()
def array_grid_on_surface(
    module_name: str,
    target_name: str,
    face: str = "FRONT",
    rows: int = 3,
    cols: int = 4,
    margin_u: float = 0.4,
    margin_v: float = 0.4,
    penetration: float = 0.005,
    instance_data: bool = True,
) -> str:
    """Array-distribute a module object onto a selected face ('FRONT', 'BACK', 'LEFT', 'RIGHT', 'TOP') of target."""
    return json.dumps(send_blender_command("array_grid_on_surface", {
        "module_name": module_name, "target_name": target_name, "face": face,
        "rows": rows, "cols": cols, "margin_u": margin_u, "margin_v": margin_v,
        "penetration": penetration, "instance_data": instance_data,
    }), indent=2)


# ==============================================================================
# 6. AUDIT, REPAIR & SELF-CORRECTION
# ==============================================================================
@mcp.tool()
def audit_3d_model(
    object_names: Optional[List[str]] = None,
    blueprint_name: Optional[str] = None,
    contact_tolerance: float = 0.018,
    suspended: Optional[List[str]] = None,
    ground_tolerance: float = 0.005,
    scale_tolerance: float = 0.001,
    symmetry_axis: Optional[str] = None,
    symmetry_plane: float = 0.0,
    symmetry_tolerance: float = 0.001,
    topology_policy: str = "report",
    check_self_intersections: bool = False,
) -> str:
    """Audit evaluated geometry: dimensions, ground contact, normalized scale, BVH surface intersections, contact graph, topology, symmetry and optional blueprint dimensions. Returns passed, requirements, failures and the legacy critical_issues/warnings views. passed is computed after every requirement. topology_policy is 'report' or 'strict'. Names in suspended are excluded from ground/floating checks."""
    return json.dumps(send_blender_command("audit_3d_model", {
        "object_names": object_names, "blueprint_name": blueprint_name,
        "contact_tolerance": contact_tolerance, "suspended": suspended,
        "ground_tolerance": ground_tolerance, "scale_tolerance": scale_tolerance,
        "symmetry_axis": symmetry_axis, "symmetry_plane": symmetry_plane,
        "symmetry_tolerance": symmetry_tolerance, "topology_policy": topology_policy,
        "check_self_intersections": check_self_intersections,
    }), indent=2)


@mcp.tool()
def repair_mesh_geometry(
    object_names: Optional[List[str]] = None,
    merge_distance: float = 0.0005,
    recalc_normals: bool = True,
    apply_scale: bool = True,
    shade_smooth: bool = True,
) -> str:
    """Clean mesh topology, remove duplicate vertices, recalculate outward normals, and apply scales safely."""
    return json.dumps(send_blender_command("repair_mesh_geometry", {
        "object_names": object_names, "merge_distance": merge_distance,
        "recalc_normals": recalc_normals, "apply_scale": apply_scale, "shade_smooth": shade_smooth,
    }), indent=2)


@mcp.tool()
def ground_model(object_names: Optional[List[str]] = None, center_xy: bool = True) -> str:
    """Translate target objects rigidly so the lowest point touches Z=0.0."""
    return json.dumps(send_blender_command("ground_model", {"object_names": object_names, "center_xy": center_xy}), indent=2)


@mcp.tool()
def auto_fix_model(
    object_names: Optional[List[str]] = None,
    snap_floating_threshold: float = 0.35,
    center_xy: bool = True,
    snap_floating: bool = True,
    suspended: Optional[List[str]] = None,
) -> str:
    """Automatically fix topology, snap floating parts into BVHTree contact, and ground the model at Z=0.0. Names in suspended are never snap-moved."""
    return json.dumps(send_blender_command("auto_fix_model", {
        "object_names": object_names, "snap_floating_threshold": snap_floating_threshold,
        "center_xy": center_xy, "snap_floating": snap_floating, "suspended": suspended,
    }), indent=2)


# ==============================================================================
# 7. MULTI-VIEW QUAD VISUAL CRITIC & STUDIO LIGHTING
# ==============================================================================
@mcp.tool()
def render_multiview_inspection(
    object_names: Optional[List[str]] = None,
    resolution: int = 512,
    show_wireframe: bool = False,
    blueprint_name: Optional[str] = None,
    suspended: Optional[List[str]] = None,
    mode: str = "quad",
    include_overlays: bool = False,
) -> list:
    """Deterministic inspection render: quad (FRONT/RIGHT/TOP ortho + ISO perspective) or a single mode (front, side, top, iso, silhouette, wireframe, normals, uv_checker). Returns the image plus camera, resolution, background, render_id and audit metadata. include_overlays draws the assembly bounding box and reports dimensions in metadata."""
    res = send_blender_command("render_multiview_inspection", {
        "object_names": object_names, "resolution": resolution,
        "show_wireframe": show_wireframe, "blueprint_name": blueprint_name,
        "return_base64": True, "suspended": suspended,
        "mode": mode, "include_overlays": include_overlays,
    })
    img_b64 = res.pop("image_data", None)
    text_summary = json.dumps(res, indent=2)
    if img_b64:
        return [Image(data=base64.b64decode(img_b64), format="png"), text_summary]
    return [text_summary]


@mcp.tool()
def setup_studio_lighting(intensity_multiplier: float = 1.0, confirm: bool = False) -> str:
    """Create a balanced 3-point studio lighting rig (Key, Fill, Rim). Replaces existing lights; returns a dry-run unless confirm=true."""
    return json.dumps(send_blender_command("setup_studio_lighting", {
        "intensity_multiplier": intensity_multiplier, "confirm": confirm,
    }), indent=2)


# ==============================================================================
# 8. TRANSFORMS, MATERIALS & CHECKPOINTS
# ==============================================================================
@mcp.tool()
def transform_object(
    name: str,
    location: Optional[List[float]] = None,
    rotation_deg: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    dimensions: Optional[List[float]] = None,
    apply_scale: bool = True,
) -> str:
    """Transform location, rotation (deg), scale, or metric dimensions."""
    return json.dumps(send_blender_command("transform_object", {
        "name": name, "location": location, "rotation_deg": rotation_deg,
        "scale": scale, "dimensions": dimensions, "apply_scale": apply_scale,
    }), indent=2)


@mcp.tool()
def delete_object(name: str, confirm: bool = False) -> str:
    """Delete an object by name. Returns a dry-run unless confirm=true."""
    return json.dumps(send_blender_command("delete_object", {"name": name, "confirm": confirm}), indent=2)


@mcp.tool()
def duplicate_object(name: str, new_name: Optional[str] = None, location: Optional[List[float]] = None) -> str:
    """Duplicate an object with its mesh data."""
    return json.dumps(send_blender_command("duplicate_object", {"name": name, "new_name": new_name, "location": location}), indent=2)


@mcp.tool()
def create_material(
    name: str,
    color: Optional[List[float]] = None,
    metallic: float = 0.0,
    roughness: float = 0.45,
    emission: Optional[List[float]] = None,
    alpha: float = 1.0,
) -> str:
    """Create or update a PBR Principled BSDF material."""
    return json.dumps(send_blender_command("create_material", {
        "name": name, "color": color, "metallic": metallic,
        "roughness": roughness, "emission": emission, "alpha": alpha,
    }), indent=2)


@mcp.tool()
def assign_material(object_name: str, material_name: str) -> str:
    """Assign an existing material to an object."""
    return json.dumps(send_blender_command("assign_material", {"object_name": object_name, "material_name": material_name}), indent=2)


@mcp.tool()
def clear_scene(keep_cameras_and_lights: bool = False, confirm: bool = False) -> str:
    """Remove objects from scene (optionally keeping cameras and lights). Returns a dry-run unless confirm=true."""
    return json.dumps(send_blender_command("clear_scene", {
        "keep_cameras_and_lights": keep_cameras_and_lights, "confirm": confirm,
    }), indent=2)


@mcp.tool()
def export_scene(filepath: str, format: str = "GLB") -> str:
    """Export scene to 'GLB', 'GLTF', 'FBX', or 'OBJ'. Paths are confined to BLENDER_MCP_OUTPUT_DIR unless BLENDER_MCP_ALLOW_ANY_PATH=1."""
    return json.dumps(send_blender_command("export_scene", {"filepath": filepath, "format": format}), indent=2)


@mcp.tool()
def execute_code(code: str, auto_audit: bool = True, blueprint_name: Optional[str] = None) -> str:
    """Execute raw Python code in Blender and automatically audit created geometry."""
    return json.dumps(send_blender_command("execute_code", {
        "code": code, "auto_audit": auto_audit, "blueprint_name": blueprint_name,
    }), indent=2)


@mcp.tool()
def create_checkpoint(name: str = "step") -> str:
    """Save a scene snapshot before risky edits (keeps last 10 snapshots)."""
    return json.dumps(send_blender_command("create_checkpoint", {"name": name}), indent=2)


@mcp.tool()
def rollback_checkpoint(name: str = "step", confirm: bool = False) -> str:
    """Roll back the scene to a previously saved checkpoint. Returns a dry-run unless confirm=true."""
    return json.dumps(send_blender_command("rollback_checkpoint", {"name": name, "confirm": confirm}), indent=2)


@mcp.tool()
def list_checkpoints() -> str:
    """List all available scene checkpoints."""
    return json.dumps(send_blender_command("list_checkpoints"), indent=2)


# ==============================================================================
# 9. EXTERNAL ASSETS (POLY HAVEN & SKETCHFAB)
# ==============================================================================
@mcp.tool()
def search_polyhaven_assets(asset_type: str = "all", categories: Optional[str] = None) -> str:
    """Search Poly Haven assets ('hdris', 'textures', 'models', 'all')."""
    return json.dumps(send_blender_command("search_polyhaven_assets", {"asset_type": asset_type, "categories": categories}), indent=2)


@mcp.tool()
def download_polyhaven_asset(asset_id: str, asset_type: str, resolution: str = "1k", file_format: Optional[str] = None) -> str:
    """Download and set up a Poly Haven HDRI, PBR texture material, or model."""
    return json.dumps(send_blender_command("download_polyhaven_asset", {
        "asset_id": asset_id, "asset_type": asset_type, "resolution": resolution, "file_format": file_format,
    }), indent=2)


@mcp.tool()
def search_sketchfab_models(query: str, categories: Optional[str] = None, count: int = 20, downloadable: bool = True) -> str:
    """Search downloadable 3D models on Sketchfab."""
    return json.dumps(send_blender_command("search_sketchfab_models", {
        "query": query, "categories": categories, "count": count, "downloadable": downloadable,
    }), indent=2)


@mcp.tool()
def download_sketchfab_model(uid: str, normalize_size: bool = True, target_size: float = 1.0) -> str:
    """Download and import a Sketchfab model by UID."""
    return json.dumps(send_blender_command("download_sketchfab_model", {
        "uid": uid, "normalize_size": normalize_size, "target_size": target_size,
    }), indent=2)


CORE_TOOLS = {
    "get_scene_info",
    "get_object_info",
    "list_objects",
    "transform_object",
    "delete_object",
    "duplicate_object",
    "clear_scene",
    "create_checkpoint",
    "rollback_checkpoint",
    "list_checkpoints",
    "audit_3d_model",
    "repair_mesh_geometry",
    "ground_model",
}

PROFILE_EXTRAS = {
    "modeling": {
        "list_modeling_blueprints", "get_modeling_blueprint",
        "create_parametric_part", "attach_and_align", "snap_to_semantic_anchor",
        "list_semantic_anchors", "anchor_operation", "orient_and_face_towards",
        "place_on_surface_raycast", "smart_bevel_and_polish",
        "spawn_corner_supports", "symmetry_mirror", "radial_array",
        "boolean_operation", "create_articulation_joint", "create_lathe_part",
        "create_curve_sweep", "create_loft_surface", "deform_object",
        "create_floorplan_walls", "cut_wall_opening", "create_parametric_roof",
        "create_staircase", "create_building_shell", "array_grid_on_surface",
        "auto_fix_model", "build_3d_network_datacenter_from_pt",
    },
    "materials": {
        "create_material", "assign_material",
        "apply_smart_procedural_material", "setup_studio_lighting",
    },
    "animation": {
        "create_articulation_joint", "auto_rig_humanoid",
        "orient_and_face_towards",
    },
    "rigging": {
        "fuse_organic_parts", "create_skeleton_skin_mesh",
        "auto_rig_humanoid", "create_articulation_joint",
    },
    "geometry_nodes": {
        "deform_object", "create_loft_surface", "array_grid_on_surface",
        "smart_bevel_and_polish", "apply_smart_procedural_material",
    },
    "inspection": {
        "list_modeling_blueprints", "get_modeling_blueprint",
        "audit_3d_model", "render_multiview_inspection",
        "list_semantic_anchors", "repair_mesh_geometry", "ground_model",
    },
    "export": {
        "export_scene", "generate_game_ready_asset",
        "repair_mesh_geometry", "auto_fix_model",
    },
    "assets": {
        "search_polyhaven_assets", "download_polyhaven_asset",
        "search_sketchfab_models", "download_sketchfab_model",
    },
}

TOOL_PROFILES = {
    name: CORE_TOOLS | extras
    for name, extras in PROFILE_EXTRAS.items()
}
TOOL_PROFILES["core"] = set(CORE_TOOLS)
TOOL_PROFILES["full"] = None


def _apply_tool_profile() -> str:
    requested = os.environ.get("BLENDER_MCP_PROFILE", "full").strip().lower() or "full"
    if requested == "full":
        return requested
    if requested not in TOOL_PROFILES:
        print(
            f"[blender-mcp] Unknown BLENDER_MCP_PROFILE '{requested}'; using 'full'.",
            file=sys.stderr,
        )
        return "full"
    allowed = TOOL_PROFILES[requested]
    manager = getattr(mcp, "_tool_manager", None)
    if manager is None:
        return requested
    for name in list(getattr(manager, "_tools", {})):
        if name not in allowed:
            manager.remove_tool(name)
    return requested


ACTIVE_TOOL_PROFILE = _apply_tool_profile()


if __name__ == "__main__":
    mcp.run()
