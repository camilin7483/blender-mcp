"""Tool profile filtering in the FastMCP bridge.

Each profile is checked in a fresh interpreter because the bridge applies the
filter at import time.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "pro"


def _tools(profile: str) -> list[str]:
    env = os.environ.copy()
    env["BLENDER_MCP_PROFILE"] = profile
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BRIDGE_DIR), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    code = (
        "import mcp_server; "
        "print(','.join(mcp_server.mcp._tool_manager._tools))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
    )
    return output.strip().split(",") if output.strip() else []


def test_core_profile_is_smaller_and_includes_audit() -> None:
    tools = _tools("core")
    assert "audit_3d_model" in tools
    assert "export_scene" not in tools
    assert len(tools) < 55


def test_full_profile_has_every_tool() -> None:
    assert len(_tools("full")) == 107


def test_unknown_profile_uses_core() -> None:
    assert _tools("does-not-exist") == _tools("core")


def test_every_tool_belongs_to_a_profile() -> None:
    import blender_mcp.server as server

    all_tools = set(server.mcp._tool_manager._tools)
    covered = set(server.CORE_TOOLS)
    for extras in server.PROFILE_EXTRAS.values():
        covered |= extras
    assert all_tools - covered == {"execute_code"}
    for name, allowed in server.TOOL_PROFILES.items():
        if allowed is None:
            continue
        assert allowed <= all_tools, f"profile '{name}' references unknown tools"


def test_legacy_wrapper_exposes_mcp() -> None:
    import mcp_server

    assert hasattr(mcp_server, "mcp")
    assert mcp_server.mcp is not None


def test_nano_profile_stays_small() -> None:
    assert len(_tools("nano")) == 13


def test_guided_profile_is_bounded() -> None:
    assert len(_tools("guided")) == 26
