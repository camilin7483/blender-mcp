"""GUI smoke test: socket round-trip and main-thread dispatch.

Run with:
    xvfb-run -a blender --factory-startup --python tests/blender/smoke_gui.py

Blender must run with its event loop (no --background), because the add-on
schedules commands with bpy.app.timers. --background never pumps timers.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "pro"))

import bpy  # noqa: E402

import blender_mcp as bm  # noqa: E402

state: dict[str, object] = {}
server = bm.BlenderMCPServer(port=0)


def client(port: int) -> None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
            sock.settimeout(15.0)
            request = json.dumps({"type": "get_scene_info", "params": {}}).encode("utf-8") + b"\n"
            sock.sendall(request)
            raw = sock.recv(65536)
        state["response"] = json.loads(raw.decode("utf-8"))
    except Exception:
        state["client_error"] = traceback.format_exc()


def finish() -> None:
    checks: list[str] = []
    response = state.get("response")
    if not isinstance(response, dict):
        checks.append(f"no response (client_error={state.get('client_error')!r})")
    else:
        if response.get("status") != "success":
            checks.append(f"status={response.get('status')!r}")
        result = response.get("result") or {}
        if result.get("object_count", 0) < 1:
            checks.append(f"object_count={result.get('object_count')!r}")

    if threading.current_thread().name != "MainThread":
        checks.append(f"timer ran on {threading.current_thread().name!r}")

    server.stop()

    if checks:
        print("BLENDER_GUI_TEST_FAIL: " + "; ".join(checks))
    else:
        print("BLENDER_GUI_TEST_OK")
    bpy.ops.wm.quit_blender()


def main() -> None:
    server.start()
    if not server.running or server.server_socket is None:
        print("BLENDER_GUI_TEST_FAIL: server did not start")
        bpy.ops.wm.quit_blender()
        return

    port = server.server_socket.getsockname()[1]
    threading.Thread(target=client, args=(port,), daemon=True).start()
    time.sleep(0.1)
    bpy.app.timers.register(finish, first_interval=3.0)


if __name__ == "__main__":
    main()
