"""Socket transport and auth token loading for the MCP bridge."""

from __future__ import annotations

import json
import os
import socket
import uuid
from typing import Any, Dict, Optional

from .config import (
    ALLOW_NO_AUTH_ENV_VAR,
    AUTH_TOKEN_ENV_VAR,
    BLENDER_HOST,
    BLENDER_PORT,
    HEAVY_TIMEOUT_COMMANDS,
    MAX_RESPONSE_BYTES,
    TOKEN_FILE_ENV_VAR,
    TOKEN_FILE_NAME,
)


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


def _current_auth_token() -> str:
    """Read the current token, including rotations while the bridge runs."""
    if os.getenv(ALLOW_NO_AUTH_ENV_VAR) == "1":
        return ""
    return _load_auth_token()


def send_blender_command(
    cmd_type: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Send a JSON command to the Blender MCP socket server on localhost:9876."""
    request_id = uuid.uuid4().hex
    token = _current_auth_token()
    if not token and os.getenv(ALLOW_NO_AUTH_ENV_VAR) != "1":
        raise RuntimeError(
            f"No Blender auth token. Start Blender once to create {default_token_path()}, "
            f"or set {AUTH_TOKEN_ENV_VAR}. Set {ALLOW_NO_AUTH_ENV_VAR}=1 only for trusted local use."
        )
    payload: Dict[str, Any] = {
        "type": cmd_type,
        "params": params or {},
        "request_id": request_id,
    }
    if token:
        payload["auth_token"] = token

    eff_timeout = timeout or (
        180.0 if cmd_type in HEAVY_TIMEOUT_COMMANDS else 60.0
    )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(eff_timeout)
        sock.connect((BLENDER_HOST, BLENDER_PORT))
        sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")

        decoder = json.JSONDecoder()
        buffer = bytearray()
        while True:
            data = sock.recv(65536)
            if not data:
                break
            buffer.extend(data)
            if len(buffer) > MAX_RESPONSE_BYTES:
                raise RuntimeError(
                    f"Response from Blender exceeds maximum size ({MAX_RESPONSE_BYTES} bytes)"
                )
            # El objeto JSON solo puede terminar después de una llave de cierre.
            # Esto conserva respuestas antiguas sin salto de línea.
            if not data.rstrip().endswith(b"}"):
                continue
            try:
                text = buffer.decode("utf-8").lstrip()
                resp, _ = decoder.raw_decode(text)
                if not isinstance(resp, dict):
                    raise RuntimeError("Blender response must be a JSON object")
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

    raise RuntimeError(
        f"Disconnected from Blender MCP during '{cmd_type}' without complete response"
    )
