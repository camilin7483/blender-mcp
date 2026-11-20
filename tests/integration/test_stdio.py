"""Exercise the SDK over stdio and the Blender socket response contract."""

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


def test_stdio_bridge():
    asyncio.run(check_bridge())


async def check_bridge():
    calls = []

    async def respond(reader, writer):
        try:
            request = json.loads(await reader.readline())
            calls.append(request.get("type"))
            if request["type"] == "list_objects":
                writer.write(b'{"status": "suc')
                await writer.drain()
                return
            if request["type"] == "get_scene_info":
                response = {"status": "success", "result": {"object_count": 1}}
            else:
                response = {"status": "error", "message": "Fixture object missing"}
            response["request_id"] = (
                "unrelated-id" if request["params"].get("name") == "WrongID" else request["request_id"]
            )
            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async with await asyncio.start_server(respond, "127.0.0.1", 0) as server:
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "pro" / "mcp_server.py")],
            env={
                **os.environ,
                "BLENDER_HOST": "127.0.0.1",
                "BLENDER_PORT": str(server.sockets[0].getsockname()[1]),
                "BLENDER_AUTH_TOKEN": "fixture-token",
                "BLENDER_MCP_ALLOW_NO_AUTH": "0",
                "BLENDER_MCP_PROFILE": "full",
            },
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=10)) as client:
                initialized = await client.initialize()
                assert initialized.capabilities.tools is not None
                tools = (await client.list_tools()).tools
                assert len(tools) == len({tool.name for tool in tools}) == 235
                assert "name" in next(tool for tool in tools if tool.name == "get_object_info").inputSchema["required"]

                info = await client.call_tool("get_scene_info", {})
                assert not info.isError
                assert json.loads(info.content[0].text) == {"object_count": 1}

                invalid = await client.call_tool("get_object_info", {})
                assert invalid.isError
                missing = await client.call_tool("get_object_info", {"name": "Missing"})
                assert missing.isError
                assert "Fixture object missing" in missing.content[0].text
                mismatch = await client.call_tool("get_object_info", {"name": "WrongID"})
                assert mismatch.isError
                assert "request_id mismatch" in mismatch.content[0].text

                disconnected = await client.call_tool("list_objects", {})
                assert disconnected.isError
                assert "without complete response" in disconnected.content[0].text
                assert calls == ["get_scene_info", "get_object_info", "get_object_info", "list_objects"]
