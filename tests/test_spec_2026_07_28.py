"""Offline raw-wire regressions modeled on the supplied Actionstep reference."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from mcp import Client
from mcp.types import LATEST_PROTOCOL_VERSION
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from lexmachina_mcp import server

PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSION = "2025-11-25"
PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"


def _modern_request(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    protocol_version: str = PROTOCOL_VERSION,
    request_id: int = 1,
) -> tuple[dict[str, str], dict[str, Any]]:
    request_params = dict(params or {})
    request_params["_meta"] = {
        PROTOCOL_VERSION_META_KEY: protocol_version,
        CLIENT_CAPABILITIES_META_KEY: {},
        CLIENT_INFO_META_KEY: {"name": "lexmachina-spec-test", "version": "0"},
    }
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "mcp-protocol-version": protocol_version,
        "mcp-method": method,
    }
    if method in ("tools/call", "prompts/get"):
        headers["mcp-name"] = str(request_params["name"])
    elif method == "resources/read":
        headers["mcp-name"] = str(request_params["uri"])
    return headers, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": request_params}


async def _post_modern(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    protocol_version: str = PROTOCOL_VERSION,
    header_overrides: dict[str, str] | None = None,
) -> httpx.Response:
    # Exercise the SDK's raw-wire path independently of the repo entry point.
    app = server.mcp.streamable_http_app(host="127.0.0.1", stateless_http=True)
    headers, body = _modern_request(method, params, protocol_version=protocol_version)
    headers.update(header_overrides or {})
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8080"
        ) as client,
    ):
        return await client.post("/mcp", headers=headers, json=body)


def _result(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    return payload["result"]


def test_spec_pins_the_2026_revision():
    assert LATEST_PROTOCOL_VERSION == PROTOCOL_VERSION
    assert MODERN_PROTOCOL_VERSIONS == (PROTOCOL_VERSION,)


def test_modern_discovery_is_sessionless_and_declares_sdk_capabilities():
    response = asyncio.run(_post_modern("server/discover"))
    result = _result(response)
    assert "mcp-session-id" not in response.headers
    assert result["supportedVersions"] == [PROTOCOL_VERSION]
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 0
    assert result["cacheScope"] == "private"
    assert result["capabilities"] == {
        "prompts": {"listChanged": True},
        "resources": {"listChanged": True, "subscribe": True},
        "tools": {"listChanged": True},
    }
    assert "extensions" not in result["capabilities"]
    assert result["_meta"][SERVER_INFO_META_KEY]["name"] == "lex-machina"


def test_client_negotiates_modern_and_keeps_legacy_compatibility():
    async def negotiate():
        async with Client(server.mcp, cache=None) as modern:
            modern_version = modern.protocol_version
        async with Client(server.mcp, mode="legacy", cache=None) as legacy:
            legacy_version = legacy.protocol_version
        return modern_version, legacy_version

    assert asyncio.run(negotiate()) == (PROTOCOL_VERSION, LEGACY_PROTOCOL_VERSION)


def test_cacheable_results_are_complete_private_and_deterministic():
    async def list_results():
        return [
            _result(await _post_modern(method))
            for method in (
                "tools/list",
                "tools/list",
                "prompts/list",
                "resources/list",
                "resources/templates/list",
            )
        ]

    first, second, prompts, resources, templates = asyncio.run(list_results())
    for result in (first, second, prompts, resources, templates):
        assert result["resultType"] == "complete"
        assert result["ttlMs"] == 0
        assert result["cacheScope"] == "private"
    assert first["tools"] == second["tools"]
    assert len(first["tools"]) == 14
    assert all(tool["inputSchema"]["type"] == "object" for tool in first["tools"])
    assert prompts["prompts"] == []
    assert resources["resources"] == []
    assert templates["resourceTemplates"] == []


def test_modern_tool_results_are_structured_and_complete(monkeypatch):
    class StubClient:
        async def request_json(self, method, path):
            assert (method, path) == ("GET", "/alerts")
            return {"alerts": [{"alertId": 7}]}

    monkeypatch.setattr(server, "_client", StubClient())
    result = _result(
        asyncio.run(_post_modern("tools/call", {"name": "list_alerts", "arguments": {}}))
    )
    assert result["isError"] is False
    assert result["resultType"] == "complete"
    assert result["structuredContent"] == {
        "result": {"alerts": [{"alertId": 7}], "returnedCount": 1}
    }
    assert '"alertId": 7' in result["content"][0]["text"]


def test_unknown_tool_remains_an_is_error_result():
    result = _result(
        asyncio.run(_post_modern("tools/call", {"name": "unknown_tool", "arguments": {}}))
    )
    assert result["isError"] is True


def test_missing_resource_returns_invalid_params():
    response = asyncio.run(_post_modern("resources/read", {"uri": "lexmachina://does-not-exist"}))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32602


def test_modern_http_enforces_routing_headers_versions_and_method_errors():
    named_headers, _ = _modern_request("tools/call", {"name": "list_alerts", "arguments": {}})
    assert named_headers["mcp-protocol-version"] == PROTOCOL_VERSION
    assert named_headers["mcp-method"] == "tools/call"
    assert named_headers["mcp-name"] == "list_alerts"
    mismatch = asyncio.run(
        _post_modern("tools/list", header_overrides={"mcp-method": "resources/list"})
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == -32020
    named_mismatch = asyncio.run(
        _post_modern(
            "tools/call",
            {"name": "list_alerts", "arguments": {}},
            header_overrides={"mcp-name": "get_district_case"},
        )
    )
    assert named_mismatch.status_code == 400
    assert named_mismatch.json()["error"]["code"] == -32020
    unsupported = asyncio.run(_post_modern("tools/list", protocol_version="2099-01-01"))
    assert unsupported.status_code == 400
    assert unsupported.json()["error"] == {
        "code": -32022,
        "message": "Unsupported protocol version",
        "data": {"supported": [PROTOCOL_VERSION], "requested": "2099-01-01"},
    }
    unknown = asyncio.run(_post_modern("example/unknown"))
    assert unknown.status_code == 404
    assert unknown.json()["error"] == {
        "code": -32601,
        "message": "Method not found",
        "data": "example/unknown",
    }
