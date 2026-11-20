#!/usr/bin/env python3
"""Legacy entry point for the Blender MCP bridge.

The implementation lives in ``src/blender_mcp/server.py``. Keep this wrapper
so existing MCP client configurations and tests keep working.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from blender_mcp.server import main, mcp  # noqa: E402,F401

if __name__ == "__main__":
    main()
