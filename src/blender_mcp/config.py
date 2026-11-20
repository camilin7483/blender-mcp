"""Environment and transport configuration for the Blender MCP bridge."""

from __future__ import annotations

import os

BLENDER_HOST = os.getenv("BLENDER_HOST", "localhost")
BLENDER_PORT = int(os.getenv("BLENDER_PORT", "9876"))

AUTH_TOKEN_ENV_VAR = "BLENDER_AUTH_TOKEN"
TOKEN_FILE_ENV_VAR = "BLENDER_MCP_TOKEN_FILE"
ALLOW_NO_AUTH_ENV_VAR = "BLENDER_MCP_ALLOW_NO_AUTH"
TOKEN_FILE_NAME = "token"

# A single response larger than this is rejected instead of growing an
# unbounded buffer. Base64 inspection images are the largest normal payload.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

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
