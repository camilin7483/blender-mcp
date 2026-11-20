"""GUI smoke test: auth, request IDs, batched messages and main-thread dispatch.

Run with:
    xvfb-run -a blender --factory-startup --python tests/blender/smoke_gui.py

Blender must run with its event loop (no --background), because the add-on
schedules commands with bpy.app.timers. --background never pumps timers.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import sys
import tempfile
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "pro"))

import bpy  # noqa: E402

import blender_mcp as bm  # noqa: E402

TOKEN_DIR = tempfile.mkdtemp(prefix="blendermcp_auth_")
TOKEN_PATH = os.path.join(TOKEN_DIR, "token")
os.environ["BLENDER_MCP_TOKEN_FILE"] = TOKEN_PATH

state: dict[str, object] = {}
queued_checks_done = threading.Event()
dispatch_ready = threading.Event()
release_started = threading.Event()
client_done = threading.Event()
server = bm.BlenderMCPServer(port=0)


def _request(request_id: str, command: str = "get_scene_info", token: str | None = None) -> str:
    payload: dict[str, object] = {"type": command, "params": {}, "request_id": request_id}
    if token:
        payload["auth_token"] = token
    return json.dumps(payload)


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


def client(port: int, token: str) -> None:
    try:
        def mutation(request_id, queue_seconds, disconnect=False):
            payload = json.loads(_request(request_id, "timeout_regression", token))
            payload["queue_timeout_seconds"] = queue_seconds
            payload["cancel_on_disconnect"] = disconnect
            return (json.dumps(payload) + "\n").encode()

        with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
            sock.sendall(mutation("expired", 0.025))
            sock.shutdown(socket.SHUT_WR)  # Legacy half-close still receives a reply.
            state["expired"] = _read_messages(sock, 1)[0]

        with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
            sock.sendall(mutation("abandoned", 4.0, disconnect=True))
            sock.shutdown(socket.SHUT_WR)
            if sock.recv(1):
                raise AssertionError("server returned data to the disconnected client")
        queued_checks_done.set()

        if not dispatch_ready.wait(timeout=15.0):
            raise TimeoutError("Blender's main-thread timer did not start")
        with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
            sock.sendall((_request("smoke-single", token=token) + "\n").encode("utf-8"))
            messages = _read_messages(sock, 1)
            state["single"] = messages[0] if len(messages) == 1 else {"missing": True}

        with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
            sock.sendall(mutation("started", 6.0))
            state["started"] = _read_messages(sock, 1)[0]
        release_started.set()

        with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
            sock.sendall((_request("smoke-bad", token="wrong-token") + "\n").encode("utf-8"))
            messages = _read_messages(sock, 1)
            state["bad_auth"] = messages[0] if len(messages) == 1 else {"missing": True}

        with socket.create_connection(("127.0.0.1", port), timeout=15.0) as sock:
            batch = (
                _request("smoke-batch-a", token=token)
                + "\n"
                + _request("smoke-batch-b", "list_objects", token=token)
                + "\n"
            )
            sock.sendall(batch.encode("utf-8"))
            state["batch"] = _read_messages(sock, 2)
    except Exception:
        state["client_error"] = traceback.format_exc()
    finally:
        queued_checks_done.set()
        release_started.set()
        client_done.set()


def finish() -> None:
    checks: list[str] = []

    bad = state.get("bad_auth")
    if not isinstance(bad, dict) or bad.get("missing"):
        checks.append(f"no bad-auth response (client_error={state.get('client_error')!r})")
    else:
        if bad.get("status") != "error":
            checks.append(f"bad-auth status={bad.get('status')!r}")
        if "Authentication" not in str(bad.get("message", "")):
            checks.append(f"bad-auth message={bad.get('message')!r}")

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

    if (state.get("expired") or {}).get("code") != "request_expired":
        checks.append(f"queued timeout did not expire: {state.get('expired')!r}")
    if (state.get("started") or {}).get("code") != "operation_result_unknown":
        checks.append(f"running timeout did not report uncertain result: {state.get('started')!r}")
    if state.get("mutations") != 1:
        checks.append(f"expected only the started mutation to execute: {state.get('mutations')!r}")

    server.stop()

    if server.last_dispatch_thread != "MainThread":
        checks.append(f"dispatcher thread={server.last_dispatch_thread!r}")
    if server.main_thread_timer_registered:
        checks.append("main-thread timer was not unregistered")

    shutil.rmtree(TOKEN_DIR, ignore_errors=True)

    if checks:
        print("BLENDER_GUI_TEST_FAIL: " + "; ".join(checks))
    else:
        print("BLENDER_GUI_TEST_OK")
    bpy.ops.wm.quit_blender()


def main() -> None:
    worker_result: dict[str, bool] = {}
    worker_server = bm.BlenderMCPServer(port=0)

    def start_from_worker() -> None:
        worker_result["started"] = worker_server.start()

    worker = threading.Thread(target=start_from_worker)
    worker.start()
    worker.join()
    if worker_result.get("started") is not False:
        print("BLENDER_GUI_TEST_FAIL: start() accepted a worker thread")
        bpy.ops.wm.quit_blender()
        return

    server.start()
    if not server.running or server.server_socket is None:
        print("BLENDER_GUI_TEST_FAIL: server did not start")
        bpy.ops.wm.quit_blender()
        return
    if not server.auth_token:
        print("BLENDER_GUI_TEST_FAIL: server started without an auth token")
        server.stop()
        bpy.ops.wm.quit_blender()
        return
    if not os.path.exists(TOKEN_PATH):
        print("BLENDER_GUI_TEST_FAIL: token file was not created")
        server.stop()
        bpy.ops.wm.quit_blender()
        return
    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(TOKEN_PATH).st_mode)
        if mode & 0o077:
            print(f"BLENDER_GUI_TEST_FAIL: token file mode {oct(mode)} is too open")
            server.stop()
            bpy.ops.wm.quit_blender()
            return
    if not server.main_thread_timer_registered:
        print("BLENDER_GUI_TEST_FAIL: persistent main-thread timer not registered")
        server.stop()
        bpy.ops.wm.quit_blender()
        return

    port = server.server_socket.getsockname()[1]
    dispatch = server._execute_command_internal
    state["mutations"] = 0

    def execute(command, params):
        if command == "timeout_regression":
            state["mutations"] += 1
            if not release_started.wait(timeout=12.0):
                raise TimeoutError("client did not observe the running request timeout")
            return {}
        return dispatch(command, params)

    server._execute_command_internal = execute
    threading.Thread(target=client, args=(port, server.auth_token), daemon=True).start()
    # Keep the main thread paused until both queued requests have been cancelled.
    queued_checks_done.wait(timeout=12.0)

    def signal_dispatch_ready():
        dispatch_ready.set()

    deadline = time.monotonic() + 35.0

    def finish_when_client_exits():
        if not client_done.is_set() and time.monotonic() < deadline:
            return 0.1
        finish()
        return None

    bpy.app.timers.register(signal_dispatch_ready, first_interval=0.0)
    bpy.app.timers.register(finish_when_client_exits, first_interval=0.1)


if __name__ == "__main__":
    main()
