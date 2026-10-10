"""Offline checks for the production Streamable HTTP app."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

import httpx
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from test_spec_2026_07_28 import _modern_request, _result
from test_tools import TOOL_CASES

from lexmachina_mcp import __version__, server


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for key in (
        "LEXMACHINA_MCP_TRANSPORT",
        "LEXMACHINA_MCP_HOST",
        "LEXMACHINA_MCP_ALLOWED_HOSTS",
        "LEXMACHINA_MCP_ALLOWED_ORIGINS",
        "PORT",
        "LEX_MACHINA_CLIENT_ID",
        "LEX_MACHINA_CLIENT_SECRET",
        "LEX_MACHINA_BASE_URL",
        "LEX_MACHINA_TOKEN_AUTH_METHOD",
    ):
        monkeypatch.delenv(key, raising=False)


@asynccontextmanager
async def http_client():
    app = server.create_serve_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8080"
        ) as client,
    ):
        yield client


async def post(client, method, params=None, *, request_id=1, headers=None):
    request_headers, body = _modern_request(method, params, request_id=request_id)
    request_headers.update(headers or {})
    return await client.post("/mcp", headers=request_headers, json=body)


@pytest.mark.asyncio
async def test_http_tools_equal_actual_stdio_names_and_schemas():
    async with Client(
        StdioServerParameters(command=sys.executable, args=["-m", "lexmachina_mcp.server"])
    ) as stdio:
        stdio_tools = await stdio.list_tools()
    async with http_client() as client:
        result = _result(await post(client, "tools/list"))
    assert {tool["name"]: tool["inputSchema"] for tool in result["tools"]} == {
        tool.name: tool.input_schema for tool in stdio_tools.tools
    }
    assert len(result["tools"]) == 14


@pytest.mark.asyncio
async def test_http_read_tool_uses_environment_credentials_and_shared_token_safely(
    monkeypatch, respx_mock, config
):
    monkeypatch.setenv("LEX_MACHINA_CLIENT_ID", config.client_id)
    monkeypatch.setenv("LEX_MACHINA_CLIENT_SECRET", config.client_secret)
    monkeypatch.setenv("LEX_MACHINA_BASE_URL", config.base_url)
    token_route = respx_mock.post(config.token_url).mock(
        return_value=httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})
    )
    route = respx_mock.get(f"{config.base_url}/alerts").mock(
        return_value=httpx.Response(200, json={"alerts": [{"alertId": 6}]})
    )
    async with http_client() as client:
        responses = await asyncio.gather(
            *(
                post(
                    client,
                    "tools/call",
                    {"name": "list_alerts", "arguments": {"limit": 2}},
                    request_id=request_id,
                    headers={"authorization": "Bearer request-credential-must-be-ignored"},
                )
                for request_id in (1, 2)
            )
        )
        for response in responses:
            result = _result(response)
            assert result["isError"] is False
            expected = {"alerts": [{"alertId": 6}], "returnedCount": 1}
            assert result["structuredContent"] == {"result": expected}
            assert json.loads(result["content"][0]["text"]) == expected
    assert token_route.call_count == 1
    assert route.call_count == 2
    assert parse_qs(token_route.calls[0].request.content.decode()) == {
        "grant_type": ["client_credentials"],
        "client_id": [config.client_id],
        "client_secret": [config.client_secret],
    }
    assert all(call.request.headers["authorization"] == "Bearer mock-token" for call in route.calls)
    assert server._client is None


@pytest.mark.asyncio
async def test_http_requests_are_sessionless_and_lifespan_runs_once(monkeypatch):
    events = []
    original_lifespan = server.mcp._lowlevel_server.lifespan

    @asynccontextmanager
    async def observed_lifespan(app):
        events.append("start")
        async with original_lifespan(app) as state:
            yield state
        events.append("stop")

    monkeypatch.setattr(server.mcp._lowlevel_server, "lifespan", observed_lifespan)
    async with http_client() as client:
        shared_client = server._client
        first = await post(client, "tools/list")
        second = await post(client, "tools/list", headers={"mcp-session-id": "unrelated-session"})
        for response in (first, second):
            assert "mcp-session-id" not in response.headers
            assert response.json()["id"] == 1
        assert _result(first) == _result(second)
        assert events == ["start"]
        assert server._client is shared_client
    assert events == ["start", "stop"]
    assert server._client is None


def test_default_transport_remains_stdio(monkeypatch):
    calls = []
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: calls.append(kwargs))
    assert server._requested_transport() == "stdio"
    assert server.main() == 0
    assert calls == [{"transport": "stdio"}]
    monkeypatch.setenv("LEXMACHINA_MCP_TRANSPORT", "  ")
    assert server._requested_transport() == "stdio"


def test_set_but_empty_transport_selects_stdio(monkeypatch):
    calls = []
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("LEXMACHINA_MCP_TRANSPORT", "")
    assert server._requested_transport() == "stdio"
    assert server.main() == 0
    assert calls == [{"transport": "stdio"}]


def test_invalid_transport_names_both_options(monkeypatch):
    monkeypatch.setenv("LEXMACHINA_MCP_TRANSPORT", "bogus")
    with pytest.raises(SystemExit, match="LEXMACHINA_MCP_TRANSPORT.*stdio.*streamable-http"):
        server.main()


def test_http_transport_selection(monkeypatch):
    calls = []

    async def serve():
        calls.append("http")

    monkeypatch.setenv("LEXMACHINA_MCP_TRANSPORT", "  STREAMABLE-HTTP  ")
    monkeypatch.setattr(server, "_serve_streamable_http", serve)
    assert server.main() == 0
    assert calls == ["http"]


def test_host_and_port_defaults_and_invalid_port(monkeypatch):
    assert server._host() == "127.0.0.1"
    assert server._port() == 8080
    monkeypatch.setenv("PORT", " 9000 ")
    assert server._port() == 9000
    monkeypatch.setenv("PORT", "bogus")
    with pytest.raises(SystemExit, match="PORT must be an integer"):
        server._port()


@pytest.mark.parametrize("empty_host", ["", "   "])
def test_empty_host_defaults_to_loopback(monkeypatch, empty_host):
    monkeypatch.setenv("LEXMACHINA_MCP_HOST", empty_host)
    assert server._host() == "127.0.0.1"
    app = server.create_serve_app()
    assert app is not None


def test_uppercase_localhost_is_not_loopback(monkeypatch):
    monkeypatch.setenv("LEXMACHINA_MCP_HOST", "  LOCALHOST  ")
    assert server._host() == "LOCALHOST"
    with pytest.raises(SystemExit, match="LEXMACHINA_MCP_ALLOWED_HOSTS"):
        server.create_serve_app()


def test_server_import_survives_missing_distribution():
    script = "\n".join(
        [
            "import importlib.metadata",
            "_real_version = importlib.metadata.version",
            "def _missing(_distribution_name):",
            "    if 'lexmachina' in str(_distribution_name).lower():",
            "        raise importlib.metadata.PackageNotFoundError(_distribution_name)",
            "    return _real_version(_distribution_name)",
            "importlib.metadata.version = _missing",
            "import lexmachina_mcp.server",
            "print('server-import-ok')",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"},
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "server-import-ok" in completed.stdout


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "mcp.example.test"])
@pytest.mark.parametrize("allowed_hosts", [None, " ,  , "])
def test_non_loopback_requires_allowed_hosts(monkeypatch, host, allowed_hosts):
    monkeypatch.setenv("LEXMACHINA_MCP_HOST", host)
    if allowed_hosts is not None:
        monkeypatch.setenv("LEXMACHINA_MCP_ALLOWED_HOSTS", allowed_hosts)
    with pytest.raises(SystemExit, match="LEXMACHINA_MCP_ALLOWED_HOSTS"):
        server.create_serve_app()


@pytest.mark.asyncio
async def test_explicit_host_and_origin_validation(monkeypatch):
    monkeypatch.setenv("LEXMACHINA_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv(
        "LEXMACHINA_MCP_ALLOWED_HOSTS", " mcp.example.test, other.example.test:8080 "
    )
    monkeypatch.setenv("LEXMACHINA_MCP_ALLOWED_ORIGINS", " https://client.example.test ")
    async with http_client() as client:
        refused_host = await post(client, "tools/list", headers={"host": "attacker.example.test"})
        assert refused_host.status_code == 421
        refused_origin = await post(
            client,
            "tools/list",
            headers={"host": "mcp.example.test", "origin": "https://evil.test"},
        )
        assert refused_origin.status_code == 403
        allowed = await post(
            client,
            "tools/list",
            headers={"host": "mcp.example.test", "origin": "https://client.example.test"},
        )
        assert len(_result(allowed)["tools"]) == 14


@pytest.mark.asyncio
async def test_origin_allowlist_is_optional_and_rejects_unlisted_origins(monkeypatch):
    monkeypatch.setenv("LEXMACHINA_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("LEXMACHINA_MCP_ALLOWED_HOSTS", "127.0.0.1:8080")
    async with http_client() as client:
        assert (
            await post(client, "tools/list", headers={"origin": "https://evil.test"})
        ).status_code == 403
        assert (await post(client, "tools/list")).status_code == 200


@pytest.mark.asyncio
async def test_loopback_has_sdk_host_and_origin_protection():
    async with http_client() as client:
        assert (await post(client, "tools/list", headers={"host": "evil.test"})).status_code == 421
        assert (
            await post(client, "tools/list", headers={"origin": "https://evil.test"})
        ).status_code == 403


@pytest.mark.asyncio
async def test_http_discovery_identity_and_unsupported_methods():
    async with http_client() as client:
        headers, _ = _modern_request("server/discover")
        for method in ("GET", "DELETE"):
            response = await client.request(method, "/mcp", headers=headers)
            assert response.status_code == 405
            assert "mcp-session-id" not in response.headers
        result = _result(await post(client, "server/discover"))
    assert "2026-07-28" in result["supportedVersions"]
    identity = result["_meta"]["io.modelcontextprotocol/serverInfo"]
    assert identity["name"] == "lex-machina"
    assert identity["title"] == "Lex Machina"
    assert identity["version"] == __version__
    assert identity["version"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,arguments,_method,_path,_payload", TOOL_CASES)
async def test_every_tool_propagates_cancellation(
    monkeypatch, tool_name, arguments, _method, _path, _payload
):
    class CancelledClient:
        def __getattr__(self, _name):
            async def cancel(*_args, **_kwargs):
                raise asyncio.CancelledError

            return cancel

    monkeypatch.setattr(server, "_client", CancelledClient())
    with pytest.raises(asyncio.CancelledError):
        await server.mcp.call_tool(tool_name, arguments)


@pytest.mark.asyncio
async def test_http_disconnect_cancels_the_running_read_tool(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    disconnected = asyncio.Event()

    class BlockingClient:
        async def request_json(self, *_args, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    monkeypatch.setattr(server, "_client", BlockingClient())
    app = server.create_serve_app()
    headers, body = _modern_request("tools/call", {"name": "list_alerts", "arguments": {}})
    headers["host"] = "127.0.0.1:8080"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8080),
    }
    body_sent = False

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(_message):
        pass

    async with app.router.lifespan_context(app):
        request = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            disconnected.set()
            await asyncio.wait_for(request, timeout=5)
            assert cancelled.is_set()
        finally:
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
