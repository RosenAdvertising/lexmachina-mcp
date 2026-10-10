"""MCP protocol and tool metadata conformance checks."""

from __future__ import annotations

import pytest
from mcp import Client
from mcp_types import LATEST_PROTOCOL_VERSION

from lexmachina_mcp.server import mcp


@pytest.mark.asyncio
async def test_server_discovers_as_protocol_revision_2026_07_28() -> None:
    """The 2026 revision uses server/discover instead of initialize."""

    assert LATEST_PROTOCOL_VERSION == "2026-07-28"
    async with Client(mcp) as client:
        assert client.protocol_version == "2026-07-28"
        assert client.session.discover_result is not None
        assert "2026-07-28" in client.session.discover_result.supported_versions


@pytest.mark.asyncio
async def test_all_tools_have_descriptions_input_schemas_and_structured_outputs() -> None:
    async with Client(mcp) as client:
        listed = await client.list_tools()

    assert len(listed.tools) == 14
    assert all(tool.name == tool.name.lower() for tool in listed.tools)
    assert all(" " not in tool.name and "-" not in tool.name for tool in listed.tools)
    assert all(tool.description and "\n" not in tool.description for tool in listed.tools)
    assert all(tool.input_schema.get("type") == "object" for tool in listed.tools)
    assert all(
        tool.output_schema and tool.output_schema.get("type") == "object" for tool in listed.tools
    )
