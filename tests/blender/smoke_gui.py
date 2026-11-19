"""GUI smoke test: socket round-trip, request IDs and batched messages.

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


def _request(request_id: str, command: str = "get_scene_info") -> str:
    return json.dumps({"type": command, "params": {}, "request_id": request_id})


def _read_messages(sock: socket.socket, count: int, timeout: float = 10.0) -> list[dict]:
    messages: list[dict] = []
    buffer = b""
    deadline = time.time() + timeout
    while len(messages) < count:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        sock.settimeout(remaining)
        chunk = sock.recv(65536)
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if line.strip():
                messages.append(json.loads(line.decode("utf-8")))
    return messages


def client(port: int) -> None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
            sock.sendall((_request("smoke-single") + "\n").encode("utf-8"))
            messages = _read_messages(sock, 1)
            state["single"] = messages[0] if len(messages) == 1 else {"missing": True}

        with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
            batch = (
                _request("smoke-batch-a")
                + "\n"
                + _request("smoke-batch-b", "list_objects")
                + "\n"
            )
            sock.sendall(batch.encode("utf-8"))
            state["batch"] = _read_messages(sock, 2)
    except Exception:
        state["client_error"] = traceback.format_exc()


def finish() -> None:
    checks: list[str] = []

    single = state.get("single")
    if not isinstance(single, dict) or single.get("missing"):
        checks.append(f"no single response (client_error={state.get('client_error')!r})")
    else:
        if single.get("status") != "success":
            checks.append(f"single status={single.get('status')!r}")
        if single.get("request_id") != "smoke-single":
            checks.append(f"single request_id={single.get('request_id')!r}")
        result = single.get("result") or {}
        if result.get("object_count", 0) < 1:
            checks.append(f"single object_count={result.get('object_count')!r}")

    batch = state.get("batch")
    if not isinstance(batch, list) or len(batch) != 2:
        checks.append(f"batched responses={len(batch) if isinstance(batch, list) else batch!r}")
    else:
        ids = [message.get("request_id") for message in batch]
        if ids != ["smoke-batch-a", "smoke-batch-b"]:
            checks.append(f"batched request_ids={ids!r}")
        if any(message.get("status") != "success" for message in batch):
            checks.append(f"batched statuses={[m.get('status') for m in batch]!r}")

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
    bpy.app.timers.register(finish, first_interval=5.0)


if __name__ == "__main__":
    main()
