"""Bridge-side token discovery. No Blender required."""

from __future__ import annotations

import mcp_server
import pytest


def test_token_file_is_read(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("BLENDER_AUTH_TOKEN", raising=False)

    assert mcp_server._load_auth_token() == "file-token"


def test_env_token_wins(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("BLENDER_AUTH_TOKEN", "env-token")

    assert mcp_server._load_auth_token() == "env-token"


def test_missing_file_returns_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(tmp_path / "missing"))
    monkeypatch.delenv("BLENDER_AUTH_TOKEN", raising=False)

    assert mcp_server._load_auth_token() == ""


def test_default_path_honors_override(tmp_path, monkeypatch) -> None:
    target = tmp_path / "custom-token"
    monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(target))

    assert mcp_server.default_token_path() == str(target)


def test_send_refuses_without_token(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_current_auth_token", lambda: "")
    monkeypatch.delenv("BLENDER_MCP_ALLOW_NO_AUTH", raising=False)
    monkeypatch.setattr(mcp_server, "default_token_path", lambda: "/nonexistent/token")

    with pytest.raises(RuntimeError, match="No Blender auth token"):
        mcp_server.send_blender_command("get_scene_info")
