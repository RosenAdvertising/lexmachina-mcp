"""OAuth secrets must never be serialized into URLs."""

import base64
from dataclasses import replace
from urllib.parse import parse_qs

import httpx
import pytest

from lexmachina_mcp.client import LexMachinaClient
from lexmachina_mcp.config import Config, ConfigurationError


def test_query_secret_mode_rejected(config):
    with pytest.raises(ConfigurationError, match="query-string"):
        replace(config, token_auth_method="query")
    with pytest.raises(ConfigurationError, match="form.*basic|basic.*form"):
        Config.from_env(
            {
                "LEX_MACHINA_CLIENT_ID": "synthetic",
                "LEX_MACHINA_CLIENT_SECRET": "synthetic",
                "LEX_MACHINA_TOKEN_AUTH_METHOD": "query",
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["form", "basic"])
async def test_secret_transport_never_uses_query(config, method):
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"access_token": "synthetic", "expires_in": 3600})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = LexMachinaClient(replace(config, token_auth_method=method), http_client=http)
        assert await client._get_access_token() == "synthetic"
    assert len(sent) == 1
    request = sent[0]
    assert request.url.query == b""
    assert config.client_secret not in str(request.url)
    body = parse_qs(request.content.decode())
    if method == "form":
        assert body["client_secret"] == [config.client_secret]
        assert body["client_id"] == [config.client_id]
    else:
        assert (
            base64.b64decode(request.headers["Authorization"].split()[1]).decode()
            == f"{config.client_id}:{config.client_secret}"
        )
        assert "client_secret" not in body


def test_query_mode_verify_is_actionable(monkeypatch, capsys):
    from lexmachina_mcp.setup import verify

    monkeypatch.setenv("LEX_MACHINA_CLIENT_ID", "synthetic")
    monkeypatch.setenv("LEX_MACHINA_CLIENT_SECRET", "synthetic")
    monkeypatch.setenv("LEX_MACHINA_TOKEN_AUTH_METHOD", "query")
    assert verify() == 2
    message = capsys.readouterr().err
    assert "LEX_MACHINA_TOKEN_AUTH_METHOD" in message
    assert "query mode is rejected" in message
