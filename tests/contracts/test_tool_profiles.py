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
    assert len(_tools("full")) == 58


def test_unknown_profile_fails_open() -> None:
    assert len(_tools("does-not-exist")) == 58
