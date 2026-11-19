"""Contract parity between the FastMCP bridge and the Blender add-on.

This test is intentionally independent from Blender: it parses both source
files and compares the tool surface. Any mismatch means an agent can call a
tool the add-on cannot dispatch, or the reverse.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER = ROOT / "pro" / "mcp_server.py"
ADDON = ROOT / "pro" / "blender_mcp.py"

EXPECTED_TOOL_COUNT = 58


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _is_mcp_tool_decorator(node: ast.expr) -> bool:
    if isinstance(node, ast.Call):
        node = node.func
    return isinstance(node, ast.Attribute) and ast.unparse(node) == "mcp.tool"


def _mcp_tools(tree: ast.Module) -> dict[str, dict[str, list[str]]]:
    tools: dict[str, dict[str, list[str]]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_mcp_tool_decorator(d) for d in node.decorator_list):
            continue
        args = [a.arg for a in node.args.args]
        required = args[: len(args) - len(node.args.defaults)]
        tools[node.name] = {"params": args, "required": required}
    return tools


def _addon_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "BlenderMCPServer":
            return node
    raise AssertionError("BlenderMCPServer class not found")


def _dispatcher_handlers(server_class: ast.ClassDef) -> set[str]:
    for node in server_class.body:
        if not (isinstance(node, ast.FunctionDef) and node.name == "_execute_command_internal"):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "handlers" for t in child.targets):
                continue
            if not isinstance(child.value, ast.Dict):
                continue
            return {
                key.value
                for key in child.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    raise AssertionError("handlers dispatch table not found")


def _addon_methods(server_class: ast.ClassDef) -> dict[str, dict[str, list[str]]]:
    methods: dict[str, dict[str, list[str]]] = {}
    for node in server_class.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        args = [a.arg for a in node.args.args][1:]  # drop self
        required = args[: len(args) - len(node.args.defaults)]
        methods[node.name] = {"params": args, "required": required}
    return methods


def test_tool_surface_parity() -> None:
    tools = _mcp_tools(_parse(MCP_SERVER))
    server_class = _addon_class(_parse(ADDON))
    handlers = _dispatcher_handlers(server_class)
    methods = _addon_methods(server_class)

    assert len(tools) == EXPECTED_TOOL_COUNT, "update EXPECTED_TOOL_COUNT with the new contract"
    assert set(tools) == handlers
    assert set(tools) <= set(methods)

    for name, tool in tools.items():
        assert tool["required"] == methods[name]["required"], (
            f"required parameters differ for {name}: "
            f"bridge={tool['required']} addon={methods[name]['required']}"
        )
        missing = set(tool["params"]) - set(methods[name]["params"])
        assert not missing, (
            f"bridge parameters not accepted by the add-on for {name}: {sorted(missing)}"
        )


def test_every_tool_has_a_docstring() -> None:
    tree = _parse(MCP_SERVER)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_mcp_tool_decorator(d) for d in node.decorator_list):
            continue
        assert ast.get_docstring(node), f"tool '{node.name}' has no docstring"


def test_no_duplicate_tool_names() -> None:
    tree = _parse(MCP_SERVER)
    names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_is_mcp_tool_decorator(d) for d in node.decorator_list)
    ]
    assert len(names) == len(set(names))
