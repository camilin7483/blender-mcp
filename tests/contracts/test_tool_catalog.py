"""Contract tests for the tool catalog and discovery surface."""

from __future__ import annotations

import json

import pytest


def _catalog(**kwargs):
    import blender_mcp.server as server

    return json.loads(server.tools_catalog(**kwargs))


def test_catalog_covers_every_active_tool() -> None:
    import blender_mcp.server as server

    data = _catalog(include_schema=False)
    assert data["success"] is True
    assert data["count"] == data["total_tools"] == 235
    assert {entry["name"] for entry in data["tools"]} == set(
        server.mcp._tool_manager._tools
    )


def test_every_catalog_entry_has_metadata() -> None:
    data = _catalog()
    for entry in data["tools"]:
        assert entry["name"]
        assert entry["description"]
        assert entry["category"]
        assert entry["safety"] in {
            "read", "write", "destructive", "privileged", "network"
        }
        assert entry["cost"] in {"low", "medium", "high"}
        assert isinstance(entry["profiles"], list)
        assert entry["profiles"]


def test_catalog_can_filter_by_category() -> None:
    data = _catalog(category="core")
    assert data["count"] > 0
    assert all(entry["category"] == "core" for entry in data["tools"])


def test_describe_returns_schema() -> None:
    import blender_mcp.server as server

    entry = json.loads(server.tools_describe("get_scene_info"))
    assert entry["success"] is True
    assert entry["name"] == "get_scene_info"
    assert entry["input_schema"]["type"] == "object"
    assert "max_objects" in entry["input_schema"]["properties"]


def test_describe_rejects_unknown_tool() -> None:
    import blender_mcp.server as server

    with pytest.raises(ValueError, match="Unknown tool"):
        server.tools_describe("not_a_real_tool")


def test_search_scores_exact_names_first() -> None:
    import blender_mcp.server as server

    data = json.loads(server.tools_search("get_scene_info"))
    assert data["success"] is True
    assert data["matches"][0]["name"] == "get_scene_info"


def test_run_workflow_schema_has_steps() -> None:
    import blender_mcp.server as server

    entry = json.loads(server.tools_describe("run_workflow"))
    assert "steps" in entry["input_schema"]["required"]
